"""The 6 endpoints (S12 build step 3; design.md, API; D30).

Every request passes the same fixed order:

    JWT verify ─► size/schema limits ─► rate limit ─► OPA (P1-P6, P10) ─► handler ─► audit

Errors: 401 no or bad token, 403 OPA deny, 404 unknown ticket or one the caller may
not see (so its existence isn't revealed), 409 wrong state, 413 body too large,
422 schema, 429 rate limit. Every denial writes an audit event; so does every
accepted write. Polled reads are not audited unless denied.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal, Protocol

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from support_agent.agent.messages import fill
from support_agent.api.auth import ApiVerifier, AuthError, Subject
from support_agent.api.limits import Kind, RateLimits
from support_agent.api.service import ApiError, TicketService
from support_agent.api.store import ApiStore, DuplicateReplay, Row
from support_agent.common.audit import AuditEvent
from support_agent.intake.schema import (
    DESCRIPTION_MAX,
    HISTORY_MAX,
    LIST_MAX,
    SHORT_MAX,
    SUBJECT_MAX,
    HistoryEntry,
)
from support_agent.mcp.base.opa import Decision

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Short = Annotated[str, StringConstraints(strip_whitespace=True, max_length=SHORT_MAX)]

IT_ROLES = ("l1_agent", "l2_engineer", "vendor_approver", "admin")
REPLAY_ONLY = (
    "source_ticket_id", "run_id", "ticket_history", "related_tickets", "escalation_flag",
    "store_name",
)  # fmt: skip


# ---- bodies ----------------------------------------------------------------------------


class _Body(BaseModel):
    # Unknown fields are a 422: ticket_id, date_opened, store_id, submitted_by,
    # contact_phone, status and resolution_notes are never accepted from a caller.
    model_config = ConfigDict(extra="forbid", frozen=True)


class NewTicket(_Body):
    """The intake schema minus store, contact, ticket id and date (the API sets them)."""

    subject: Annotated[Text, StringConstraints(max_length=SUBJECT_MAX)]
    description: Annotated[Text, StringConstraints(max_length=DESCRIPTION_MAX)]
    asset_id: Short | None = None
    system_version: Short | None = None
    category: Short | None = None
    subcategory: Short | None = None
    priority: Short | None = None
    tags: list[Short] = Field(default_factory=list, max_length=LIST_MAX)
    # Replay of a dataset ticket only (eval-runner, D52); anyone else gets 422.
    source_ticket_id: Short | None = None
    run_id: uuid.UUID | None = None
    store_name: Short | None = None
    escalation_flag: bool | None = None
    related_tickets: list[Short] = Field(default_factory=list, max_length=LIST_MAX)
    ticket_history: list[HistoryEntry] = Field(default_factory=list, max_length=HISTORY_MAX)


class Reply(_Body):
    pending_id: uuid.UUID
    text: Annotated[Text, StringConstraints(max_length=DESCRIPTION_MAX)]


class Approve(_Body):
    pending_id: uuid.UUID
    decision: Literal["approve", "reject", "done", "failed"]
    reason: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] | None = None
    result: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] | None = None


# ---- dependencies ----------------------------------------------------------------------


class Policy(Protocol):
    async def allow(self, policy_input: dict[str, Any]) -> Decision: ...


class AuditFn(Protocol):
    async def __call__(self, event: AuditEvent) -> int: ...


@dataclass
class ApiDeps:
    verifier: ApiVerifier
    policy: Policy
    limits: RateLimits
    store: ApiStore
    service: TicketService
    audit: AuditFn
    wall: Any = None

    def now(self) -> datetime:
        return self.wall() if self.wall else datetime.now(UTC)

    async def audit_refusal(self, status: int, reason: str, path: str) -> None:
        """A refusal before the token is read (the body size cap)."""
        await self.audit(
            AuditEvent(step="api", actor="anonymous", action=f"api.{path}", result="denied",
                       reason=reason, source="api", payload={"status": status})
        )  # fmt: skip


def deps(request: Request) -> ApiDeps:
    d: ApiDeps = request.app.state.deps
    return d


async def deny(
    d: ApiDeps,
    status: int,
    reason: str,
    *,
    action: str,
    subject: Subject | None = None,
    resource: Row | None = None,
    rule: str | None = None,
    extra: dict[str, Any] | None = None,
) -> JSONResponse:
    """Audit a denial, then answer it (D9: the audit write comes first)."""
    await d.audit(
        AuditEvent(
            step="api",
            actor=subject.client_id if subject else "anonymous",
            action=action,
            result="denied",
            reason=reason[:300],
            source="api",
            run_id=resource.get("run_id") if resource else None,
            ticket_id=resource.get("ticket_id") if resource else None,
            payload={"status": status, "rule": rule, **(extra or {})},
        )
    )
    return JSONResponse({"error": reason, "status": status}, status_code=status)


async def authenticate(request: Request, d: Annotated[ApiDeps, Depends(deps)]) -> Subject:
    try:
        subject = await d.verifier.verify(request.headers.get("authorization"))
    except AuthError as exc:
        raise ApiError(401, exc.reason) from None
    request.state.subject = subject
    return subject


Auth = Annotated[Subject, Depends(authenticate)]
Deps = Annotated[ApiDeps, Depends(deps)]


def _limit(d: ApiDeps, subject: Subject, kind: Kind) -> None:
    broken = d.limits.hit(subject, kind)
    if broken:
        raise ApiError(429, "rate_limited", rule=broken)


def policy_resource(resource: Row, *, now: datetime, kb_rev_current: str | None = None) -> Row:
    """The facts OPA decides on: ids, states and the open pause, no text."""
    pending = None
    if resource.get("pending_id"):
        pending = {
            "kind": resource.get("pending_kind"),
            "approver_role": resource.get("approver_role"),
            "kb_rev": resource.get("approval_kb_rev"),
            # A guarded IT step is an L2 task, never an approval card (D51).
            "guarded": False,
        }
    return {
        "ticket_id": resource["ticket_id"],
        "run_id": str(resource["run_id"]),
        "store_id": resource["store_id"],
        "submitted_by_user": resource["submitted_by_user"],
        "assignee_queue": resource.get("assignee_queue"),
        "status": resource.get("status") or "new",
        "replay": resource.get("source_ticket_id") is not None,
        "pending": pending,
        "kb_rev_current": kb_rev_current,
        "sla_passed": sla_passed(resource, now),
    }


def ticket_now(resource: Row, now: datetime) -> datetime:
    """The ticket's own time (D48): wall clock plus its replay offset."""
    return now + timedelta(seconds=float(resource.get("clock_offset_s") or 0.0))


