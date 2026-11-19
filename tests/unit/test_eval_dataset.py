"""S14 build step 1: the Langfuse dataset items (D52, D56, Codex F4)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest

from support_agent.eval import dataset as ds

pytestmark = pytest.mark.unit

TICKET = {
    "ticket_id": "INC-99901",
    "store_id": "STR-9001",
    "store_name": "Mock Store",
    "date_opened": datetime(2026, 11, 1, 9, 30, tzinfo=UTC),
    "priority": "P3",
    "category": "Printer",
    "subcategory": "Offline",
    "subject": "Kitchen printer offline",
    "description": "[PERSON_1] says the printer shows offline on POS-9001-T1.",
    "asset_id": "PRN-9001-01",
    "system_version": None,
    "tags": ["printer"],
    "escalation_flag": False,
    "related_tickets": [],
    "ticket_history": [],
}
LABEL = {
    "correct_routing": "l1_guided",
    "should_escalate": False,
    "escalation_reason": None,
    "expected_agent_action": "guide",
    "relevant_kb_docs": ["runbooks/printer-offline.md"],
    "correct_resolution_summary": "Restart the spooler.",
    "chaos_correct_behavior": "n/a",
    "evaluator_notes": "",
}


def _item(**kw: Any) -> ds.Item:
    args: dict[str, Any] = {
        "half": "tune", "cohort": "labelled", "chaos_type": None, "has_card": False,
    } | kw  # fmt: skip
    label = args.pop("label", LABEL)
    ticket = args.pop("ticket", TICKET)
    return ds.build_item(ticket, label, **args)


def test_item_holds_masked_ticket_replay_id_label_and_tags() -> None:
    item = _item(has_card=True)

    assert item.id == "sw256-INC-99901"
    assert item.input["source_ticket_id"] == "INC-99901"
    assert item.input["date_opened"] == "2026-11-01T09:30:00+00:00"
    assert "system_version" not in item.input  # null fields left out
    assert item.expected_output == LABEL
    assert item.metadata["split"] == "tune"
    assert item.metadata["fault_card"] == "INC-99901"
    assert item.hash.startswith("sha256:")


def test_no_contact_field_reaches_the_item() -> None:
    item = _item(ticket={**TICKET, "submitted_by": "Testa Mockwell", "contact_phone": "x"})

    assert not {"submitted_by", "contact_phone"} & set(item.input)


@pytest.mark.parametrize(
    "where",
    [
        {"ticket": {**TICKET, "description": "Call +91-90000-00001 please"}},
        {"label": {**LABEL, "evaluator_notes": "L1 Agent - Testa Mockwell fixed it"}},
        {"label": {**LABEL, "correct_resolution_summary": "mail test@example.invalid"}},
    ],
)
def test_contact_like_text_refuses_the_item(where: dict[str, Any]) -> None:
    with pytest.raises(ds.DatasetError, match="INC-99901"):
        _item(**where)


def test_hash_changes_with_content_and_card() -> None:
    base = _item()

    assert _item().hash == base.hash
    assert _item(has_card=True).hash != base.hash
    assert _item(label={**LABEL, "evaluator_notes": "new"}).hash != base.hash


def test_counts_must_match_split() -> None:
    split = {
        "tune": {"labelled": ["INC-99901"], "tricky": []},
        "heldout": {"labelled": [], "tricky": []},
    }
    ds.check_counts([_item()], split)

    with pytest.raises(ds.DatasetError, match="split counts"):
        ds.check_counts([_item(), _item(half="heldout")], split)
    with pytest.raises(ds.DatasetError, match="cohort"):
        ds.check_counts([_item(label=None)], split)


@dataclass
class FakeClient:
    remote: dict[str, str | None] | None
    created: bool = False
    upserts: list[str] = field(default_factory=list)

    def existing(self) -> dict[str, str | None] | None:
        return self.remote

    def create(self) -> None:
        self.created = True

    def upsert(self, item: ds.Item) -> None:
        self.upserts.append(item.id)


def test_push_creates_dataset_and_all_items_first_time() -> None:
    client = FakeClient(None)

    result = ds.push(client, [_item()])

    assert client.created
    assert (result.created, result.updated, result.unchanged) == (1, 0, 0)


def test_push_sends_only_changed_items() -> None:
    same, changed = _item(), _item(ticket={**TICKET, "ticket_id": "INC-99902"})
    client = FakeClient({same.id: same.hash, changed.id: "sha256:old"})

    result = ds.push(client, [same, changed])

    assert client.upserts == [changed.id]
    assert (result.created, result.updated, result.unchanged) == (0, 1, 1)


def test_push_stops_on_an_unknown_item() -> None:
    client = FakeClient({"sw256-INC-00000": None})

    with pytest.raises(ds.DatasetError, match="not in the 256"):
        ds.push(client, [_item()])
    assert client.upserts == []
