"""Graph state and node models (S8 build step 1; agent-architecture.md, Shared state).

Every node's input and output is a Pydantic model, so a malformed value fails
at the node that made it. `TicketState` is the per-ticket state the S10 graph
carries; S8 fills `facts`, `triage`, `policy` and `route`.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from support_agent.intake.schema import MaskedTicket
from support_agent.mcp.it_data.models import (
    Asset,
    AssetSummary,
    KnownBugResult,
    SlaResult,
    Store,
    TicketSummary,
)


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# ---- Enrich -----------------------------------------------------------------------------


class Flag(StrEnum):
    """Facts Enrich flags by comparing data, never by reading the ticket's text
    (S8a): whether the text's device fits the store is Triage's judgement."""

    ASSET_NOT_FOUND = "asset_not_found"  # E4: the linked asset id is not in the CMDB
    UNKNOWN_SYSTEM = "unknown_system"  # E5: the ticket's system is not in the version matrix
    VERSION_MISMATCH = "version_mismatch"  # the ticket's system_version differs from the CMDB


class Facts(_Model):
    store: Store | None
    asset: Asset | None
    store_assets: list[AssetSummary]
    recent_tickets: list[TicketSummary]
    sla: SlaResult
    # The SLA for every priority, so Policy recomputes deadlines without a call.
    sla_by_priority: dict[str, SlaResult]
    # The ticket's priority as used for the first SLA lookup (P3 when missing or invalid).
    priority_used: str
    known_bug_cmdb: KnownBugResult | None  # for the linked asset's version (the truth)
    known_bug_ticket: KnownBugResult | None  # for the ticket's own system_version
    flags: list[Flag]


# ---- Triage -----------------------------------------------------------------------------

Category = Literal[
    "POS", "Printers", "Online Orders", "Wi-Fi / Network", "Soft Serve", "Kiosks", "Other"
]  # fmt: skip
Group = Literal["A", "B", "C"]
Route = Literal["l1_guided", "l1_then_l2", "l2_now", "non_it", "redirect", "clarify", "human"]
GROUP_A = frozenset({"POS", "Printers"})

TrickFlag = Literal[
    "wrong_category",
    "wrong_device",
    "fake_device",
    "unknown_system",
    "cited_unrelated_ticket",
    "steps_already_tried",
    "angry_tone",
    "not_it",
    "too_vague",
]

EscalateNow = Literal[
    "payment_failure",
    "full_pos_outage",
    "data_loss",
    "security_incident",
    "network_failure",
    "third_party_integration_failure",
    "error_not_in_kb",
    "customer_waited_30_min",
    "compliance",
    "customer_asks",
]
NeverEscalate = Literal[
    "how_to",
    "user_error",
    "billing",
    "scheduled_maintenance",
    "feature_request",
    "third_party_service",
    "connectivity_resolved",
]
ESCALATE_NOW: frozenset[str] = frozenset(EscalateNow.__args__)  # type: ignore[attr-defined]
NEVER_ESCALATE: frozenset[str] = frozenset(NeverEscalate.__args__)  # type: ignore[attr-defined]


class TriggerHit(_Model):
    trigger: EscalateNow | NeverEscalate
    evidence: str = Field(description="A quote from the ticket's subject or description.")


# Approved redirect destinations (D108): code owns the directory and contact details.
RedirectKey = Literal["hr", "billing", "isp", "card_processor"]
# The one fact a Clarify question may ask for (D108): one approved template per key.
MissingFact = Literal["device", "error_message", "symptom", "scope", "when_started"]


class RunbookEvidence(_Model):
    section_id: str
    quote: str


class TriageOutput(_Model):
    """What the model submits (the strict JSON schema of `submit_triage`)."""

    real_category: Category
    real_device: str | None
    trick_flags: list[TrickFlag]
    runbook_id: str | None
    runbook_evidence: RunbookEvidence | None
    sop_triggers: list[TriggerHit]
    # Documents the model read that disagree on a fact this ticket depends on, each
    # as one short line naming both documents and the fact.
    doc_conflicts: list[str]
    route: Route
    # Set only with route redirect or non_it: where the store should go (D108).
    redirect_to: RedirectKey | None = None
    # Set only with route clarify: the one fact the question asks for (D108).
    missing_fact: MissingFact | None = None
    reason: str
    confidence: float = Field(ge=0.0, le=1.0)

    @property
    def group(self) -> Group:
        """From the real category, never from the ticket's field (E8)."""
        if self.real_category in GROUP_A:
            return "A"
        return "C" if self.real_category == "Other" else "B"