def sla_passed(resource: Row, now: datetime) -> bool:
    escalate_by = resource.get("escalate_by")
    return bool(escalate_by and ticket_now(resource, now) > escalate_by)


def minutes_left(resource: Row, now: datetime) -> float | None:
    escalate_by = resource.get("escalate_by")
    if not escalate_by:
        return None
    left: timedelta = escalate_by - ticket_now(resource, now)
    return round(left.total_seconds() / 60, 1)


async def authorize(
    d: ApiDeps, subject: Subject, action: str, resource: Row | None, *, status: int = 403
) -> None:
    decision = await d.policy.allow(
        {"action": action, "subject": subject.policy(), "resource": resource or {}}
    )
    if not decision.allowed:
        reason = "not_found" if status == 404 else "forbidden"
        raise ApiError(status, reason, rule=decision.reason)


async def visible(d: ApiDeps, subject: Subject, ticket_id: str) -> Row:
    """The ticket if the caller may see it; 404 otherwise, whatever the reason."""
    resource = await d.store.resource(ticket_id)
    if resource is None:
        raise ApiError(404, "not_found", rule="unknown_ticket")
    facts = policy_resource(resource, now=d.now())
    try:
        await authorize(d, subject, "api.get_ticket", facts, status=404)
    except ApiError as exc:
        exc.resource = resource
        raise
    return resource


async def accepted(d: ApiDeps, subject: Subject, action: str, resource: Row | None,
                   ticket_id: str, run_id: Any, **payload: Any) -> None:  # fmt: skip
    await d.audit(
        AuditEvent(
            step="api", actor=subject.client_id, action=action, result="accepted",
            source="api", run_id=run_id, ticket_id=ticket_id,
            payload={"user": subject.user, **payload},
        )
    )  # fmt: skip
    del resource


