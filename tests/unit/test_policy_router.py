"""CP8.3: Policy check and Router tables (S8 build steps 5-6)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from support_agent.agent.nodes.policy import BILLING, HR, policy
from support_agent.agent.nodes.router import route
from support_agent.agent.state import ESCALATE_NOW, NEVER_ESCALATE, Flag, PolicyResult
from support_agent.mcp.it_data.models import KnownBugResult
from tests.unit.agent_fakes import OPENED, facts, output, recent, result, ticket

pytestmark = pytest.mark.unit

TEXT = "Receipt printer offline\nThe printer shows offline on POS."


def run(out: Any = None, *, f: Any = None, t: Any = None, **res: Any) -> PolicyResult:
    out = output() if out is None else out
    return policy(t or ticket(), f or facts(), result(out, **res), confidence_min=0.5)


def hit(trigger: str, evidence: str = "printer shows offline") -> dict[str, str]:
    return {"trigger": trigger, "evidence": evidence}


def test_17_triggers_in_the_fixed_lists() -> None:
    assert len(ESCALATE_NOW) == 10 and len(NEVER_ESCALATE) == 7


@pytest.mark.parametrize("trigger", sorted(ESCALATE_NOW))
def test_every_escalate_now_trigger_hands_off(trigger: str) -> None:
    p = run(output(sop_triggers=[hit(trigger)]))
    assert p.handoff_reason == "sop_trigger" and trigger in p.escalate_now
    assert route(result(output()), p, clarify_count=0, now=OPENED).route == "handoff"


def test_escalate_now_counts_even_without_verified_evidence() -> None:
    p = run(output(sop_triggers=[hit("payment_failure", "words not in the ticket")]))
    assert p.handoff_reason == "sop_trigger"
    assert "trigger_unverified_kept:payment_failure" in p.rules_fired


@pytest.mark.parametrize(
    ("trigger", "key", "redirect"),
    [("billing", None, BILLING), ("third_party_service", "isp", "isp"),
     ("third_party_service", "card_processor", "card_processor")],
)  # fmt: skip
def test_billing_and_third_party_redirect(trigger: str, key: str | None, redirect: str) -> None:
    p = run(output(sop_triggers=[hit(trigger)], route="redirect", runbook_id=None,
                   runbook_evidence=None, redirect_to=key))  # fmt: skip
    assert p.redirect_to == redirect and p.handoff_reason is None
    assert route(result(output()), p, clarify_count=0, now=OPENED).route == "redirect"


def test_third_party_redirect_without_destination_goes_to_a_human() -> None:
    """D108: an ambiguous ISP-or-card-processor redirect is never guessed."""
    p = run(output(sop_triggers=[hit("third_party_service")], route="redirect", runbook_id=None,
                   runbook_evidence=None))  # fmt: skip
    assert p.redirect_to is None and p.handoff_reason == "invalid_output"
    assert "redirect_without_destination" in p.rules_fired


def test_escalate_now_beats_a_chosen_redirect() -> None:
    p = run(output(sop_triggers=[hit("payment_failure")], route="redirect", redirect_to="isp"))
    assert p.redirect_to is None and p.handoff_reason == "sop_trigger"


@pytest.mark.parametrize(
    "trigger",
    ["how_to", "user_error", "feature_request", "scheduled_maintenance", "connectivity_resolved"],
)
def test_never_escalate_keeps_an_it_ticket_at_l1(trigger: str) -> None:
    out = output(sop_triggers=[hit(trigger)], route="l2_now")
    p = run(out)
    assert p.force_l1 and p.handoff_reason is None
    assert route(result(out), p, clarify_count=0, now=OPENED).route == "resolver"


def test_never_escalate_without_verified_evidence_is_dropped() -> None:
    p = run(output(sop_triggers=[hit("billing", "invoice dispute")]))
    assert p.redirect_to is None and "trigger_unverified_dropped:billing" in p.rules_fired


def test_escalate_now_beats_never_escalate() -> None:
    p = run(output(sop_triggers=[hit("billing"), hit("payment_failure")]))
    assert p.handoff_reason == "sop_trigger" and p.redirect_to is None and p.never_escalate == []
    assert "escalate_now_beats_never_escalate" in p.rules_fired


def test_not_it_redirects_to_hr() -> None:
    out = output(real_category="Other", route="non_it", runbook_id=None, runbook_evidence=None)
    assert run(out).redirect_to == HR


def test_not_it_flag_alone_does_not_redirect() -> None:
    # INC-00127 shape: a real printer fault plus a salary aside (D116).
    out = output(trick_flags=["not_it"])
    assert run(out).redirect_to is None


# ---- no keyword backstop (S8a) --------------------------------------------------


def test_an_outage_the_model_misses_is_not_escalated_by_keywords() -> None:
    outage = ticket(subject="POS down", description="All 3 POS terminals are down since opening.")
    p = run(output(real_category="POS"), t=outage)
    assert p.escalate_now == [] and not any("backstop" in r for r in p.rules_fired)


def test_an_outage_trigger_escalates_even_with_unverified_evidence() -> None:
    out = output(real_category="POS", sop_triggers=[hit("full_pos_outage", "not in the text")])
    p = run(out)
    assert p.handoff_reason == "sop_trigger"
    assert route(result(out), p, clarify_count=0, now=OPENED).route == "handoff"


# ---- other handoffs ------------------------------------------------------------------


def test_conflict_hands_off() -> None:
    disagreement = "soft-serve FAQ and error-code runbook give E-02 different meanings"
    assert run(output(doc_conflicts=[disagreement])).handoff_reason == "conflict"


def test_no_runbook_after_search_is_no_kb_match() -> None:
    out = output(runbook_id=None, runbook_evidence=None)
    assert run(out).handoff_reason == "no_kb_match"
    assert run(out, searched=False).handoff_reason == "invalid_output"


def test_triage_failure_keeps_its_reason() -> None:
    p = policy(ticket(), facts(), result(None, handoff_reason="tool_error"), confidence_min=0.5)
    assert p.handoff_reason == "tool_error"


def test_low_confidence_hands_off_but_not_a_clarify() -> None:
    assert run(output(confidence=0.2)).handoff_reason == "low_confidence"
    out = output(confidence=0.2, route="clarify", trick_flags=["too_vague"])
    assert run(out).handoff_reason is None


def test_real_device_not_found_hands_off() -> None:
    f = facts(flags=[Flag.ASSET_NOT_FOUND], asset_type=None)
    assert run(output(real_device=None), f=f).handoff_reason == "device_not_found"


def test_unknown_system_goes_to_a_human() -> None:
    p = run(f=facts(flags=[Flag.UNKNOWN_SYSTEM]))
    assert p.unknown_system
    assert route(result(output()), p, clarify_count=0, now=OPENED).route == "human"


# ---- priority overrides and SLA ------------------------------------------------------

IST_PEAK = datetime(2026, 1, 5, 7, 0, tzinfo=UTC)  # 12:30 IST


@pytest.mark.parametrize(
    ("kw", "expected", "rule"),
    [
        ({"t": ticket(date_opened=IST_PEAK)}, "P2", "priority:+1 peak hours"),
        ({"f": facts(recent=[recent(1), recent(5), recent(20)])}, "P2", "priority:+1 repeat issue"),
        ({"f": facts(store_type="corporate")}, "P2", "priority:+1 corporate location"),
        ({"out": output(sop_triggers=[hit("compliance")])}, "P2", "priority:+1 compliance"),
        (
            {
                "f": facts(
                    bug=KnownBugResult(
                        status="found",
                        system="Mockprint",
                        version="v1.0",
                        known_bug="Drops jobs",
                        patch_status="Partial",
                    )
                )
            },  # fmt: skip
            "P4",
            "priority:-1 known issue with workaround",
        ),
    ],
)
def test_each_priority_override(kw: dict[str, Any], expected: str, rule: str) -> None:
    p = run(kw.pop("out", None), **kw)
    assert p.priority == expected and rule in p.rules_fired


def test_two_repeats_is_not_a_repeat_and_old_tickets_do_not_count() -> None:
    p = run(f=facts(recent=[recent(1), recent(5), recent(40)]))
    assert p.priority == "P3"


def test_customer_asks_gives_p2_and_the_manager() -> None:
    p = run(output(sop_triggers=[hit("customer_asks")]), f=facts(priority="P4"))
    assert p.priority == "P2" and p.manager_in_note


def test_clamped_to_p1_and_p4() -> None:
    top = run(t=ticket(date_opened=IST_PEAK, priority="P1"), f=facts(priority="P1",
              store_type="corporate"))  # fmt: skip
    assert top.priority == "P1"
    bug = KnownBugResult(status="found", system="Mockprint", version="v1.0", known_bug="x",
                         patch_status="Yes")  # fmt: skip
    assert run(f=facts(priority="P4", bug=bug)).priority == "P4"


@pytest.mark.parametrize(("base", "minutes"), [("P4", 180), ("P3", 90), ("P2", 30)])
def test_sla_is_recomputed_with_the_new_priority(base: str, minutes: int) -> None:
    p = run(f=facts(priority=base, store_type="corporate"))
    assert p.sla.escalation_to_l2_minutes == minutes
    assert p.sla.escalate_by == OPENED + timedelta(minutes=minutes)


# ---- router table --------------------------------------------------------------------


def _p(**over: Any) -> PolicyResult:
    base = run()
    return base.model_copy(update=over)


@pytest.mark.parametrize(
    ("out", "pol", "clarify", "expected", "line"),
    [
        (output(), {"handoff_reason": "sop_trigger"}, 0, "handoff", 1),
        (output(), {"unknown_system": True}, 0, "human", 2),
        (output(), {"redirect_to": BILLING}, 0, "redirect", 3),
        (
            output(route="clarify", trick_flags=["too_vague"], missing_fact="device"),
            {},
            0,
            "clarify",
            4,
        ),
        (
            output(route="clarify", trick_flags=["too_vague"], missing_fact="device"),
            {},
            1,
            "handoff",
            5,
        ),
        (output(route="clarify", trick_flags=["too_vague"]), {}, 0, "handoff", 5),
        (output(trick_flags=["too_vague"]), {}, 0, "resolver", 6),  # a flag is evidence (D108)
        (output(route="l1_then_l2"), {}, 0, "resolver", 6),
        (output(real_category="Soft Serve", real_device="Soft Serve Machine"), {}, 0, "l1_pack", 7),
        (output(route="l2_now"), {}, 0, "handoff", 8),
        (output(route="human"), {}, 0, "handoff", 8),
        (
            output(real_category="POS"),
            {"handoff_reason": "conflict", "redirect_to": BILLING},
            0,
            "handoff",
            1,
        ),  # fmt: skip
    ],
)
def test_router_table(
    out: Any, pol: dict[str, Any], clarify: int, expected: str, line: int
) -> None:
    d = route(result(out), _p(**pol), clarify_count=clarify, now=OPENED)
    assert (d.route, d.rule) == (expected, line)


def test_router_sla_passed_hands_off() -> None:
    late = OPENED + timedelta(hours=10)
    assert route(result(output()), _p(), clarify_count=0, now=late).rule == 1


def test_router_failure_without_output_hands_off() -> None:
    p = policy(ticket(), facts(), result(None, handoff_reason="llm_unavailable"),
               confidence_min=0.5)  # fmt: skip
    assert route(result(None), p, clarify_count=0, now=datetime.now(UTC)).route == "handoff"


def test_policy_text_fixture() -> None:
    assert ticket().subject + "\n" + ticket().description == TEXT
