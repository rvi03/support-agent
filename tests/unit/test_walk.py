"""S11 Resolver gate checks 1-4 and evidence rules (D51, D54, review m2); no services."""

from __future__ import annotations

from typing import Any

import pytest

from support_agent.agent.bindings import Binding, Bindings, default_bindings, proposal_id
from support_agent.agent.state import TriedStep, WalkState, WalkStep
from support_agent.agent.walk import (
    ResolverTurn,
    TriedClaim,
    check_fixed,
    check_step,
    dispatch_kind,
    says_fixed,
    verify_tried,
)
from support_agent.mcp.itsm.registry import default_registry

pytestmark = pytest.mark.unit
PO = "runbooks/printer-offline.md"
PSF = "runbooks/pos-screen-frozen.md"
PRINTER_ACTIONS = {
    a.action_id for a in default_registry().actions if "printer" in a.device_families
}


def steps(doc: str = PO) -> dict[str, Binding]:
    return {b.id: b for b in default_bindings().for_runbook(doc)}


def turn(decision: str = "next", step_id: str | None = None, **over: Any) -> ResolverTurn:
    base: dict[str, Any] = {
        "decision": decision, "step_id": step_id, "reply_quote": None, "tried": [],
        "connection": "unknown", "connection_quote": None, "version_covered": "covered",
        "version_quote": None, "escalate_quote": None, "reason": "r",
    }  # fmt: skip
    return ResolverTurn.model_validate(base | over)


def walk(**over: Any) -> WalkState:
    return WalkState(runbook_id=PO, kb_rev="kb-test").model_copy(update=over)


def done(step_id: str, outcome: str = "replied", kind: str = "store") -> WalkStep:
    return WalkStep(turn=1, step_id=step_id, proposal_id="p", section_id=f"{PO}#x", kind=kind,  # type: ignore[arg-type]
                    outcome=outcome)  # type: ignore[arg-type]  # fmt: skip


# ---- the approved steps ----------------------------------------------------------------


def test_every_it_step_names_a_registry_action_for_its_family() -> None:
    reg = default_registry()
    for doc, items in default_bindings().runbooks.items():
        for b in items:
            if b.audience == "it":
                action = reg.get(b.action_id or "")
                assert action is not None, b.id
                family = "printer" if "printer" in doc else "pos"
                assert family in action.device_families, b.id


def test_proposal_id_is_stable_and_names_the_revision() -> None:
    b = steps()["po-self-test"]
    assert proposal_id("kb-1", b) == proposal_id("kb-1", b)
    assert proposal_id("kb-1", b) != proposal_id("kb-2", b)


def test_bindings_refuse_unknown_prerequisites() -> None:
    b = steps()["po-self-test"].model_dump()
    with pytest.raises(ValueError, match="requires unknown"):
        Bindings.model_validate({"version": 1, "runbooks": {PO: [b | {"requires": ["nope"]}]}})


# ---- check 1: source -------------------------------------------------------------------


def test_unapproved_step_is_refused() -> None:
    check, _ = check_step(turn(step_id="po-made-up"), walk(), steps(), has_action=PRINTER_ACTIONS)
    assert (check.ok, check.check) == (False, 1)


def test_done_and_tried_steps_are_not_sent_again() -> None:
    w = walk(
        steps=[done("po-physical-check")], tried=[TriedStep(step_id="po-self-test", quote="q")]
    )
    for sid, why in (("po-physical-check", "already_done"), ("po-self-test", "already_tried")):
        check, _ = check_step(turn(step_id=sid), w, steps(), has_action=PRINTER_ACTIONS)
        assert not check.ok and check.reason.startswith(why)


def test_reply_quote_must_be_in_the_latest_reply() -> None:
    w = walk(last_event="store_reply", last_text="Light is on, cable is firm.")
    bad = turn(step_id="po-self-test", reply_quote="the printer was replaced")
    good = turn(step_id="po-self-test", reply_quote="cable is firm")
    assert not check_step(bad, w, steps(), has_action=PRINTER_ACTIONS)[0].ok
    assert check_step(good, w, steps(), has_action=PRINTER_ACTIONS)[0].ok


# ---- check 3: dispatch -----------------------------------------------------------------


def test_dispatch_follows_the_binding_not_the_model() -> None:
    s = steps()
    assert dispatch_kind(s["po-self-test"]) == ("send_store", None)
    assert dispatch_kind(s["po-usb-recognition"]) == ("run_action", None)
    assert dispatch_kind(s["po-usb-driver-reinstall"]) == ("l2_task", "unmapped")
    assert dispatch_kind(steps(PSF)["psf-force-quit"]) == ("l2_task", "destructive_store_step")


def test_guarded_it_step_becomes_an_l2_task_never_an_approval() -> None:
    guarded = steps()["po-usb-spooler-restart"].model_copy(
        update={"warnings": ("Do NOT restart the spooler while a print job is running",)}
    )
    assert dispatch_kind(guarded) == ("l2_task", "guard")