# ---- routes ----------------------------------------------------------------------------

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/tickets", status_code=202)
async def create_ticket(body: NewTicket, subject: Auth, d: Deps) -> dict[str, str]:
    given = body.model_dump(exclude_unset=True)
    replay_fields = sorted(f for f in REPLAY_ONLY if given.get(f) not in (None, [], ""))
    if replay_fields and not subject.is_replayer:
        raise ApiError(422, "fields_not_allowed", rule=",".join(replay_fields))
    _limit(d, subject, "write")
    source = None
    if subject.is_replayer:
        if not body.source_ticket_id or not body.run_id:
            raise ApiError(422, "replay_needs_source_ticket_id_and_run_id")
        source = await d.store.source(body.source_ticket_id)
        if source is None:
            raise ApiError(422, "unknown_source_ticket")
    store_id = source.store_id if source else subject.store_id
    await authorize(
        d, subject, "api.create_ticket",
        {"store_id": store_id, "replay": source is not None,
         "source_ticket_id": body.source_ticket_id},
    )  # fmt: skip
    if store_id is None:  # P1 refuses this already; kept for the type checker
        raise ApiError(403, "forbidden", rule="no_store")
    run_id = body.run_id if source and body.run_id else uuid.uuid4()
    fields = body.model_dump(exclude={"source_ticket_id", "run_id"}, exclude_unset=True,
                             exclude_none=True)  # fmt: skip
    try:
        ticket_id = await d.service.create(
            subject, fields, store_id=store_id,
            date_opened=source.date_opened if source else d.now(),
            source_ticket_id=source.ticket_id if source else None, run_id=run_id,
        )  # fmt: skip
    except DuplicateReplay:
        raise ApiError(409, "source_ticket_already_in_run", rule="D45") from None
    await accepted(d, subject, "api.create_ticket", None, ticket_id, run_id,
                   replay=source is not None)  # fmt: skip
    return {"ticket_id": ticket_id, "run_id": str(run_id)}


@router.get("/tickets")
async def list_tickets(subject: Auth, d: Deps) -> dict[str, Any]:
    _limit(d, subject, "read")
    await authorize(d, subject, "api.list_tickets", {})
    rows = await d.store.list_for(
        store_id=subject.store_id if subject.has("store_user") else None,
        submitted_by=subject.user if subject.is_replayer else None,
        queues={
            q for q, role in (("l1", "l1_agent"), ("l2", "l2_engineer")) if subject.has(role)
        },  # fmt: skip
        approver_roles={r for r in ("l2_engineer", "vendor_approver") if subject.has(r)},
        l2_tasks=subject.has("l2_engineer"),
        everything=subject.has("admin"),
    )
    now = d.now()
    return {"tickets": [list_item(r, now) for r in rows]}


@router.get("/tickets/{ticket_id}")
async def get_ticket(ticket_id: str, subject: Auth, d: Deps) -> dict[str, Any]:
    _limit(d, subject, "read")
    resource = await visible(d, subject, ticket_id)
    return await ticket_view(d, subject, resource)


@router.post("/tickets/{ticket_id}/reply", status_code=202)
async def reply(ticket_id: str, body: Reply, subject: Auth, d: Deps) -> dict[str, str]:
    _limit(d, subject, "write")
    resource = await visible(d, subject, ticket_id)
    await _authorize_on(d, subject, "api.reply", resource)
    await _act(d.service.reply(resource, str(body.pending_id), body.text), resource)
    await accepted(d, subject, "api.reply", resource, ticket_id, resource["run_id"],
                   pending_id=str(body.pending_id))  # fmt: skip
    return {"ticket_id": ticket_id}


@router.post("/tickets/{ticket_id}/approve", status_code=202)
async def approve(ticket_id: str, body: Approve, subject: Auth, d: Deps) -> dict[str, str]:
    _limit(d, subject, "write")
    resource = await visible(d, subject, ticket_id)
    kb_rev = await d.store.current_kb_rev()
    await _authorize_on(d, subject, "api.approve", resource, kb_rev_current=kb_rev)
    await _act(
        d.service.approve(subject, resource, str(body.pending_id), body.decision, body.reason,
                          body.result),
        resource,
    )  # fmt: skip
    await accepted(d, subject, "api.approve", resource, ticket_id, resource["run_id"],
                   pending_id=str(body.pending_id), decision=body.decision)  # fmt: skip
    return {"ticket_id": ticket_id}


async def _authorize_on(d: ApiDeps, subject: Subject, action: str, resource: Row,
                        **facts: Any) -> None:  # fmt: skip
    try:
        await authorize(d, subject, action, policy_resource(resource, now=d.now(), **facts))
    except ApiError as exc:
        exc.resource = resource
        raise


async def _act(work: Any, resource: Row) -> None:
    try:
        await work
    except ApiError as exc:
        exc.resource = resource
        raise


