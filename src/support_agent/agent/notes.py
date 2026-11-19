"""L2 note and L1 pack schemas (S10 build steps 4, 5; escalation SOP, Required
Information Checklist).

- `L2NoteDraft` is what the model writes (one call, strict JSON): the fields that
  need reading the ticket. Code fills every fact field (ids, store, contact,
  timestamps, priority, reason, trigger, warranty, KB consulted), so the model
  cannot get them wrong.
- `L2Note` is the full note. Each field is required, conditional (with its
  condition) or may be `unavailable: <reason>`. A required field can't be
  unavailable or a placeholder; `contact` holds only `on file (vault)` (D43).
- `build_fallback_note(state)` builds the same `L2Note` from facts alone (no LLM
  text), so a blocked or failed note still passes the same checklist check.
- `L1Pack` is the human-L1 brief (Group B); every claim cites section ids.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from support_agent.agent.state import TicketState

UNAVAILABLE = "unavailable:"
CONTACT_ON_FILE = "on file (vault)"
_PLACEHOLDER = re.compile(
    r"(?i)^\s*(?:|-+|n/?a|none|null|tbd|todo|unknown|not known|not available|\?+|\[.*\]|"
    r"<.*>|x+)\s*$"
)


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# ---- L2 note --------------------------------------------------------------------------


class StepTried(_Model):
    step: str
    outcome: str


class L2NoteDraft(_Model):
    """The model's part of the note. Write `unavailable: <reason>` when the data does
    not hold a value."""

    summary: str = Field(description="Two or three sentences: device, symptom, why L2 now.")
    exact_error: str = Field(description="The error code or message exactly as reported.")
    frequency: str = Field(description="one-time, intermittent or persistent, from the text.")
    steps_tried: list[StepTried] = Field(
        description="Each step from the history, the description and this run, with its outcome."
    )
    devices_affected: str
    users_affected: str
    business_impact: str
    workaround: str
    version_gap: str = Field(description="Runbook does not cover the version, or 'none'.")


Rule = Literal["required", "may_be_unavailable", "conditional"]

# Field -> (label, rule). Order is the order of the rendered note.
FIELDS: dict[str, tuple[str, Rule]] = {
    "ticket_id": ("Ticket ID", "required"),
    "summary": ("Executive summary", "required"),
    "store": ("Store", "required"),
    "asset_id": ("Asset ID", "may_be_unavailable"),
    "asset_type": ("Asset type", "required"),
    "contact": ("Store contact", "required"),
    "exact_error": ("Error code or message", "may_be_unavailable"),
    "first_occurrence": ("First occurrence", "required"),
    "frequency": ("Frequency", "may_be_unavailable"),
    "steps_tried": ("Steps tried and outcome", "may_be_unavailable"),
    "kb_consulted": ("KB resources consulted", "may_be_unavailable"),
    "devices_affected": ("Devices affected", "may_be_unavailable"),
    "users_affected": ("Users affected", "may_be_unavailable"),
    "business_impact": ("Business impact", "required"),
    "workaround": ("Workaround", "may_be_unavailable"),
    "priority": ("Priority and overrides", "required"),
    "escalation_reason": ("Escalation reason", "required"),
    "sop_trigger": ("SOP trigger and evidence", "conditional"),  # reason sop_trigger
    "warranty": ("Warranty", "conditional"),  # asset known
    "conflicts": ("Document conflicts", "conditional"),  # reason conflict
    "version_gap": ("Version coverage gap", "may_be_unavailable"),
    "escalated_at": ("Escalated at", "required"),
}


class L2Note(_Model):
    ticket_id: str
    summary: str
    store: str
    asset_id: str
    asset_type: str
    contact: str
    exact_error: str
    first_occurrence: str
    frequency: str
    steps_tried: str
    kb_consulted: str
    devices_affected: str
    users_affected: str
    business_impact: str
    workaround: str
    priority: str
    escalation_reason: str
    sop_trigger: str | None
    warranty: str | None
    conflicts: str | None
    version_gap: str
    escalated_at: str
    queue: Literal["l2", "vendor"] = "l2"
    source: Literal["llm", "fallback"] = "llm"

    def render(self) -> str:
        lines = []
        for name, (label, _rule) in FIELDS.items():
            value = getattr(self, name)
            if value is not None:
                lines.append(f"{label}: {value}")
        return "\n".join(lines)


def is_real(value: str | None) -> bool:
    return value is not None and not _PLACEHOLDER.match(value) and len(value.strip()) >= 2


def problems(note: L2Note) -> list[str]:
    """The agent's own checklist check before a note is used (the eval re-checks the
    stored text independently, `eval/metrics/k15a.py`)."""
    out: list[str] = []
    for name, (_label, rule) in FIELDS.items():
        value = getattr(note, name)
        unavailable = isinstance(value, str) and value.strip().lower().startswith(UNAVAILABLE)
        if rule == "required" and (not is_real(value) or unavailable):
            out.append(f"{name}:missing")
        elif rule == "may_be_unavailable":
            if unavailable and not is_real(value.split(":", 1)[1]):
                out.append(f"{name}:unavailable_without_reason")
            elif not unavailable and not is_real(value):
                out.append(f"{name}:placeholder")
    if note.contact != CONTACT_ON_FILE:
        out.append("contact:not_on_file")
    if note.escalation_reason.startswith("sop_trigger") and not is_real(note.sop_trigger):
        out.append("sop_trigger:missing")
    if note.escalation_reason.startswith("conflict") and not is_real(note.conflicts):
        out.append("conflicts:missing")
    if not note.asset_id.lower().startswith(UNAVAILABLE) and not is_real(note.warranty):
        out.append("warranty:missing")
    return out


# ---- facts the code fills ------------------------------------------------------------


def _iso(at: datetime) -> str:
    return at.isoformat(timespec="minutes")


def _store(state: TicketState) -> str:
    s = state.facts.store if state.facts else None
    if s is None:
        return state.ticket.store_id
    return f"{s.store_id} {s.store_name}, {s.neighborhood}, {s.city} ({s.store_type})"


def _asset(state: TicketState) -> tuple[str, str, str | None]:
    """(asset_id, asset_type, warranty) from the CMDB when the asset is the real device."""
    t, f = state.ticket, state.facts
    out = state.triage.output if state.triage else None
    real_device = out.real_device if out else None
    asset = f.asset if f else None
    if asset is None:
        why = "not in the CMDB" if t.asset_id else "no asset linked"
        aid = f"unavailable: {t.asset_id or 'none'} {why}"
        return aid, real_device or "unavailable: device not established", None
    warranty = (
        f"in warranty ({asset.warranty_days_left} days left): vendor route"
        if asset.in_warranty
        else f"expired {asset.warranty_expiry}: paid repair"
    )
    if real_device and real_device != asset.asset_type:
        return (
            f"unavailable: linked {asset.asset_id} is a {asset.asset_type}, not the "
            f"{real_device} (asset not verified)",
            real_device,
            None,
        )
    kind = f"{asset.asset_type} ({asset.make} {asset.model}, {asset.system_version})"
    return asset.asset_id, kind, warranty


def _priority(state: TicketState) -> str:
    p = state.policy
    if p is None:
        return f"{state.ticket.priority or 'P3'} (ticket priority; policy not reached)"
    overrides = [r.split(":", 1)[1] for r in p.rules_fired if r.startswith("priority:")]
    return f"{p.priority}" + (f" ({'; '.join(overrides)})" if overrides else " (no overrides)")


def _reason(state: TicketState) -> str:
    reason = state.handoff_reason or "l2_now"
    out = state.triage.output if state.triage else None
    detail = out.reason if out and reason in ("sop_trigger", "l2_now", "conflict") else None
    return f"{reason}: {detail}" if detail else reason


def _trigger(state: TicketState) -> str | None:
    out = state.triage.output if state.triage else None
    if not out or not state.policy or not state.policy.escalate_now:
        return None
    hits = [h for h in out.sop_triggers if h.trigger in state.policy.escalate_now]
    return "; ".join(f'{h.trigger} ("{h.evidence}")' for h in hits) or None


def _kb(state: TicketState) -> str:
    docs = list(state.kb_consulted)
    return ", ".join(docs) if docs else "unavailable: no KB document matched or was read"


def facts_fields(state: TicketState, now: datetime) -> dict[str, str | None]:
    aid, atype, warranty = _asset(state)
    out = state.triage.output if state.triage else None
    return {
        "ticket_id": state.ticket.ticket_id,
        "store": _store(state),
        "asset_id": aid,
        "asset_type": atype,
        "contact": CONTACT_ON_FILE,
        "first_occurrence": f"reported {_iso(state.ticket.date_opened)}",
        "kb_consulted": _kb(state),
        "priority": _priority(state),
        "escalation_reason": _reason(state),
        "sop_trigger": _trigger(state),
        "warranty": warranty,
        "conflicts": "; ".join(out.doc_conflicts) if out and out.doc_conflicts else None,
        "escalated_at": _iso(now),
    }


def walk_lines(state: TicketState) -> list[str]:
    """The Resolver walk as code saw it (S11): each step, who did it, the outcome."""
    walk = state.walk
    if walk is None:
        return []
    lines = [f"tried before (ticket): {t.step_id}" for t in walk.tried]
    for s in walk.steps:
        what = f"{s.step_id} ({s.kind}{', ' + s.action_id if s.action_id else ''})"
        lines.append(f"walk turn {s.turn}: {what} -> {s.outcome}"
                     + (f": {' '.join(s.result.split())[:200]}" if s.result else ""))  # fmt: skip
    if walk.end_reason:
        lines.append(f"walk ended: {walk.end_reason[:200]}")
    return lines


def _steps_text(steps: list[StepTried]) -> str:
    if not steps:
        return "unavailable: no steps recorded before escalation"
    return "; ".join(f"{n}) {s.step} -> {s.outcome}" for n, s in enumerate(steps, 1))


NO_GAP = "none: the runbook covers this version"


def _version_gap(value: str) -> str:
    """The draft schema asks for 'none' when there is no gap; that is a real answer."""
    return NO_GAP if value.strip().strip(".").lower() in ("none", "no", "no gap") else value


def code_words(state: TicketState, now: datetime) -> str:
    """Every value code filled into the note from facts: words a name detector may read
    as a person (a city or neighbourhood) but which are not personal data (D111)."""
    return "\n".join(v for v in facts_fields(state, now).values() if v)


def build_note(state: TicketState, draft: L2NoteDraft, now: datetime) -> L2Note:
    return L2Note(
        **facts_fields(state, now),
        summary=draft.summary,
        exact_error=draft.exact_error,
        frequency=draft.frequency,
        steps_tried=_steps_text(draft.steps_tried),
        devices_affected=draft.devices_affected,
        users_affected=draft.users_affected,
        business_impact=draft.business_impact,
        workaround=draft.workaround,
        version_gap=_version_gap(draft.version_gap),
        queue=queue_for(state),
    )


def queue_for(state: TicketState) -> Literal["l2", "vendor"]:
    return "l2"


def build_fallback_note(state: TicketState, now: datetime) -> L2Note:
    """Facts only, no LLM text (S10 build step 4): the ticket's own words, quoted."""
    t = state.ticket
    out = state.triage.output if state.triage else None
    device = (out.real_device if out else None) or t.category or "device"
    history = [f"history: {h.note}" for h in t.ticket_history if h.note.strip()]
    done = [*history, *walk_lines(state)]
    steps = (
        "; ".join(f"{n}) {h}" for n, h in enumerate(done, 1))
        if done
        else "unavailable: no steps in the ticket history"
    )
    walk = state.walk
    gap = "unavailable: not assessed (code-built note)"
    if walk is not None and walk.version is not None:
        gap = (f"not covered ({walk.version}): runbook {walk.runbook_id} does not list this "
               "device version; generic steps only" if walk.generic_only else NO_GAP)  # fmt: skip
    description = " ".join(t.description.split())
    return L2Note(
        **facts_fields(state, now),
        summary=(
            f"{device}: {t.subject}. Handed to L2 with reason "
            f"{state.handoff_reason or 'l2_now'}; this note was built by code from the ticket."
        ),
        exact_error="unavailable: see the store's description under Business impact",
        frequency="unavailable: not stated in a form code can read",
        steps_tried=steps,
        devices_affected="unavailable: not stated in a form code can read",
        users_affected="unavailable: not stated in a form code can read",
        business_impact=f'as reported by the store: "{description[:600]}"',
        workaround="unavailable: none recorded",
        version_gap=gap,
        queue=queue_for(state),
        source="fallback",
    )