HandoffReason = Literal[
    "no_kb_match",
    "tool_error",
    "budget_exceeded",
    "invalid_output",
    "llm_unavailable",
    "sop_trigger",
    "conflict",
    "gate_block",
    "sla_breach",
    "moderation",
    "low_confidence",
    "device_not_found",
    "unknown_system",  # router line 2: a person checks the system (S10)
    "l2_needed",  # Triage judged L2 now with no SOP trigger (router line 8)
    "still_vague",  # one question asked, still not actionable (router line 5)
    "steps_exhausted",  # S11: the walk found no approved step left or met an escalate condition
    "approval_rejected",  # S11: the approver rejected the action (reason in the note)
    "version_not_covered",  # S11: generic steps used up on a device the runbook does not cover
    "kb_rev_changed",  # S11: the KB revision changed during the walk (D18)
    "no_approved_steps",  # S11: the runbook has no approved walk steps (bindings.yaml)
]


class TriageResult(_Model):
    """Triage after code checks: the output with an unverified runbook removed and
    only register conflicts kept, or the reason it failed."""

    output: TriageOutput | None
    handoff_reason: HandoffReason | None  # set only when output is None
    searched: bool  # search_kb ran at least once
    quote_check: str | None  # "verified" or why the citation was dropped
    cited_runbook: str | None = None  # what the model cited, kept for the audit event
    cited: RunbookEvidence | None = None
    tool_calls: int
    first_try_valid: bool
    kb_rev: str | None
    documents_read: list[str] = Field(default_factory=list)  # for the L2 note (S10)

    @property
    def abstained(self) -> bool:
        """Triage's own `no_kb_match` (D57): a valid output with no verified runbook
        after a search ran. Policy may report a stronger reason (an SOP trigger)."""
        return bool(self.output and self.output.runbook_id is None and self.searched)


# ---- Policy and Router ------------------------------------------------------------------

Priority = Literal["P1", "P2", "P3", "P4"]
FinalRoute = Literal["handoff", "human", "redirect", "clarify", "resolver", "l1_pack"]


class PolicyResult(_Model):
    priority: Priority
    sla: SlaResult
    escalate_now: list[str]  # the model's escalate-now triggers in force
    never_escalate: list[str]  # verified never-escalate triggers
    handoff_reason: HandoffReason | None  # router line 1
    unknown_system: bool  # router line 2
    redirect_to: RedirectKey | None  # router line 3
    force_l1: bool  # a never-escalate trigger keeps an IT ticket at L1
    rules_fired: list[str]
    manager_in_note: bool


class RouteDecision(_Model):
    route: FinalRoute
    rule: int  # the router table line that matched (1-8)


MessageKind = Literal[
    "step", "framing_template", "redirect", "clarify", "status_template", "summary"
]
TicketStatus = Literal[
    "in_progress", "waiting_store", "waiting_approval", "waiting_l2", "escalated", "redirected",
    "with_l1", "resolved", "error",
]  # fmt: skip


class StoreDraft(_Model):
    """A store message before the contact is filled (D50: every message has a kind)."""

    kind: MessageKind
    text: str  # holds `{name}`, never the real name
    key: str | None = None  # the approved redirect or missing-fact key
    section_id: str | None = None


# ---- Resolver walk (S11) ----------------------------------------------------------------