# ---- views -----------------------------------------------------------------------------


def _iso(value: Any) -> Any:
    return value.isoformat() if isinstance(value, datetime) else value


def _pending(r: Row) -> dict[str, Any] | None:
    if not r.get("pending_id"):
        return None
    return {
        "pending_id": str(r["pending_id"]),
        "kind": r.get("pending_kind"),
        "step_id": r.get("pending_step_id"),
        "since": _iso(r.get("pending_since")),
        "approver_role": r.get("approver_role"),
    }


def list_item(r: Row, now: datetime) -> dict[str, Any]:
    return {
        "ticket_id": r["ticket_id"],
        "store_id": r["store_id"],
        "subject": r.get("subject"),
        "status": r.get("status") or "new",
        "api_status": r["api_status"],
        "route": r.get("route"),
        "priority": r.get("priority"),
        "category": r.get("real_category") or r.get("category"),
        "asset_id": r.get("asset_id"),
        "assignee_queue": r.get("assignee_queue"),
        "created_at": _iso(r.get("created_at")),
        "escalate_by": _iso(r.get("escalate_by")),
        "sla_minutes_left": minutes_left(r, now),
        "pending": _pending(r),
    }


def _rows(rows: list[Row]) -> list[Row]:
    return [{k: (str(v) if isinstance(v, uuid.UUID) else _iso(v)) for k, v in r.items()}
            for r in rows]  # fmt: skip


async def ticket_view(d: ApiDeps, subject: Subject, r: Row) -> dict[str, Any]:
    now = d.now()
    view = list_item(r, now) | {
        "run_id": str(r["run_id"]),
        "runbook_id": r.get("runbook_id"),
        "error": r.get("error"),
        "source_ticket_id": r.get("source_ticket_id"),
    }
    state, interrupt = await d.service.state(r)
    details = await d.store.details(r["run_id"], r["ticket_id"])
    owner = subject.has("store_user") and subject.store_id == r["store_id"]
    it = any(subject.has(role) for role in IT_ROLES)
    if owner:  # the store's own user: the messages as sent, with the real first name
        messages = [{"kind": m["kind"], "text": m["body"], "section_id": m["section_id"],
                     "at": _iso(m["created_at"])} for m in details["messages"]]  # fmt: skip
    else:  # anyone else: the same messages from state, the name left out (P9)
        drafts = state.drafts[: state.sent] if state else []
        messages = [{"kind": m.kind, "text": fill(m.text, None), "section_id": m.section_id,
                     "at": None} for m in drafts]  # fmt: skip
    view["messages"] = messages
    view["actions"] = _rows(details["actions"])
    pending = _pending(r)
    if pending and interrupt and str(interrupt.get("pending_id")) == pending["pending_id"]:
        pending["approval"] = interrupt.get("approval") if it else None
    view["pending"] = pending
    if state:
        walk = state.walk
        view["outcome"] = {
            "route": state.route.route if state.route else None,
            "triage_route": state.triage.output.route
            if state.triage and state.triage.output else None,
            "status": state.status,
            "handoff_reason": state.handoff_reason,
            "priority": state.policy.priority if state.policy else None,
            "llm_calls": state.llm_calls,
            "tokens": state.tokens,
            "cost_usd": round(state.cost_usd, 6),
        }  # fmt: skip
        view["walk"] = (
            {
                "runbook_id": walk.runbook_id,
                "kb_rev": walk.kb_rev,
                "end": walk.end,
                "end_reason": walk.end_reason,
                "steps": [
                    {
                        "turn": s.turn,
                        "step_id": s.step_id,
                        "kind": s.kind,
                        "action_id": s.action_id,
                        "outcome": s.outcome,
                        "result": s.result,
                    }
                    for s in walk.steps
                ],  # fmt: skip
                "tried": [t.step_id for t in walk.tried],
            }
            if walk
            else None
        )
    audit = details["audit"]
    summary: dict[str, int] = {}
    for e in audit:
        key = f"{e['step']}:{e['action']}:{e['result']}"
        summary[key] = summary.get(key, 0) + 1
    view["audit_summary"] = {"events": len(audit), "by_step": summary}
    if it:
        view["notes"] = _rows(details["comments"])
        view["approvals"] = _rows(details["approvals"])
        view["l2_tasks"] = _rows(details["l2_tasks"])
        view["audit"] = _rows(audit)
    return view
