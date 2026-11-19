"""itsm-actions MCP server: the local ITSM writes (S7; design.md, ITSM actions).

Run: `python -m support_agent.mcp.itsm` (container `itsm-actions`, port 8103, role
`itsm_rw`). Every tool is called by `agent-actor` (P7) and never trusts the caller:

- The run, ticket and store come from the request `_meta` (`current_call()`); a
  call without all three is refused. Every write after `create_ticket` targets the
  bound ticket, whose stored store must equal the bound store (own store).
- Every write takes `idem_key` = `<run_id>:<ticket_id>:<node>:<step>`. The first
  reply per key is kept in `itsm.idempotency`; a repeated key returns it and writes
  nothing, the same key with other arguments is refused with `conflict`.
- Each write and its domain audit event (step `itsm`) commit in one transaction.
- `run_fix` gathers its facts under row locks and asks OPA P8; a refusal writes a
  `denied` event with the reasons. It records its own outcome and autonomy
  (`autonomy.record_result`), and consumes the approval in the same transaction.
- `message_store` asks OPA P9; `decide_approval` demotes on a reject (P5).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from psycopg import AsyncConnection, sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel

from support_agent.common.audit import AuditEvent, awrite_event
from support_agent.common.config import ItsmSettings
from support_agent.common.db import dsn
from support_agent.common.text import quote_in
from support_agent.mcp.base.auth import JwtVerifier
from support_agent.mcp.base.errors import ErrorCode, ToolFailure
from support_agent.mcp.base.opa import OpaClient
from support_agent.mcp.base.server import CallContext, McpService, Policy, args_hash, current_call
from support_agent.mcp.itsm import autonomy
from support_agent.mcp.itsm.autonomy import Decider
from support_agent.mcp.itsm.models import (
    AddCommentIn,
    ApprovalResult,
    CreateApprovalIn,
    CreateL2TaskIn,
    CreateTicketIn,
    DecideApprovalIn,
    EscalateIn,
    L2TaskResult,
    MessageStoreIn,
    RowResult,
    RunFixIn,
    RunFixResult,
    Ticket,
    TicketResult,
    UpdateTicketIn,
)
from support_agent.mcp.itsm.outcome import OutcomeProvider, provider_for
from support_agent.mcp.itsm.registry import Registry, default_registry, family_of

NAME = "itsm-actions"
POLICY_PREFIX = "itsm"
SCOPE_WRITE = "itsm:write"
SCOPE_FIX = "itsm:run_fix"
P8 = "servewell/p8_run_fix"
P9 = "servewell/p9_pii"

Conn = AsyncConnection[Any]

_TICKET_COLS = (
    "ticket_id, store_id, asset_id, date_opened, status, route, category, real_category, "
    "priority, assignee_queue, runbook_id, kb_rev"
)


class Denied(Exception):  # noqa: N818 - a reply kind
    """A refusal found inside the write transaction; audited after the rollback."""

    def __init__(self, reasons: list[str], cols: dict[str, Any] | None = None) -> None:
        super().__init__(",".join(reasons))
        self.reasons, self.cols = reasons, cols or {}


@dataclass
class Itsm:
    registry: Registry
    policy: Decider
    outcome: OutcomeProvider
    threshold: int
    ttl_min: int
    eval_mode: bool
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))  # wall clock


# ---- helpers -------------------------------------------------------------------------


def bound() -> CallContext:
    ctx = current_call()
    if ctx.run_id is None or not ctx.ticket_id or not ctx.store_id:
        raise ToolFailure(ErrorCode.DENIED, "unbound_call")
    return ctx


def _must[T](value: T | None) -> T:
    if value is None:
        raise ToolFailure(ErrorCode.ERROR, "row_missing")
    return value


def _check_key(ctx: CallContext, key: str) -> None:
    if not key.startswith(f"{ctx.run_id}:{ctx.ticket_id}:"):
        raise ToolFailure(ErrorCode.INVALID, "idem_key_not_bound_to_run_and_ticket")


async def _one(conn: Conn, query: Any, params: tuple[Any, ...]) -> dict[str, Any] | None:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(query, params)
        return await cur.fetchone()


async def _event(conn: Conn, ctx: CallContext, action: str, result: str, **cols: Any) -> None:
    payload = cols.pop("payload", {})
    await awrite_event(
        conn,
        AuditEvent(
            step="itsm", actor=ctx.client_id, action=action, result=result, source=NAME,
            run_id=ctx.run_id, ticket_id=ctx.ticket_id, payload=payload, **cols,
        ),
    )  # fmt: skip


async def _ticket(conn: Conn, ctx: CallContext, *, lock: bool = False) -> dict[str, Any]:
    """The bound ticket, which must belong to the bound store (own-store check)."""
    row = await _one(
        conn,
        f"SELECT {_TICKET_COLS} FROM itsm.tickets WHERE run_id = %s AND ticket_id = %s"  # noqa: S608
        + (" FOR UPDATE" if lock else ""),
        (ctx.run_id, ctx.ticket_id),
    )
    if row is None:
        raise ToolFailure(ErrorCode.DENIED, "ticket_not_created")
    if row["store_id"] != ctx.store_id:
        raise ToolFailure(ErrorCode.DENIED, "other_store")
    return row


async def _section(
    conn: Conn, ticket: dict[str, Any], section_id: str, quote: str
) -> dict[str, Any] | None:
    """The cited section of the ticket's runbook in the ticket's kb_rev, and whether
    the quoted runbook words are really in it (S8a: binding by quote, not by a
    parsed step). None when the ticket has no runbook or the section is not in it."""
    if not ticket.get("kb_rev") or not ticket.get("runbook_id"):
        return None
    row = await _one(
        conn,
        "SELECT doc_id, kb_rev, section_id, masked_text FROM kb.sections "
        "WHERE kb_rev = %s AND doc_id = %s AND section_id = %s",
        (ticket["kb_rev"], ticket["runbook_id"], section_id),
    )
    if row is None:
        return None
    return {
        "doc_id": row["doc_id"],
        "kb_rev": row["kb_rev"],
        "quote_ok": quote_in(quote, row["masked_text"]),
    }


async def idempotent(
    conn: Conn,
    ctx: CallContext,
    tool: str,
    args: BaseModel,
    work: Callable[[], Awaitable[BaseModel]],
) -> dict[str, Any]:
    """Run `work` once per idem_key, in one transaction with its ledger row."""
    key = str(getattr(args, "idem_key"))  # noqa: B009
    _check_key(ctx, key)
    digest = args_hash(args.model_dump(mode="json"))
    async with conn.transaction():
        cur = await conn.execute(
            "INSERT INTO itsm.idempotency (idem_key, run_id, ticket_id, tool, args_sha256) "
            "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (idem_key) DO NOTHING RETURNING idem_key",
            (key, ctx.run_id, ctx.ticket_id, tool, digest),
        )
        if await cur.fetchone() is None:
            seen = await _one(
                conn,
                "SELECT run_id, ticket_id, tool, args_sha256, response FROM itsm.idempotency "
                "WHERE idem_key = %s",
                (key,),
            )
            seen = _must(seen)
            same = (seen["run_id"], seen["ticket_id"], seen["tool"], seen["args_sha256"]) == (
                ctx.run_id, ctx.ticket_id, tool, digest,
            )  # fmt: skip
            if not same or seen["response"] is None:
                raise ToolFailure(ErrorCode.CONFLICT, "idem_key_reused_with_other_arguments")
            return dict(seen["response"])
        response = (await work()).model_dump(mode="json")
        await conn.execute(
            "UPDATE itsm.idempotency SET response = %s WHERE idem_key = %s",
            (Jsonb(response), key),
        )
        return response


# ---- tools ---------------------------------------------------------------------------


def register(service: McpService, it: Itsm) -> None:  # noqa: C901 - one closure per tool
    @service.tool(scope=SCOPE_WRITE)
    async def create_ticket(args: CreateTicketIn, conn: Conn) -> TicketResult:
        """Write the ticket row right after intake. The store is the bound store, never
        the body. Idempotent on (run_id, ticket_id): a different payload is `conflict`."""
        ctx = bound()

        async def work() -> TicketResult:
            body = args.model_dump(mode="json", exclude={"idem_key"})
            digest = args_hash({**body, "store_id": ctx.store_id})
            cur = await conn.execute(
                "INSERT INTO itsm.tickets (run_id, ticket_id, store_id, asset_id, "
                "submitted_by_user, date_opened, clock_offset, priority, category, "
                "create_sha256, idem_key) VALUES (%s, %s, %s, %s, %s, %s, "
                "make_interval(secs => %s), %s, %s, %s, %s) "
                "ON CONFLICT (run_id, ticket_id) DO NOTHING RETURNING ticket_id",
                (
                    ctx.run_id, ctx.ticket_id, ctx.store_id, args.asset_id,
                    args.submitted_by_user, args.date_opened, args.clock_offset_s,
                    args.priority, args.category, digest, args.idem_key,
                ),
            )  # fmt: skip
            created = await cur.fetchone() is not None
            row = await _one(
                conn,
                f"SELECT {_TICKET_COLS}, create_sha256 FROM itsm.tickets "  # noqa: S608
                "WHERE run_id = %s AND ticket_id = %s",
                (ctx.run_id, ctx.ticket_id),
            )
            row = _must(row)
            if not created:
                if row["store_id"] != ctx.store_id:
                    raise ToolFailure(ErrorCode.DENIED, "other_store")
                if row["create_sha256"] != digest:
                    raise ToolFailure(ErrorCode.CONFLICT, "ticket_exists_with_other_payload")
            else:
                await _event(
                    conn,
                    ctx,
                    "create_ticket",
                    "created",
                    payload={"idem_key": args.idem_key, "store_id": ctx.store_id},
                )
            row.pop("create_sha256")
            return TicketResult(status="created", ticket=Ticket(**row))

        return TicketResult.model_validate(await idempotent(conn, ctx, "create_ticket", args, work))

    @service.tool(scope=SCOPE_WRITE)
    async def update_ticket(args: UpdateTicketIn, conn: Conn) -> TicketResult:
        """Set route, category, priority, status, queue, SLA deadlines, and at Triage the
        runbook_id and kb_rev (set once; a change is `conflict`)."""
        ctx = bound()
        fields = args.model_dump(exclude={"idem_key"}, exclude_none=True)
        if not fields:
            raise ToolFailure(ErrorCode.INVALID, "nothing_to_update")

        async def work() -> TicketResult:
            row = await _ticket(conn, ctx, lock=True)
            for once in ("runbook_id", "kb_rev"):
                if once in fields and row[once] not in (None, fields[once]):
                    raise ToolFailure(ErrorCode.CONFLICT, f"{once}_already_set")
            sets = sql.SQL(", ").join(sql.SQL("{} = %s").format(sql.Identifier(k)) for k in fields)
            await conn.execute(
                sql.SQL(
                    "UPDATE itsm.tickets SET {}, updated_at = now() "
                    "WHERE run_id = %s AND ticket_id = %s"
                ).format(sets),
                (*fields.values(), ctx.run_id, ctx.ticket_id),
            )
            await _event(
                conn,
                ctx,
                "update_ticket",
                "updated",
                kb_rev=fields.get("kb_rev") or row["kb_rev"],
                payload={"idem_key": args.idem_key, "fields": sorted(fields)},
            )
            new = await _ticket(conn, ctx)
            return TicketResult(status="updated", ticket=Ticket(**new))

        return TicketResult.model_validate(await idempotent(conn, ctx, "update_ticket", args, work))

    @service.tool(scope=SCOPE_WRITE)
    async def add_comment(args: AddCommentIn, conn: Conn) -> RowResult:
        """Internal comment on the ticket (note, L1 pack, L2 note, system)."""
        ctx = bound()

        async def work() -> RowResult:
            await _ticket(conn, ctx)
            row = await _one(
                conn,
                "INSERT INTO itsm.ticket_comments (run_id, ticket_id, kind, body, idem_key) "
                "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                (ctx.run_id, ctx.ticket_id, args.kind, args.body, args.idem_key),
            )
            row = _must(row)
            await _event(
                conn,
                ctx,
                "add_comment",
                "written",
                payload={"idem_key": args.idem_key, "kind": args.kind, "id": row["id"]},
            )
            return RowResult(status="written", id=str(row["id"]))

        return RowResult.model_validate(await idempotent(conn, ctx, "add_comment", args, work))

    @service.tool(scope=SCOPE_WRITE)
    async def message_store(args: MessageStoreIn, conn: Conn) -> RowResult:
        """A message to the store, with its kind (D50). The only table that may hold the
        real contact (the reply sender fills it), so OPA P9 is asked first."""
        ctx = bound()
        decision = await it.policy.decide(
            P9,
            {
                "subject": {"client_id": ctx.client_id},
                "context": {"ticket_id": ctx.ticket_id},
                "resource": {"ticket_id": ctx.ticket_id},
            },
        )
        if decision is None or decision.get("allow") is not True:
            raise ToolFailure(ErrorCode.DENIED, "p9_pii")

        async def work() -> RowResult:
            await _ticket(conn, ctx)
            row = await _one(
                conn,
                "INSERT INTO itsm.store_messages (run_id, ticket_id, kind, section_id, body, "
                "idem_key) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                (ctx.run_id, ctx.ticket_id, args.kind, args.section_id, args.body, args.idem_key),
            )
            row = _must(row)
            # The body may hold the real contact: never in the audit row.
            await _event(
                conn,
                ctx,
                "message_store",
                "written",
                step_id=args.section_id,
                payload={"idem_key": args.idem_key, "kind": args.kind, "id": row["id"]},
            )
            return RowResult(status="written", id=str(row["id"]))

        return RowResult.model_validate(await idempotent(conn, ctx, "message_store", args, work))

    @service.tool(scope=SCOPE_WRITE)
    async def escalate_to_l2(args: EscalateIn, conn: Conn) -> TicketResult:
        """Hand the ticket to the L2 (or vendor) queue with the full handoff note and its
        reason code (D57)."""
        ctx = bound()

        async def work() -> TicketResult:
            await _ticket(conn, ctx, lock=True)
            await conn.execute(
                "UPDATE itsm.tickets SET status = 'escalated', route = 'handoff', "
                "assignee_queue = %s, updated_at = now() WHERE run_id = %s AND ticket_id = %s",
                (args.queue, ctx.run_id, ctx.ticket_id),
            )
            await conn.execute(
                "INSERT INTO itsm.ticket_comments (run_id, ticket_id, kind, body, idem_key) "
                "VALUES (%s, %s, 'l2_note', %s, %s)",
                (ctx.run_id, ctx.ticket_id, args.note, args.idem_key),
            )
            await _event(
                conn,
                ctx,
                "escalate_to_l2",
                "escalated",
                reason=args.reason_code,
                payload={"idem_key": args.idem_key, "queue": args.queue},
            )
            return TicketResult(status="escalated", ticket=Ticket(**await _ticket(conn, ctx)))

        return TicketResult.model_validate(
            await idempotent(conn, ctx, "escalate_to_l2", args, work)
        )

    @service.tool(scope=SCOPE_WRITE)
    async def create_approval(args: CreateApprovalIn, conn: Conn) -> ApprovalResult:
        """Ask for approval of one IT action. Bound to (run, ticket, asset, runbook section,
        quote, action, the ticket's kb_rev); the quote must be in that section of the
        ticket's runbook. Expires APPROVAL_TTL_MIN after now (wall clock, D48)."""
        ctx = bound()

        async def work() -> ApprovalResult:
            t = await _ticket(conn, ctx)
            action = it.registry.get(args.action_id)
            if action is None:
                raise ToolFailure(ErrorCode.DENIED, "unknown_action")
            if args.asset_id != t["asset_id"]:
                raise ToolFailure(ErrorCode.DENIED, "not_ticket_asset")
            section = await _section(conn, t, args.section_id, args.quote)
            if section is None:
                raise ToolFailure(ErrorCode.DENIED, "section_not_in_runbook")
            if not section["quote_ok"]:
                raise ToolFailure(ErrorCode.DENIED, "quote_not_in_section")
            expires = it.clock() + timedelta(minutes=it.ttl_min)
            row = await _one(
                conn,
                "INSERT INTO itsm.approvals (run_id, ticket_id, asset_id, section_id, quote, "
                "action_id, kb_rev, approver_role, requested_by, requested_at, expires_at, "
                "idem_key) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                (
                    ctx.run_id, ctx.ticket_id, args.asset_id, args.section_id, args.quote,
                    args.action_id,
                    t["kb_rev"], args.approver_role, args.requested_by, it.clock(), expires,
                    args.idem_key,
                ),
            )  # fmt: skip
            row = _must(row)
            await _event(
                conn,
                ctx,
                "create_approval",
                "requested",
                kb_rev=t["kb_rev"],
                step_id=args.section_id,
                action_id=args.action_id,
                tier=action.tier,
                approval_id=str(row["id"]),
                payload={"idem_key": args.idem_key, "approver_role": args.approver_role},
            )
            return ApprovalResult(status="requested", approval_id=row["id"], expires_at=expires)

        return ApprovalResult.model_validate(
            await idempotent(conn, ctx, "create_approval", args, work)
        )

    @service.tool(scope=SCOPE_WRITE)
    async def decide_approval(args: DecideApprovalIn, conn: Conn) -> ApprovalResult:
        """Store an approver's decision (the API checked OPA P3/P4 before the agent resumed).
        A reject needs a reason and demotes the action in the same transaction."""
        ctx = bound()
        if args.decision == "reject" and not args.reason:
            raise ToolFailure(ErrorCode.INVALID, "reject_needs_reason")

        async def work() -> ApprovalResult:
            await _ticket(conn, ctx)
            a = await _one(
                conn,
                "SELECT id, asset_id, section_id, action_id, kb_rev, requested_by, decision, "
                "expires_at FROM itsm.approvals WHERE id = %s AND run_id = %s AND ticket_id = %s "
                "FOR UPDATE",
                (args.approval_id, ctx.run_id, ctx.ticket_id),
            )
            if a is None:
                raise ToolFailure(ErrorCode.DENIED, "approval_not_found")
            if a["decision"] is not None:
                raise ToolFailure(ErrorCode.CONFLICT, "approval_already_decided")
            if it.clock() >= a["expires_at"]:
                raise ToolFailure(ErrorCode.DENIED, "approval_expired")
            if args.decided_by == a["requested_by"]:
                raise ToolFailure(ErrorCode.DENIED, "approver_is_requester")
            decision = "approved" if args.decision == "approve" else "rejected"
            await conn.execute(
                "UPDATE itsm.approvals SET decision = %s, decided_by = %s, reason = %s, "
                "decided_at = %s WHERE id = %s",
                (decision, args.decided_by, args.reason, it.clock(), a["id"]),
            )
            action = it.registry.get(a["action_id"])
            state: str | None = None
            if decision == "rejected" and action is not None:
                model = await _one(
                    conn, "SELECT model FROM data.assets WHERE asset_id = %s", (a["asset_id"],)
                )
                if model is not None:
                    after = await autonomy.record_result(
                        conn, it.policy, action_id=action.action_id, tier=action.tier,
                        model=model["model"], approved=False, success=False,
                        threshold=it.threshold, eval_mode=it.eval_mode, run_id=ctx.run_id,
                        ticket_id=ctx.ticket_id, actor=ctx.client_id, event="reject",
                    )  # fmt: skip
                    state = after.state
            await _event(
                conn,
                ctx,
                "decide_approval",
                decision,
                reason=args.reason,
                kb_rev=a["kb_rev"],
                step_id=a["section_id"],
                action_id=a["action_id"],
                approval_id=str(a["id"]),
                autonomy_state=state,
                payload={"idem_key": args.idem_key, "decided_by": args.decided_by},
            )
            return ApprovalResult(
                status=decision, approval_id=a["id"], expires_at=a["expires_at"],
                autonomy_state=state,
            )  # fmt: skip

        return ApprovalResult.model_validate(
            await idempotent(conn, ctx, "decide_approval", args, work)
        )

    @service.tool(scope=SCOPE_WRITE)
    async def create_l2_task(args: CreateL2TaskIn, conn: Conn) -> L2TaskResult:
        """A runbook step only L2 may do (the agent decides: L2-only, secret, destructive
        for the store, no listed action, or a runbook warning); the ticket waits."""
        ctx = bound()

        async def work() -> L2TaskResult:
            await _ticket(conn, ctx)
            row = await _one(
                conn,
                "INSERT INTO itsm.l2_tasks (run_id, ticket_id, section_id, reason, note, "
                "idem_key) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                (
                    ctx.run_id,
                    ctx.ticket_id,
                    args.section_id,
                    args.reason,
                    args.note,
                    args.idem_key,
                ),  # fmt: skip
            )
            row = _must(row)
            await _event(
                conn,
                ctx,
                "create_l2_task",
                "created",
                reason=args.reason,
                step_id=args.section_id,
                payload={"idem_key": args.idem_key, "task_id": str(row["id"])},
            )
            return L2TaskResult(status="created", task_id=row["id"])

        return L2TaskResult.model_validate(
            await idempotent(conn, ctx, "create_l2_task", args, work)
        )

    @service.tool(scope=SCOPE_FIX)
    async def run_fix(args: RunFixIn, conn: Conn) -> RunFixResult:
        """Run one simulated IT fix. The server checks everything itself (OPA P8): registry
        and its version, own store and asset, the quoted runbook words, tier, autonomy
        and the approval. It records the outcome and autonomy itself."""
        ctx = bound()
        try:
            return RunFixResult.model_validate(
                await idempotent(conn, ctx, "run_fix", args, lambda: _run_fix(conn, ctx, args))
            )
        except Denied as exc:
            reason = ",".join(sorted(exc.reasons))[:300]
            await _event(
                conn,
                ctx,
                "run_fix",
                "denied",
                reason=reason,
                step_id=args.section_id,
                action_id=args.action_id,
                approval_id=str(args.approval_id) if args.approval_id else None,
                payload={"idem_key": args.idem_key, **exc.cols},
            )
            raise ToolFailure(ErrorCode.DENIED, reason) from None

    async def _run_fix(conn: Conn, ctx: CallContext, args: RunFixIn) -> RunFixResult:
        facts, model = await _run_fix_facts(conn, ctx, args)
        decision = await it.policy.decide(P8, facts)
        if decision is None:
            raise Denied(["opa_unavailable"])
        if decision.get("allow") is not True:
            raise Denied([str(r) for r in decision.get("deny", [])] or ["p8_denied"])
        action = it.registry.get(args.action_id)
        if action is None or model is None:  # P8 allowed it, so both exist
            raise ToolFailure(ErrorCode.ERROR, "facts_changed")
        ticket = facts["ticket"]
        state_at_run = facts["autonomy"]["state"]
        out = await it.outcome.outcome(action, ticket_id=str(ctx.ticket_id), asset_id=args.asset_id)
        if args.approval_id is not None:
            await conn.execute(
                "UPDATE itsm.approvals SET used_at = clock_timestamp() WHERE id = %s",
                (args.approval_id,),
            )
        row = await _one(
            conn,
            "INSERT INTO itsm.actions (run_id, ticket_id, asset_id, device_model, section_id, "
            "quote, action_id, kb_rev, registry_version, tier, autonomy_state_at_run, "
            "approval_id, outcome, result, eval_mode, idem_key) VALUES "
            "(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (
                ctx.run_id, ctx.ticket_id, args.asset_id, model, args.section_id, args.quote,
                args.action_id,
                ticket["kb_rev"], it.registry.version, action.tier, state_at_run,
                args.approval_id, out.outcome, out.text, it.eval_mode, args.idem_key,
            ),
        )  # fmt: skip
        row = _must(row)
        after = await autonomy.record_result(
            conn, it.policy, action_id=action.action_id, tier=action.tier, model=model,
            approved=args.approval_id is not None, success=out.success,
            threshold=it.threshold, eval_mode=it.eval_mode, run_id=ctx.run_id,
            ticket_id=ctx.ticket_id, actor=ctx.client_id,
        )  # fmt: skip
        await _event(conn, ctx, "run_fix", out.outcome, kb_rev=ticket["kb_rev"],
                     step_id=args.section_id, action_id=args.action_id, tier=action.tier,
                     autonomy_state=state_at_run,
                     approval_id=str(args.approval_id) if args.approval_id else None,
                     payload={"idem_key": args.idem_key, "action_row_id": row["id"],
                              "device_model": model, "autonomy_after": after.state,
                              "registry_version": it.registry.version,
                              "eval_mode": it.eval_mode})  # fmt: skip
        return RunFixResult(
            status="ran", action_row_id=str(row["id"]), outcome=out.outcome, result=out.text,
            tier=action.tier, autonomy_state_at_run=state_at_run,
            autonomy_state_after=after.state if action.tier != "read_only" else state_at_run,
            approval_id=args.approval_id,
        )  # fmt: skip

    async def _run_fix_facts(
        conn: Conn, ctx: CallContext, args: RunFixIn
    ) -> tuple[dict[str, Any], str | None]:
        """Everything P8 decides on, read from our own tables (never the caller), with the
        ticket, autonomy and approval rows locked until the transaction ends."""
        action = it.registry.get(args.action_id)
        t = await _one(
            conn,
            "SELECT store_id, asset_id, runbook_id, kb_rev FROM itsm.tickets "
            "WHERE run_id = %s AND ticket_id = %s FOR UPDATE",
            (ctx.run_id, ctx.ticket_id),
        )
        ticket = None
        section = None
        if t is not None:
            rev = (
                await _one(
                    conn,
                    "SELECT rule_versions->>'action_registry' AS v FROM kb.revisions "
                    "WHERE kb_rev = %s",
                    (t["kb_rev"],),
                )
                if t["kb_rev"]
                else None
            )
            ticket = {**t, "registry_version": rev["v"] if rev else None}
            section = await _section(conn, t, args.section_id, args.quote)
        asset = await _one(
            conn,
            "SELECT store_id, asset_type, model FROM data.assets WHERE asset_id = %s",
            (args.asset_id,),
        )
        model = asset["model"] if asset else None
        state = autonomy.Autonomy()
        if action is not None and model is not None and action.tier != "read_only":
            state = await autonomy.current(conn, action.action_id, model, lock=True)
        approval = None
        if args.approval_id is not None:
            a = await _one(
                conn,
                "SELECT run_id, ticket_id, asset_id, section_id, quote, action_id, kb_rev, "
                "decision, approver_role, expires_at, used_at FROM itsm.approvals "
                "WHERE id = %s FOR UPDATE",
                (args.approval_id,),
            )
            if a is not None:
                approval = {
                    **{k: a[k] for k in ("ticket_id", "asset_id", "section_id", "quote",
                                         "action_id", "kb_rev", "decision", "approver_role")},
                    "run_id": str(a["run_id"]),
                    "expires_ns": int(a["expires_at"].timestamp() * 1e9),
                    "used": a["used_at"] is not None,
                }  # fmt: skip
        facts = {
            "subject": {"client_id": ctx.client_id},
            "context": {
                "run_id": str(ctx.run_id), "ticket_id": ctx.ticket_id, "store_id": ctx.store_id,
            },
            "request": {
                "asset_id": args.asset_id, "section_id": args.section_id, "quote": args.quote,
                "action_id": args.action_id,
                "approval_id": str(args.approval_id) if args.approval_id else None,
            },
            "now_ns": int(it.clock().timestamp() * 1e9),
            "registry": {
                "version": it.registry.version,
                "action": None if action is None else {
                    "tier": action.tier, "device_families": list(action.device_families),
                    "approver": action.approver,
                },
            },
            "ticket": ticket,
            "asset": None if asset is None else {
                "store_id": asset["store_id"], "family": family_of(asset["asset_type"]),
            },
            "section": section,
            "autonomy": {"state": state.state},
            "approval": approval,
        }  # fmt: skip
        return facts, model