StepKind = Literal["store", "action", "approval", "l2_task"]
StepOutcome = Literal[
    "sent", "replied", "fixed", "no_change", "failed", "done", "rejected", "void", "denied"
]  # fmt: skip
EventKind = Literal["start", "store_reply", "action", "l2_task", "approval_void"]
Waiting = Literal["store_reply", "approval", "l2_task"]


class WalkStep(_Model):
    """One dispatched step: what was done and what came back (masked)."""

    turn: int
    step_id: str  # the binding id
    proposal_id: str  # hash of (kb_rev, document, section, span)
    section_id: str
    kind: StepKind
    action_id: str | None = None
    outcome: StepOutcome = "sent"
    result: str | None = None  # the store's masked reply, the action result or the L2 note
    approval_id: str | None = None
    task_id: str | None = None


class TriedStep(_Model):
    """A step the ticket or history says was already done (D54: never sent, never done)."""

    step_id: str
    quote: str


class WalkState(_Model):
    runbook_id: str
    kb_rev: str
    turn: int = 0
    steps: list[WalkStep] = Field(default_factory=list)
    tried: list[TriedStep] = Field(default_factory=list)
    connection: Literal["usb", "network"] | None = None
    connection_quote: str | None = None
    version: Literal["covered", "not_covered", "unclear"] | None = None
    proposal: str | None = None  # the binding chosen this turn, waiting for dispatch
    waiting: Waiting | None = None
    last_event: EventKind = "start"
    last_text: str | None = None  # the latest masked reply or result
    last_outcome: str | None = None  # the latest action outcome
    approval_attempt: int = 0
    approval_expires_at: str | None = None  # ISO, wall clock (D48)
    # the action's autonomy when approval was asked: state, runs_in_a_row, runs_needed (S12a)
    approval_autonomy: dict[str, Any] | None = None
    end: Literal["fixed", "stuck"] | None = None
    end_reason: str | None = None

    @property
    def generic_only(self) -> bool:
        return self.version in ("not_covered", "unclear")

    @property
    def done_ids(self) -> set[str]:
        """Steps completed in this walk (a reported attempt is not one, D54)."""
        return {s.step_id for s in self.steps if s.outcome in ("replied", "fixed", "no_change",
                                                                "done")}  # fmt: skip

    @property
    def current(self) -> WalkStep | None:
        return self.steps[-1] if self.steps else None


class TicketState(_Model):
    ticket: MaskedTicket
    run_id: str = ""
    clock_offset_s: float = 0.0  # replay time minus wall time (D48)
    # From the API (S12): the requester's user id (P3) and, for an eval replay, the
    # dataset ticket it replays (D52). Ids only.
    submitted_by_user: str | None = None
    source_ticket_id: str | None = None
    facts: Facts | None = None
    triage: TriageResult | None = None
    policy: PolicyResult | None = None
    route: RouteDecision | None = None
    clarify_count: int = 0
    # Moderation (S4 labels, S10 build step 3).
    moderation_label: str = "ok"
    abuse_count: int = 0
    # Handoff (D57): the reason code and the node that failed, if any.
    handoff_reason: HandoffReason | None = None
    failed_node: str | None = None
    # Outputs after the gate.
    note_text: str | None = None
    note_source: Literal["llm", "fallback"] | None = None
    l1_pack_text: str | None = None
    drafts: list[StoreDraft] = Field(default_factory=list)
    sent: int = 0  # drafts already sent (by Communicate or the walk's dispatch)
    comm_pass: int = 0  # Communicate passes so far (idem keys per pass)
    walk: WalkState | None = None
    summary_text: str | None = None  # the code-built walk summary (S11)
    status: TicketStatus = "in_progress"
    # Pause (D53).
    pending_id: str | None = None
    pending_kind: str | None = None
    # Per-ticket caps and cost (review m1, K14).
    llm_calls: int = 0
    tokens: int = 0
    cost_usd: float = 0.0
    moderation_calls: int = 0
    audit_ids: list[int] = Field(default_factory=list)

    @property
    def kb_consulted(self) -> list[str]:
        return list(self.triage.documents_read) if self.triage else []
