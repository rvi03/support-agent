"""Policy check (S8 build step 5; agent-architecture.md, 4): pure code.

The model detects SOP triggers in Triage; code enforces them here (D7):

- Escalate-now triggers come from the model (kept even when their evidence does
  not verify: a missed escalation costs more, K2). Any one hands off; it beats
  never-escalate. No keyword rules read the ticket (S8a).
- Never-escalate triggers count only with evidence quoted from the ticket.
  Redirects go to the approved destination key Triage chose (D108: hr, billing,
  isp, card_processor); a billing trigger defaults to billing and not-IT to hr,
  but an ISP-or-card-processor redirect with no key is ambiguous and goes to a
  human (`invalid_output`). The other never-escalate triggers keep an IT ticket
  at L1.
- Hand off: conflict, no verified runbook for an L1 IT route (`no_kb_match`
  only when a search ran), low confidence, real device not found.
- Unknown system -> a human.
- Priority overrides from the SOP, clamped to P1-P4; the SLA is the one for the
  new priority. Every rule that fired is listed for the audit event.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from support_agent.agent.grounding import normalize
from support_agent.agent.state import (
    ESCALATE_NOW,
    Facts,
    Flag,
    HandoffReason,
    PolicyResult,
    Priority,
    RedirectKey,
    TriageResult,
)
from support_agent.intake.schema import MaskedTicket

STORE_TZ = ZoneInfo("Asia/Kolkata")
PEAK_HOURS = ((11, 14), (18, 21))
REPEAT_WINDOW = timedelta(days=30)
REPEAT_MORE_THAN = 2
BILLING: RedirectKey = "billing"
HR: RedirectKey = "hr"
STAY_L1 = frozenset(
    {"how_to", "user_error", "feature_request", "scheduled_maintenance", "connectivity_resolved"}
)
L1_ROUTES = frozenset({"l1_guided", "l1_then_l2"})
DEVICE_FLAGS = frozenset({Flag.ASSET_NOT_FOUND})
PRIORITIES: tuple[Priority, ...] = ("P1", "P2", "P3", "P4")


def is_peak(opened: datetime) -> bool:
    hour = opened.astimezone(STORE_TZ).hour
    return any(start <= hour < end for start, end in PEAK_HOURS)


def repeat_count(ticket: MaskedTicket, facts: Facts, category: str | None) -> int:
    since = ticket.date_opened - REPEAT_WINDOW
    return sum(
        1
        for t in facts.recent_tickets
        if since <= t.date_opened < ticket.date_opened
        and (
            (ticket.asset_id is not None and t.asset_id == ticket.asset_id)
            or (t.store_id == ticket.store_id and category is not None and t.category == category)
        )
    )


def policy(
    ticket: MaskedTicket,
    facts: Facts,
    triage: TriageResult,
    *,
    confidence_min: float,
) -> PolicyResult:
    fired: list[str] = []
    text = f"{ticket.subject}\n{ticket.description}"
    folded = normalize(text)
    out = triage.output

    model_now: set[str] = set()
    never: set[str] = set()
    for hit in out.sop_triggers if out else []:
        verified = len(normalize(hit.evidence)) >= 3 and normalize(hit.evidence) in folded
        if hit.trigger in ESCALATE_NOW:
            model_now.add(hit.trigger)
            if not verified:
                fired.append(f"trigger_unverified_kept:{hit.trigger}")
        elif verified:
            never.add(hit.trigger)
        else:
            fired.append(f"trigger_unverified_dropped:{hit.trigger}")
    escalate_now = sorted(model_now)
    if escalate_now and never:
        fired.append("escalate_now_beats_never_escalate")
        never = set()

    # Redirects (never-escalate, or not IT) to an approved destination key (D108).
    redirect_to: RedirectKey | None = None
    ambiguous_redirect = False
    if not escalate_now and out:
        # Triage's disposition decides (D108, D116); category Other and the not_it flag
        # are evidence, not a route.
        not_it = out.route == "non_it"
        wants = (
            not_it or out.route == "redirect" or bool(never & {"billing", "third_party_service"})
        )
        if wants:
            if out.redirect_to:
                redirect_to = out.redirect_to
            elif "billing" in never:
                redirect_to = BILLING
            elif not_it:
                redirect_to = HR
            else:
                ambiguous_redirect = True
                fired.append("redirect_without_destination")
    if redirect_to:
        fired.append(f"redirect:{redirect_to}")
    force_l1 = bool(not escalate_now and never & STAY_L1)
    if force_l1:
        fired.append("never_escalate_stays_l1")

    unknown_system = Flag.UNKNOWN_SYSTEM in facts.flags or bool(
        out and ("unknown_system" in out.trick_flags or out.route == "human")
    )
    if unknown_system:
        fired.append("unknown_system")

    reason: HandoffReason | None = None
    if out is None:
        reason = triage.handoff_reason or "invalid_output"
    elif escalate_now:
        reason = "sop_trigger"
    elif out.doc_conflicts:
        reason = "conflict"
    elif ambiguous_redirect:
        reason = "invalid_output"
    elif not redirect_to and not unknown_system:
        it_l1 = (out.route in L1_ROUTES or force_l1) and out.group in ("A", "B")
        if it_l1 and out.runbook_id is None:
            reason = "no_kb_match" if triage.searched else "invalid_output"
        elif out.route == "clarify":
            pass  # one question first (router line 4); still vague after it -> line 5
        elif out.confidence < confidence_min:
            reason = "low_confidence"
        elif DEVICE_FLAGS & set(facts.flags) and out.real_device is None:
            reason = "device_not_found"
    if reason:
        fired.append(f"handoff:{reason}")

    # Priority (escalation SOP, Priority Override Rules).
    level = PRIORITIES.index(facts.priority_used)
    if is_peak(ticket.date_opened):
        level -= 1
        fired.append("priority:+1 peak hours")
    category = out.real_category if out else ticket.category
    if repeat_count(ticket, facts, category) > REPEAT_MORE_THAN:
        level -= 1
        fired.append("priority:+1 repeat issue")
    if facts.store and facts.store.store_type == "corporate":
        level -= 1
        fired.append("priority:+1 corporate location")
    if "compliance" in escalate_now:
        level -= 1
        fired.append("priority:+1 compliance")
    # The CMDB bug counts only for the device the model says the ticket is about.
    on_asset = bool(out and facts.asset and out.real_device == facts.asset.asset_type)
    bug = facts.known_bug_cmdb if on_asset else None
    if bug and bug.known_bug and bug.patch_status in ("Yes", "Partial"):
        level += 1
        fired.append("priority:-1 known issue with workaround")
    level = min(max(level, 0), 3)
    manager = "customer_asks" in escalate_now
    if manager:
        level = min(level, 1)
        fired.append("priority:customer escalation P1/P2 + manager")
    priority = PRIORITIES[level]

    return PolicyResult(
        priority=priority,
        sla=facts.sla_by_priority[priority],
        escalate_now=escalate_now,
        never_escalate=sorted(never),
        handoff_reason=reason,
        unknown_system=unknown_system,
        redirect_to=redirect_to,
        force_l1=force_l1,
        rules_fired=fired,
        manager_in_note=manager,
    )
