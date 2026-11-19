"""CP10.4: the evaluator gate (checks 5-8) and the handoff fallback note.

- 5: a phone or this ticket's vault name blocks; the template's own words pass.
- 6: `[SECRET]`, a PIN with a value and `admin/epson` block; a destructive line
  in store text blocks.
- 7: an absent runbook (`runbooks/router-reset.md`) or an unknown section blocks.
- 8: a Clarify or Redirect draft with added instruction text cannot be sent; a
  store message without a kind is refused.
- A handoff note that fails the gate twice falls back to the code-built note,
  which passes the checklist, and the ticket is escalated.

Mock values only (D70).
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from support_agent.agent.gate import Gate, GateOutput, GateResult
from support_agent.agent.llm import TicketBudget
from support_agent.agent.messages import catalogue, clarify, redirect, status_l2, template
from support_agent.agent.nodes.handoff import handoff_node
from support_agent.agent.notes import L2NoteDraft, StepTried, problems
from support_agent.agent.state import TicketState
from support_agent.common.pii_filter import clear_exact_values
from support_agent.intake.reference import build_reference
from support_agent.intake.safety_net import SafetyNet, register_contact
from support_agent.intake.vault import Contact
from tests.unit.agent_fakes import OPENED, facts, output, result, ticket

pytestmark = pytest.mark.unit

TICKET = "T-1"
KB = {"runbooks/printer-offline.md": {"runbooks/printer-offline.md#symptoms"}}


async def _kb_exists(doc: str, section: str | None) -> bool:
    return doc in KB and (section is None or section in KB[doc])


@pytest.fixture
def gate() -> Iterator[Gate]:
    register_contact(TICKET, Contact(full_name="Testa Mockwell", phone="+91-90000-00061"))
    net = SafetyNet(build_reference((), ()), lambda e: 0, actor="test")
    yield Gate(net, _kb_exists, template, catalogue())
    clear_exact_values(TICKET)


def check(gate: Gate, out: GateOutput) -> GateResult:
    return asyncio.run(gate.check(out, TICKET))


def note(text: str) -> GateOutput:
    return GateOutput("l2_note", text, source="Receipt printer offline")


# ---- 5 PII ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Store asks to call back on +91-90000-00062 about the printer.",  # a phone (pattern)
        "Testa reported the printer offline.",  # the vault name
        "Call back on 9000000061.",  # the vault phone
    ],
)
def test_pii_blocks(gate: Gate, text: str) -> None:
    r = check(gate, note(text))
    assert (r.ok, r.check) == (False, 5), r


def test_clean_note_passes(gate: Gate) -> None:
    text = "Receipt printer offline; see runbooks/printer-offline.md#symptoms. Priority P3."
    assert check(gate, note(text)).ok


def test_store_template_with_name_placeholder_passes(gate: Gate) -> None:
    out = GateOutput("store_message", status_l2(TICKET, "P3", OPENED), "status_template")
    assert check(gate, out).ok


# ---- 6 secrets and destructive text ------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "The admin PIN is [SECRET], ask L2.",
        "Log in with admin/epson on the printer page.",
        "Supervisor PIN: 4821 unlocks the void screen.",
        "The password is mockpass99 for the router.",
    ],
)
def test_secret_blocks(gate: Gate, text: str) -> None:
    r = check(gate, note(text))
    assert (r.ok, r.check) == (False, 6), r


def test_password_reset_wording_is_not_a_secret(gate: Gate) -> None:
    assert check(gate, note("The password is expired; L2 must reset it.")).ok


def test_destructive_store_text_blocks(gate: Gate) -> None:
    out = GateOutput("store_message", "Hi {name}, please factory reset the terminal.", "step")
    assert (check(gate, out).check, check(gate, out).reason) == (6, "destructive_instruction")


# ---- 7 invented documents or sections ----------------------------------------------------


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("Follow runbooks/router-reset.md first.", "unknown_kb_ref:runbooks/router-reset.md"),
        (
            "See runbooks/printer-offline.md#factory-mode.",
            "unknown_kb_ref:runbooks/printer-offline.md#factory-mode",
        ),
    ],
)
def test_invented_kb_reference_blocks(gate: Gate, text: str, reason: str) -> None:
    r = check(gate, note(text))
    assert (r.ok, r.check, r.reason) == (False, 7, reason)


# ---- 8 templates only for Redirect and Clarify ---------------------------------------


def test_exact_templates_pass(gate: Gate) -> None:
    assert check(gate, GateOutput("store_message", clarify("device") or "", "clarify", "device")).ok
    assert check(gate, GateOutput("store_message", redirect("hr") or "", "redirect", "hr")).ok


@pytest.mark.parametrize(
    ("kind", "key", "base"),
    [("clarify", "device", clarify("device")), ("redirect", "billing", redirect("billing"))],
)
def test_added_instruction_text_is_not_sent(gate: Gate, kind: str, key: str, base: str) -> None:
    text = base + " Also open services.msc and stop the Print Spooler."
    r = check(gate, GateOutput("store_message", text, kind, key))
    assert (r.ok, r.check, r.reason) == (False, 8, "not_the_approved_template")


def test_unknown_key_and_missing_kind_are_refused(gate: Gate) -> None:
    text = clarify("device") or ""
    assert check(gate, GateOutput("store_message", text, "clarify", "password")).reason == (
        "no_approved_template"
    )
    assert check(gate, GateOutput("store_message", text)).reason == "store_message_without_kind"


# ---- a blocked handoff note falls back to the code-built note ------------------------


class _Llm:
    def __init__(self) -> None:
        self.calls = 0

    async def structured(self, *a: Any, **kw: Any) -> tuple[L2NoteDraft, None]:
        self.calls += 1
        draft = L2NoteDraft(
            summary="Receipt printer offline; ring Testa Mockwell on +91-90000-00061.",
            exact_error="Offline", frequency="persistent",
            steps_tried=[StepTried(step="power cycle", outcome="still offline")],
            devices_affected="one receipt printer", users_affected="front counter",
            business_impact="no receipts at the counter", workaround="handwritten bills",
            version_gap="none",
        )  # fmt: skip
        return draft, None


def test_note_blocked_twice_uses_the_fallback_note(gate: Gate) -> None:
    llm = _Llm()
    state = TicketState(
        ticket=ticket(),
        run_id="00000000-0000-4000-8000-000000000001",
        facts=facts(),
        triage=result(output(route="l2_now")),
        handoff_reason="l2_needed",
    )
    ctx = SimpleNamespace(
        deps=SimpleNamespace(llm=llm, safety_net=gate.safety_net),
        budget=TicketBudget(15, 120_000),
        check=gate.check,
        now=lambda: OPENED + timedelta(minutes=5),
    )
    update = asyncio.run(handoff_node(state, ctx))  # type: ignore[arg-type]
    assert llm.calls == 2  # written, blocked, written once more, blocked
    assert update["note_source"] == "fallback"
    assert update["status"] == "escalated"
    assert [m.split(":")[0] for m in update["_audit"]["misses"]] == ["gate5", "gate5"]
    assert "Testa" not in update["note_text"] and "90000" not in update["note_text"]
    assert "Store contact: on file (vault)" in update["note_text"]
    assert [d.kind for d in update["drafts"]] == ["status_template"]
    # The fallback note passes the same checklist rules as an LLM note.
    from support_agent.agent.notes import build_fallback_note

    assert problems(build_fallback_note(state, OPENED)) == []