# ---- L1 pack ---------------------------------------------------------------------------


class Claim(_Model):
    text: str
    section_ids: list[str] = Field(description="Section ids of the runbook this line rests on.")


class L1Pack(_Model):
    issue: str = Field(description="What the issue really is: device, category, any trick.")
    path: list[Claim] = Field(description="Which runbook path fits and why.")
    known_bug_fix: str = Field(description="Known-bug fix for the version, or 'none'.")
    version_warning: str = Field(description="Runbook does not cover the version, or 'none'.")
    skip: list[str] = Field(description="Steps already tried: L1 skips these.")
    first_questions: list[str] = Field(description="What to ask the store first.")
    when_to_escalate: list[Claim]

    def render(self, runbook_id: str) -> str:
        def claims(items: list[Claim]) -> str:
            return "\n".join(f"- {c.text} [{', '.join(c.section_ids)}]" for c in items) or "- none"

        bullets = "\n".join(f"- {s}" for s in self.skip) or "- none"
        questions = "\n".join(f"- {q}" for q in self.first_questions) or "- none"
        return (
            f"L1 pack for {runbook_id}\n"
            f"Issue: {self.issue}\n"
            f"Path:\n{claims(self.path)}\n"
            f"Known-bug fix: {self.known_bug_fix}\n"
            f"Version warning: {self.version_warning}\n"
            f"Already tried (skip):\n{bullets}\n"
            f"Ask the store first:\n{questions}\n"
            f"When to escalate:\n{claims(self.when_to_escalate)}"
        )

    def section_ids(self) -> list[str]:
        return [s for c in (*self.path, *self.when_to_escalate) for s in c.section_ids]
