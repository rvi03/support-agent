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
StepId = Annotated[str, StringConstraints(min_length=1, max_length=80, pattern=r"^[a-z0-9._-]+$")]
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
    "sop_trigger", "conflict", "gate_block", "sla_breach", "moderation",
]  # fmt: skip
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
    step_id: StepId | None = None


class RowResult(_Out):
    status: Literal["written"]
    id: str


# ---- approvals and L2 tasks ---------------------------------------------------------


class CreateApprovalIn(_In):
    asset_id: Id
    step_id: StepId
    action_id: ActionId
    approver_role: ApproverRole
    requested_by: Short


class ApprovalResult(_Out):
    status: Literal["requested", "approved", "rejected"]
    approval_id: uuid.UUID
    expires_at: datetime
    autonomy_state: str | None = None


class DecideApprovalIn(_In):
    approval_id: uuid.UUID
    decision: Literal["approve", "reject"]
    decided_by: Short
    reason: Reason | None = None


class CreateL2TaskIn(_In):
    step_id: StepId
    reason: L2Reason
    note: Body


class L2TaskResult(_Out):
    status: Literal["created"]
    task_id: uuid.UUID


# ---- run_fix ------------------------------------------------------------------------


class RunFixIn(_In):
    asset_id: Id
    step_id: StepId
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
