"""Graph state and node models (S8 build step 1; agent-architecture.md, Shared state).

Every node's input and output is a Pydantic model, so a malformed value fails
at the node that made it. `TicketState` is the per-ticket state the S10 graph
carries; S8 fills `facts`, `triage`, `policy` and `route`.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

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
    redirect_to: str | None  # router line 3
    force_l1: bool  # a never-escalate trigger keeps an IT ticket at L1
    rules_fired: list[str]
    manager_in_note: bool


class RouteDecision(_Model):
    route: FinalRoute
    rule: int  # the router table line that matched (1-8)


class TicketState(_Model):
    ticket: MaskedTicket
    facts: Facts | None = None
    triage: TriageResult | None = None
    policy: PolicyResult | None = None
    route: RouteDecision | None = None
    clarify_count: int = 0
