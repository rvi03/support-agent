"""Typed responses of GET /tickets and GET /tickets/{id} (S12a; S13 typed client).

The route builders (`routes.list_item`, `routes.ticket_view`) still build plain
dicts; these models only describe them, so OpenAPI gives the UI real types. Field
names are the S12 ones and must not change (the S13 UI is built on them). A key
that only some callers get (IT-only lists, the outcome before the graph ran) is
optional and left out of the JSON when absent (`response_model_exclude_unset`).
`extra="forbid"` makes a builder key missing here fail the unit tests, not vanish.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class _View(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ApprovalCard(_View):
    approval_id: str | None = None
    action_id: str | None = None
    # S12a: warranty as of the ticket date, and the action's autonomy when asked
    warranty_expiry: str | None = None
    in_warranty: bool | None = None
    warranty_as_of: str | None = None
    autonomy_state: str | None = None
    runs_in_a_row: int | None = None
    runs_needed: int | None = None  # null for a destructive action (never promoted)
    action: str | None = None
    tier: str | None = None
    asset_id: str | None = None
    section_id: str | None = None
    step: str | None = None
    quote: str | None = None
    kb_rev: str | None = None
    expires_at: str | None = None
    approver_role: str | None = None


class Pending(_View):
    pending_id: str
    kind: str | None = None
    step_id: str | None = None
    since: str | None = None
    approver_role: str | None = None
    approval: ApprovalCard | None = None  # detail only, IT roles only


class TicketItem(_View):
    ticket_id: str
    store_id: str
    subject: str | None = None
    status: str
    api_status: str
    route: str | None = None
    priority: str | None = None
    category: str | None = None
    asset_id: str | None = None
    assignee_queue: str | None = None
    created_at: str | None = None
    escalate_by: str | None = None
    sla_minutes_left: float | None = None
    pending: Pending | None = None


class TicketList(_View):
    tickets: list[TicketItem]


class Message(_View):
    kind: str
    text: str
    section_id: str | None = None
    at: str | None = None  # null for callers who see the messages from state


class ActionRow(_View):
    action_id: str
    tier: str
    autonomy_state_at_run: str | None = None
    section_id: str | None = None
    outcome: str
    result: str | None = None
    approval_id: str | None = None
    eval_mode: bool | None = None
    created_at: str | None = None


class NoteRow(_View):
    id: str | int
    kind: str
    body: str
    created_at: str | None = None


class ApprovalRow(_View):
    id: str | int
    action_id: str | None = None
    section_id: str | None = None
    approver_role: str | None = None
    decision: str | None = None
    decided_by: str | None = None
    reason: str | None = None
    requested_at: str | None = None
    decided_at: str | None = None
    expires_at: str | None = None
    used_at: str | None = None


class L2TaskRow(_View):
    id: str | int
    section_id: str | None = None
    reason: str | None = None
    note: str | None = None
    result: str | None = None
    result_note: str | None = None
    done_by: str | None = None
    done_at: str | None = None
    created_at: str | None = None


class AuditRow(_View):
    id: str | int
    ts: str | None = None
    step: str | None = None
    actor: str | None = None
    action: str | None = None
    result: str | None = None
    reason: str | None = None


class Outcome(_View):
    route: str | None = None
    triage_route: str | None = None
    status: str | None = None
    handoff_reason: str | None = None
    priority: str | None = None
    llm_calls: int
    tokens: int
    cost_usd: float


class WalkStepView(_View):
    turn: int
    step_id: str
    kind: str
    action_id: str | None = None
    outcome: str | None = None
    result: str | None = None


class WalkView(_View):
    runbook_id: str
    kb_rev: str | None = None
    end: str | None = None
    end_reason: str | None = None
    steps: list[WalkStepView]
    tried: list[str]


class AuditSummary(_View):
    events: int
    by_step: dict[str, int]


class TicketView(TicketItem):
    run_id: str
    runbook_id: str | None = None
    error: str | None = None
    source_ticket_id: str | None = None
    messages: list[Message]
    actions: list[ActionRow]
    outcome: Outcome | None = None  # once the graph has state
    walk: WalkView | None = None
    audit_summary: AuditSummary
    # IT roles only
    notes: list[NoteRow] | None = None
    approvals: list[ApprovalRow] | None = None
    l2_tasks: list[L2TaskRow] | None = None
    audit: list[AuditRow] | None = None
