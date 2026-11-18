"""CP4.3: INC-00298 loses exactly its System chaos line, every other history line
of all 256 tickets is kept, and `status` / `resolution_notes` are rejected."""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import ValidationError

from support_agent.intake.leak_lines import drop_leak_lines, is_leak
from support_agent.intake.masker import Masker
from support_agent.intake.pipeline import process_ticket
from support_agent.intake.schema import HistoryEntry, TicketIn
from tests.unit.test_no_real_pii import DATASET

pytestmark = pytest.mark.unit

MOCK: dict[str, Any] = {
    "ticket_id": "INC-90002",
    "store_id": "SW-9999",
    "date_opened": "2026-04-04T10:01:00+05:30",
    "subject": "Mock printer offline",
    "description": "Mock description.",
}


def _train() -> list[dict[str, Any]]:
    if not (DATASET / "tickets/train").is_dir():
        pytest.skip(f"dataset not found at {DATASET}")
    raws = []
    for path in sorted((DATASET / "tickets/train").glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw.pop("status", None)  # the seed strips them (S3 never stored them)
        raw.pop("resolution_notes", None)
        raws.append(raw)
    return raws


def test_only_the_inc_00298_chaos_line_is_dropped_in_the_dataset() -> None:
    raws = _train()
    assert len(raws) == 256
    dropped = {}
    for raw in raws:
        history = TicketIn.model_validate(raw).ticket_history
        kept = drop_leak_lines(raw["ticket_id"], list(history))
        if len(kept) != len(history):
            dropped[raw["ticket_id"]] = [h for h in history if h not in kept]
        assert kept == [h for h in history if not is_leak(h)]  # order and content kept
    assert list(dropped) == ["INC-00298"]
    (line,) = dropped["INC-00298"]
    assert line.actor == "System" and "chaos type" in line.note


def test_inc_00298_through_the_pipeline_keeps_its_other_lines() -> None:
    raw = next(r for r in _train() if r["ticket_id"] == "INC-00298")
    result = process_ticket(raw, Masker(use_presidio=False))
    assert result.dropped_lines == 1
    assert len(result.ticket.ticket_history) == len(raw["ticket_history"]) - 1
    assert all(h.actor != "System" for h in result.ticket.ticket_history)
    assert "chaos" not in result.ticket.model_dump_json().lower()


@pytest.mark.parametrize(
    ("actor", "note", "leak"),
    [
        ("System", "Escalated due to unknown_system chaos type.", True),
        ("system", "This is a TRICK TICKET for testing", True),
        ("System", "Escalated, chaos_type=duplicate", True),
        ("System", "Auto-assigned to the POS queue", False),
        ("L1 Agent - [PERSON_1]", "Store said chaos type is unclear", False),
        (None, "chaos type", False),
    ],
)
def test_leak_rule(actor: str | None, note: str, leak: bool) -> None:
    assert is_leak(HistoryEntry(actor=actor, note=note)) is leak


@pytest.mark.parametrize("field", ["status", "resolution_notes"])
def test_forbidden_fields_are_rejected(field: str) -> None:
    with pytest.raises(ValidationError, match=f"forbidden fields: {field}"):
        TicketIn.model_validate({**MOCK, field: "Mock value"})


def test_forbidden_field_rejected_even_when_empty() -> None:
    with pytest.raises(ValidationError):
        TicketIn.model_validate({**MOCK, "status": None})


def test_unknown_fields_are_dropped_not_rejected() -> None:
    ticket = TicketIn.model_validate({**MOCK, "mock_extra": "x", "priority_hint": "P1"})
    assert "mock_extra" not in ticket.model_dump()
