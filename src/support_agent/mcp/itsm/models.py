"""Pydantic input and result models of the itsm-actions tools (S7 build step 3).

The run, ticket and store of every call come from the request `_meta` (the bound
call context), never from these models, so a tool can only write to the ticket
the call is bound to. Every input carries `idem_key` =
`<run_id>:<ticket_id>:<node>:<step>`; the server checks its prefix.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints

IdemKey = Annotated[str, StringConstraints(min_length=40, max_length=200, pattern=r"^\S+$")]
Id = Annotated[str, StringConstraints(min_length=1, max_length=64, pattern=r"^\S+$")]
# A KB section of the ticket's runbook, and the exact runbook words the agent acts
# on; the server checks the quote is in that section (S8a: no parsed steps).
SectionId = Annotated[
    str, StringConstraints(max_length=200, pattern=r"^runbooks/[a-z0-9][a-z0-9-]*\.md#[a-z0-9-]+$")
]
Quote = Annotated[str, StringConstraints(min_length=20, max_length=2_000)]
ActionId = Annotated[str, StringConstraints(min_length=1, max_length=64, pattern=r"^[a-z0-9_]+$")]
Short = Annotated[str, StringConstraints(min_length=1, max_length=120, strip_whitespace=True)]
Body = Annotated[str, StringConstraints(min_length=1, max_length=20_000)]
Reason = Annotated[str, StringConstraints(min_length=1, max_length=1_000, strip_whitespace=True)]
DocId = Annotated[str, StringConstraints(pattern=r"^runbooks/[a-z0-9][a-z0-9-]*\.md$")]

Priority = Literal["P1", "P2", "P3", "P4"]
Route = Literal["resolver", "l1_pack", "handoff", "redirect", "clarify"]
Status = Literal[
    "new", "in_progress", "waiting_store", "waiting_approval", "waiting_l2", "resolved",
    "escalated", "redirected", "closed",
]  # fmt: skip
Queue = Literal["agent", "store", "l1", "l2", "vendor"]
CommentKind = Literal["note", "l1_pack", "l2_note", "system"]
MessageKind = Literal[
    "step", "framing_template", "redirect", "clarify", "status_template", "summary"
]
L2Reason = Literal["l2_only", "secret", "destructive_store_step", "unmapped", "guard"]
HandoffReason = Literal[
    "no_kb_match", "tool_error", "budget_exceeded", "invalid_output", "llm_unavailable",
    "sop_trigger", "conflict", "gate_block", "sla_breach", "moderation", "low_confidence",
    "device_not_found", "unknown_system", "l2_needed", "still_vague", "steps_exhausted",
    "approval_rejected", "version_not_covered", "kb_rev_changed", "no_approved_steps",
]  # fmt: skip
PendingKind = Literal["answer", "store_reply", "approval", "l2_task"]
ApproverRole = Literal["l2_engineer", "vendor_approver"]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    idem_key: IdemKey


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# ---- tickets ------------------------------------------------------------------------


class CreateTicketIn(_In):
    date_opened: AwareDatetime
    asset_id: Id | None = None
    priority: Priority | None = None
    category: Short | None = None
    submitted_by_user: Short | None = None
    # Eval replay only (D52): the dataset ticket this run replays, for scoring.
    source_ticket_id: Id | None = None
    clock_offset_s: float = Field(default=0.0, description="Replay time minus wall time (D48).")


class Ticket(_Out):
    ticket_id: str
    store_id: str
    asset_id: str | None
    date_opened: datetime
    status: str
    route: str | None
    category: str | None
    real_category: str | None
    priority: str | None
    assignee_queue: str | None
    runbook_id: str | None
    kb_rev: str | None


class TicketResult(_Out):
    status: Literal["created", "updated", "escalated"]
    ticket: Ticket


class UpdateTicketIn(_In):
    route: Route | None = None
    category: Short | None = None
    real_category: Short | None = None
    priority: Priority | None = None
    status: Status | None = None
    assignee_queue: Queue | None = None
    runbook_id: DocId | None = None
    kb_rev: Id | None = None
    first_response_by: AwareDatetime | None = None
    escalate_by: AwareDatetime | None = None
    resolve_by: AwareDatetime | None = None
    # Replay clock (D48, S11): the ticket's new offset after a simulated store-reply delay.
    clock_offset_s: float | None = None


class EscalateIn(_In):
    queue: Literal["l2", "vendor"] = "l2"
    reason_code: HandoffReason
    note: Body


# ---- comments and messages ----------------------------------------------------------


class AddCommentIn(_In):
    kind: CommentKind
    body: Body


class MessageStoreIn(_In):
    kind: MessageKind
    body: Body
    section_id: SectionId | None = None


class RowResult(_Out):
    status: Literal["written"]
    id: str


# ---- approvals and L2 tasks ---------------------------------------------------------


class CreateApprovalIn(_In):
    asset_id: Id
    section_id: SectionId
    quote: Quote
    action_id: ActionId
    approver_role: ApproverRole
    requested_by: Short


class ApprovalResult(_Out):
    status: Literal["requested", "approved", "rejected"]
    approval_id: uuid.UUID
    expires_at: datetime
    autonomy_state: str | None = None
    # create_approval only: the action's autonomy for this device model when asked
    # (S12a, the approval card's "supervised, 0 of 1")
    runs_in_a_row: int | None = None
    runs_needed: int | None = None


class DecideApprovalIn(_In):
    approval_id: uuid.UUID
    decision: Literal["approve", "reject"]
    decided_by: Short
    reason: Reason | None = None


class CreateL2TaskIn(_In):
    section_id: SectionId | None = None
    reason: L2Reason
    note: Body


class L2TaskResult(_Out):
    status: Literal["created", "done", "failed"]
    task_id: uuid.UUID


class CompleteL2TaskIn(_In):
    """The L2 engineer's result for one task (S11; the API checked the role first)."""

    task_id: uuid.UUID
    result: Literal["done", "failed"]
    result_note: Reason
    done_by: Short


# ---- run_fix ------------------------------------------------------------------------


class RunFixIn(_In):
    asset_id: Id
    section_id: SectionId
    quote: Quote
    action_id: ActionId
    approval_id: uuid.UUID | None = None


class RunFixResult(_Out):
    status: Literal["ran"]
    action_row_id: str
    outcome: Literal["fixed", "no_change", "failed"]
    result: str
    tier: str
    autonomy_state_at_run: str
    autonomy_state_after: str
    approval_id: uuid.UUID | None


# ---- pending items (S10, D53) -------------------------------------------------------


class CreatePendingIn(_In):
    kind: PendingKind
    step_id: Annotated[str, StringConstraints(max_length=200)] | None = None
    approval_id: uuid.UUID | None = None


class PendingResult(_Out):
    status: Literal["pending", "cleared"]
    pending_id: uuid.UUID
    kind: str


class ClearPendingIn(_In):
    pending_id: uuid.UUID
    # The kind the resume brings; "timeout" (SLA timer, S11) clears any kind.
    kind: Literal["answer", "store_reply", "approval", "l2_task", "timeout"]
