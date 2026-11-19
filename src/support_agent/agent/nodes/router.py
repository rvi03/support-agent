"""Router (S8 build step 6; agent-architecture.md, 5 Router): a pure function over
the 8-line table, checked top to bottom, first match wins.

    1 SOP escalate-now / conflict / no runbook / low confidence / SLA passed -> handoff
    2 unknown system                                  -> human
    3 not IT / billing / ISP / card processor         -> redirect
    4 too vague, no question asked yet, a missing-fact key chosen -> clarify
    5 too vague, question already asked or no key     -> handoff
    6 Group A + l1_guided or l1_then_l2               -> resolver
    7 Group B + l1_guided or l1_then_l2               -> l1_pack
    8 l2_now / anything else                          -> handoff
"""

from __future__ import annotations

from datetime import datetime

from support_agent.agent.state import PolicyResult, RouteDecision, TriageResult

L1_ROUTES = frozenset({"l1_guided", "l1_then_l2"})


def route(
    triage: TriageResult, policy: PolicyResult, *, clarify_count: int, now: datetime
) -> RouteDecision:
    out = triage.output
    if policy.handoff_reason or now > policy.sla.escalate_by:
        return RouteDecision(route="handoff", rule=1)
    if policy.unknown_system:
        return RouteDecision(route="human", rule=2)
    if policy.redirect_to:
        return RouteDecision(route="redirect", rule=3)
    if out is None:  # policy always sets a reason then; kept as a safe default
        return RouteDecision(route="handoff", rule=8)
    # Dispatch follows Triage's disposition; the too_vague flag is evidence only (D108).
    vague = out.route == "clarify"
    # One question only, and only for an approved missing-fact key (D108).
    if vague and clarify_count == 0 and out.missing_fact is not None:
        return RouteDecision(route="clarify", rule=4)
    if vague:
        return RouteDecision(route="handoff", rule=5)
    l1 = out.route in L1_ROUTES or policy.force_l1
    if l1 and out.group == "A":
        return RouteDecision(route="resolver", rule=6)
    if l1 and out.group == "B":
        return RouteDecision(route="l1_pack", rule=7)
    return RouteDecision(route="handoff", rule=8)