# ---- service -------------------------------------------------------------------------


def build_service(
    settings: ItsmSettings,
    *,
    verifier: JwtVerifier | None = None,
    policy: Policy | None = None,
    decider: Decider | None = None,
    pool: AsyncConnectionPool[AsyncConnection[Any]] | None = None,
    registry: Registry | None = None,
    outcome: OutcomeProvider | None = None,
    clock: Callable[[], datetime] | None = None,
) -> McpService:
    opa = OpaClient(settings.opa_url)
    service = McpService(
        name=NAME,
        policy_prefix=POLICY_PREFIX,
        issuer=settings.keycloak_issuer,
        verifier=verifier
        or JwtVerifier(issuer=settings.keycloak_issuer, audience=NAME, jwks_url=settings.jwks_url),
        policy=policy or opa,
        pool=pool
        or AsyncConnectionPool(
            dsn(settings.database_url_itsm, settings.db_host),
            min_size=1,
            max_size=10,
            open=False,
            kwargs={"autocommit": True},
        ),
        public_url=f"http://localhost:{settings.itsm_port}",
    )
    it = Itsm(
        registry=registry or default_registry(),
        policy=decider or opa,
        outcome=outcome or provider_for(settings.eval_mode),
        threshold=settings.action_autonomy_runs,
        ttl_min=settings.approval_ttl_min,
        eval_mode=settings.eval_mode,
    )
    if clock is not None:
        it.clock = clock
    register(service, it)
    return service
