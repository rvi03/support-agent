"""CP10.6: the independent K15a checker (eval/k15a.py) on stored note text.

A full LLM-shaped note and the code-built fallback note pass; a note with
`Steps tried` removed by hand, a note with every field `unavailable`, and a note
whose only filled field is the contact marker fail. The checker imports no agent
code (D42). Mock values only (D70).
"""

from __future__ import annotations

import ast
from datetime import timedelta
from pathlib import Path

import pytest

from support_agent.agent.notes import L2NoteDraft, StepTried, build_fallback_note, build_note
from support_agent.agent.state import TicketState
from support_agent.eval import k15a
from tests.unit.agent_fakes import OPENED, facts, output, result, ticket

pytestmark = pytest.mark.unit


def _state(reason: str = "l2_needed") -> TicketState:
    return TicketState(
        ticket=ticket(),
        run_id="00000000-0000-4000-8000-000000000002",
        facts=facts(),
        triage=result(output(route="l2_now")),
        handoff_reason=reason,  # type: ignore[arg-type]
    )


def _llm_note() -> str:
    draft = L2NoteDraft(
        summary="Receipt printer offline after a power cycle; L2 needed.",
        exact_error="Printer shows Offline", frequency="persistent",
        steps_tried=[StepTried(step="power cycle the printer", outcome="still offline")],
        devices_affected="one receipt printer", users_affected="front counter staff",
        business_impact="no printed receipts at the counter", workaround="handwritten bills",
        version_gap="none",
    )  # fmt: skip
    return build_note(_state(), draft, OPENED + timedelta(minutes=5)).render()


def test_llm_note_passes() -> None:
    r = k15a.check(_llm_note())
    assert r.ok, r.problems


def test_fallback_note_passes() -> None:
    r = k15a.check(build_fallback_note(_state(), OPENED).render())
    assert r.ok, r.problems


def test_steps_tried_removed_by_hand_fails() -> None:
    note = "\n".join(
        line for line in _llm_note().splitlines() if not line.startswith("Steps tried")
    )
    r = k15a.check(note)
    assert not r.ok and "Steps tried and outcome: missing" in r.problems


def test_every_field_unavailable_fails() -> None:
    note = "\n".join(f"{label}: unavailable: not known" for label in k15a.LABELS)
    r = k15a.check(note)
    assert not r.ok
    assert {f"{label}: not a real value" for label in k15a.REQUIRED} <= set(r.problems)


def test_only_the_contact_filled_fails() -> None:
    note = "Store contact: on file (vault)"
    r = k15a.check(note)
    assert not r.ok and "Ticket ID: missing" in r.problems
    assert "Store contact: not 'on file (vault)'" not in r.problems


def test_contact_marker_does_not_fill_another_field() -> None:
    note = _llm_note().replace("Business impact: ", "Business impact: on file (vault)", 1)
    note = note.replace("on file (vault)no printed receipts at the counter", "on file (vault)")
    assert "Business impact: holds only the contact marker" in k15a.check(note).problems


def test_a_name_or_phone_as_contact_fails() -> None:
    note = _llm_note().replace("Store contact: on file (vault)", "Store contact: +91-90000-00071")
    problems = k15a.check(note).problems
    assert "Store contact: not 'on file (vault)'" in problems
    assert "Store contact: holds a phone number" in problems


def test_sop_trigger_required_for_a_trigger_escalation() -> None:
    note = build_fallback_note(_state("sop_trigger"), OPENED).render()
    assert "SOP trigger and evidence: required for an SOP-trigger escalation" in (
        k15a.check(note).problems
    )


def test_checker_imports_no_agent_code() -> None:
    tree = ast.parse(Path(k15a.__file__).read_text())
    mods = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    mods += [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
    assert not [m for m in mods if m.startswith("support_agent")], mods


@pytest.mark.parametrize(
    ("text", "phone"),
    [
        ("expired 2025-03-14: paid repair", False),
        ("reported 2025-11-22T10:28+05:30", False),
        ("history 2025-11-22 10:28 power cycle", False),
        ("+91-90000-00071", True),
        ("call 90000 00071", True),
    ],
)
def test_dates_are_not_phones(text: str, phone: bool) -> None:
    assert bool(k15a._PHONE.search(text)) is phone
