"""What each endpoint does once the token, the body, the rate limit and OPA passed
(S12 build steps 3 and 7).

- `create`: the raw JSON goes to `raw/tickets/incoming/` first, then the
  tickets.api_tickets row (a duplicate replay is 409 here, D45), then 202. Intake
  and the graph run in a background task under the per-ticket lock.
- `reply` and `approve`: the ticket lock is taken and the pending item claimed
  (the D53 compare-and-clear) before the 202, so a busy lock, a stale
  `pending_id` or a lost race is a 409 with nothing changed. The graph then
  continues in the background and the lock is released when it stops.

A background task is lost if the API restarts mid-run; the checkpointer keeps the
state and the SLA timer hands the ticket off (S12 risks; a durable queue is parked).
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from support_agent.agent.graph import RunOutcome, claim, continue_run, run_ticket
from support_agent.agent.runtime import WrongState
from support_agent.agent.state import TicketState
from support_agent.api.auth import Subject
from support_agent.api.store import ApiStore, Row
from support_agent.common.logging import get_logger
from support_agent.intake.pipeline import IntakeResult
from support_agent.intake.safety_net import PIIBlocked

log = get_logger(__name__)

INCOMING = "raw/tickets/incoming/"
REPLY_KINDS = ("store_reply", "answer")


class ApiError(Exception):
    """An HTTP error the API answers and audits (401/403/404/409/413/422/429)."""

    def __init__(self, status: int, reason: str, *, rule: str | None = None) -> None:
        super().__init__(reason)
        self.status, self.reason, self.rule = status, reason, rule
        # The ticket the call was about, once known (for the denial's audit event).
        self.resource: dict[str, Any] | None = None


class RawWriter(Protocol):
    async def put(self, key: str, body: bytes) -> None: ...


class AgentHost(Protocol):
    """The parts of `agent.app.Agent` the API uses (a fake in unit tests)."""

    app: Any
    deps: Any
    locker: Any

    def reload_contact(self, ticket_id: str) -> bool: ...

    def mask_text(self, ticket_id: str, text: str) -> str: ...


IntakeFn = Callable[[dict[str, Any]], Awaitable[IntakeResult]]


def new_ticket_id() -> str:
    return f"SWT-{uuid.uuid4().hex[:12].upper()}"


@dataclass
class TicketService:
    store: ApiStore
    raw: RawWriter
    agent: AgentHost
    intake: IntakeFn
    wall: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    tasks: set[asyncio.Task[Any]] = field(default_factory=set)

    # ---- create ------------------------------------------------------------------------

    async def create(self, subject: Subject, body: dict[str, Any], *, store_id: str,
                     date_opened: datetime, source_ticket_id: str | None,
                     run_id: uuid.UUID) -> str:  # fmt: skip
        ticket_id = new_ticket_id()
        raw: dict[str, Any] = {
            **body,
            "ticket_id": ticket_id,
            "store_id": store_id,
            "date_opened": date_opened.isoformat(),
        }
        if source_ticket_id is None:
            # Ordinary intake: the contact comes from the token's profile claims.
            raw["submitted_by"] = subject.name
            raw["contact_phone"] = subject.phone
        key = f"{INCOMING}{ticket_id}.json"
        await self.raw.put(key, json.dumps(raw, sort_keys=True).encode())
        await self.store.add_ticket(
            ticket_id=ticket_id, run_id=run_id, store_id=store_id,
            submitted_by_user=subject.user, client_id=subject.client_id,
            source_ticket_id=source_ticket_id, date_opened=date_opened, raw_key=key,
        )  # fmt: skip
        self._spawn(self._run_new(raw, run_id, subject.user, source_ticket_id), ticket_id)
        return ticket_id

    async def _run_new(
        self, raw: dict[str, Any], run_id: uuid.UUID, user: str, source_ticket_id: str | None
    ) -> None:
        ticket_id = str(raw["ticket_id"])
        await self.store.set_state(ticket_id, "running")
        try:
            result = await self.intake(raw)
        except PIIBlocked:
            await self.store.set_state(ticket_id, "failed", error="pii_blocked")
            return
        if source_ticket_id:
            await self.store.copy_source_contact(source_ticket_id, ticket_id)
            await asyncio.to_thread(self.agent.reload_contact, ticket_id)
        else:
            await self.store.write_vault(ticket_id, result.contact, result.mask_map)
        await self.store.set_state(ticket_id, "running", subject=result.ticket.subject)
        state = initial_state(result, str(run_id), wall=self.wall()).model_copy(
            update={"submitted_by_user": user, "source_ticket_id": source_ticket_id}
        )
        outcome = await run_ticket(self.agent.app, state, locker=self.agent.locker)
        await self._settle(ticket_id, outcome)

    async def _settle(self, ticket_id: str, outcome: RunOutcome) -> None:
        await self.store.set_state(ticket_id, "running" if outcome.paused else "done")

    # ---- reply and approve -------------------------------------------------------------

    async def reply(self, resource: Row, pending_id: str, text: str) -> None:
        kind = _open_kind(resource, pending_id, REPLY_KINDS)
        await self._claim_and_continue(resource, pending_id, kind, {"text": text})

    async def approve(self, subject: Subject, resource: Row, pending_id: str, decision: str,
                      reason: str | None, result: str | None) -> None:  # fmt: skip
        kind = _open_kind(resource, pending_id, ("approval", "l2_task"))
        if kind == "approval":
            if decision not in ("approve", "reject"):
                raise ApiError(409, "decision_does_not_fit_an_approval")
            if decision == "reject" and not reason:
                raise ApiError(422, "reject_needs_a_reason")
            payload: dict[str, Any] = {
                "decision": decision, "decided_by": subject.user, "reason": reason,
            }  # fmt: skip
        else:
            if decision not in ("done", "failed"):
                raise ApiError(409, "decision_does_not_fit_an_l2_task")
            payload = {"result": decision, "note": result or decision, "done_by": subject.user}
        await self._claim_and_continue(resource, pending_id, kind, payload)

    async def _claim_and_continue(
        self, resource: Row, pending_id: str, kind: str, payload: dict[str, Any]
    ) -> None:
        run_id, ticket_id = str(resource["run_id"]), str(resource["ticket_id"])
        hold = self.agent.locker.hold(run_id, ticket_id)
        try:
            await hold.__aenter__()
        except WrongState as exc:  # Busy: the graph is running now
            raise ApiError(409, "ticket_busy") from exc
        try:
            await asyncio.to_thread(self.agent.reload_contact, ticket_id)
            # Free text is masked before the claim, so the resume value the
            # checkpointer persists never holds a raw name or phone (S12a).
            payload = await asyncio.to_thread(self._masked, ticket_id, payload)
            await claim(self.agent.app, self.agent.deps, run_id, ticket_id, pending_id, kind)
        except WrongState as exc:
            await hold.__aexit__(None, None, None)
            raise ApiError(409, f"stale_or_cleared_pending: {exc}"[:200]) from exc
        except BaseException:
            await hold.__aexit__(None, None, None)
            raise

        async def go() -> None:
            try:
                outcome = await continue_run(self.agent.app, run_id, ticket_id, kind, payload)
            finally:
                await hold.__aexit__(None, None, None)
            await self._settle(ticket_id, outcome)

        self._spawn(go(), ticket_id)

    def _masked(self, ticket_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            k: self.agent.mask_text(ticket_id, v)
            if k in FREE_TEXT and isinstance(v, str) and v
            else v
            for k, v in payload.items()
        }

    # ---- background --------------------------------------------------------------------

    def _spawn(self, work: Awaitable[None], ticket_id: str) -> None:
        async def guarded() -> None:
            try:
                await work
            except Exception as exc:  # the graph hands off itself; this is a crash
                log.error("api_background_failed", ticket_id=ticket_id,
                          error=type(exc).__name__)  # fmt: skip
                try:
                    await self.store.set_state(ticket_id, "failed", error=type(exc).__name__)
                except Exception:  # noqa: BLE001 - nothing more to do
                    log.error("api_state_write_failed", ticket_id=ticket_id)

        task = asyncio.get_running_loop().create_task(guarded())
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def drain(self, timeout: float = 30.0) -> None:
        """Wait for running tasks (tests and shutdown)."""
        if self.tasks:
            await asyncio.wait(set(self.tasks), timeout=timeout)

    # ---- reads -------------------------------------------------------------------------

    async def state(self, resource: Row) -> tuple[TicketState | None, dict[str, Any] | None]:
        """The checkpointed state and the open interrupt value (the approval card)."""
        from support_agent.agent.graph import thread

        cfg = thread(str(resource["run_id"]), str(resource["ticket_id"]))
        snap = await self.agent.app.aget_state(cfg)
        if not snap.values:
            return None, None
        state = TicketState.model_validate(snap.values)
        value = None
        for task in getattr(snap, "tasks", ()) or ():
            for intr in getattr(task, "interrupts", ()) or ():
                value = dict(intr.value)
        return state, value


# fields typed by people: the store's reply, a reject reason, an L2 task result note
FREE_TEXT = frozenset({"text", "reason", "note"})


def _open_kind(resource: Row, pending_id: str, kinds: tuple[str, ...]) -> str:
    """The open pending item's kind, if `pending_id` names it and it fits; else 409."""
    open_id = resource.get("pending_id")
    if open_id is None or str(open_id) != pending_id:
        raise ApiError(409, "no_open_pending_with_this_id")
    kind = str(resource.get("pending_kind"))
    if kind not in kinds:
        raise ApiError(409, f"pending_is_{kind}")
    return kind


def initial_state(result: IntakeResult, run_id: str, *, wall: datetime) -> TicketState:
    from support_agent.cli.ticket_local import initial_state as build

    return build(result, run_id, wall=wall)