def test_prerequisite_needs_a_completed_step_not_a_reported_one() -> None:
    s = steps()
    s["po-usb-clear-queue"] = s["po-usb-clear-queue"].model_copy(
        update={"requires": ("po-usb-spooler-restart",)}
    )
    t = turn(step_id="po-usb-clear-queue")
    reported = walk(tried=[TriedStep(step_id="po-usb-spooler-restart", quote="q")])
    assert check_step(t, reported, s, has_action=PRINTER_ACTIONS)[0].reason.startswith(
        "prerequisite_not_done"
    )
    ran = walk(steps=[done("po-usb-spooler-restart", "fixed", "action")])
    assert check_step(t, ran, s, has_action=PRINTER_ACTIONS)[0].ok


def test_conflict_hands_off_without_repair() -> None:
    s = steps()
    s["po-self-test"] = s["po-self-test"].model_copy(update={"conflict": True})
    check, _ = check_step(turn(step_id="po-self-test"), walk(), s, has_action=PRINTER_ACTIONS)
    assert (check.ok, check.check, check.handoff) == (False, 3, True)


def test_action_for_another_device_family_is_refused() -> None:
    check, _ = check_step(turn(step_id="po-usb-recognition"), walk(), steps(), has_action=set())
    assert not check.ok and check.reason.startswith("action_not_for_device")


# ---- check 4: scope --------------------------------------------------------------------


def test_network_step_blocked_once_the_store_says_usb() -> None:
    w = walk(connection="usb", last_event="store_reply", last_text="It's on USB, light on.")
    t = turn(step_id="po-net-ping", reply_quote="It's on USB")
    check, _ = check_step(t, w, steps(), has_action=PRINTER_ACTIONS)
    assert (check.ok, check.check) == (False, 4)
    assert check_step(turn(step_id="po-usb-recognition", reply_quote="It's on USB"), w, steps(),
                      has_action=PRINTER_ACTIONS)[0].ok  # fmt: skip


def test_version_not_covered_allows_generic_steps_only() -> None:
    w = WalkState(runbook_id=PSF, kb_rev="kb-test", version="not_covered")
    s = steps(PSF)
    assert check_step(turn(step_id="psf-wait"), w, s, has_action=set())[0].ok
    check, _ = check_step(turn(step_id="psf-mouse-test"), w, s, has_action=set())
    assert (check.ok, check.check) == (False, 4)


# ---- evidence (D54) --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("reply", "quote", "ok"),
    [
        ("No, it is still not printing.", "still not printing", False),
        ("Yes! It is printing again now.", "printing again now", True),
        ("We will try it later.", "We will try it later", False),
        ("Does it print now?", "Does it print now?", False),
    ],
)
def test_fixed_needs_the_latest_replys_affirmative_words(reply: str, quote: str, ok: bool) -> None:
    w = walk(last_event="store_reply", last_text=reply)
    assert check_fixed(turn("fixed", reply_quote=quote), w).ok is ok


def test_fixed_after_an_action_needs_an_outcome_of_fixed() -> None:
    assert not check_fixed(turn("fixed"), walk(last_event="action", last_outcome="no_change")).ok
    assert check_fixed(turn("fixed"), walk(last_event="action", last_outcome="fixed")).ok


def test_a_tried_step_or_a_done_l2_task_is_not_a_fix() -> None:
    tried = walk(tried=[TriedStep(step_id="po-self-test", quote="ran the self-test")])
    assert not check_fixed(turn("fixed"), tried).ok
    l2 = walk(last_event="l2_task", last_outcome="done", last_text="done")
    assert not check_fixed(turn("fixed", reply_quote="done"), l2).ok


TICKET = (
    "Printer offline. We restarted the POS application twice this morning. I didn't restart "
    "the spooler. I will reseat the cable after lunch. Should I power cycle the printer?"
)


def test_tried_needs_affirmative_past_tense_words_from_the_ticket() -> None:
    claims = [
        TriedClaim(step_id="po-restart-pos-app", quote="We restarted the POS application twice"),
        TriedClaim(step_id="po-usb-spooler-restart", quote="I didn't restart the spooler"),
        TriedClaim(step_id="po-usb-reconnect", quote="I will reseat the cable"),
        TriedClaim(step_id="po-net-power-cycle", quote="Should I power cycle the printer?"),
        TriedClaim(step_id="po-self-test", quote="we ran the self-test"),  # not in the ticket
    ]
    accepted, rejected = verify_tried(claims, steps(), TICKET)
    assert accepted == [("po-restart-pos-app", "We restarted the POS application twice")]
    assert sorted(r.split(":")[1] for r in rejected) == [
        "negated_or_planned", "negated_or_planned", "negated_or_planned", "quote_not_in_ticket",
    ]  # fmt: skip


def test_every_step_claim_still_sends_steps_with_a_warning() -> None:
    text = "Screen frozen. I already did every step in the runbook."
    claims = [TriedClaim(step_id=s, quote="I already did every step") for s in steps(PSF)]
    accepted, rejected = verify_tried(claims, steps(PSF), text)
    assert "psf-graceful-restart" not in {s for s, _ in accepted}
    assert "psf-graceful-restart:has_warning" in rejected


def test_says_fixed_rejects_still_and_negation() -> None:
    assert says_fixed("it prints again now")
    assert not says_fixed("still offline")
    assert not says_fixed("it doesn't print")
