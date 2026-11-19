"""SLA timer (S11 build step 7; agent-architecture.md, SLA timer; D48, D53).

Every tick (APScheduler, every `SLA_TIMER_INTERVAL_S`), guarded by a Postgres
advisory lock so only one runner fires:

- it selects tickets whose own now (wall time + `clock_offset`, replay-aware) is
  past escalate-by and that are not resolved, redirected, escalated, closed or
  waiting on an L2 task;
- a paused graph: `resume(..., kind="timeout")`, which clears the open pending item
  with the same atomic compare-and-clear as a reply or an approval. Only if the
  timer wins does the ticket hand off (`sla_breach`); if a reply or an approval
  won, the timer gets `WrongState` and does nothing, and the reverse holds too.
  The advisory lock only stops two timers; the pending row decides the race;
- a finished graph with a human L1 (L1 pack): a new HANDOFF run on the same thread.

The timer reads only ids, status and deadlines (db/sql/011_sla_timer.sql); every
write goes through itsm-actions.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import psycopg

from support_agent.agent.graph import Locker, RunOutcome, resume, thread
from support_agent.agent.runtime import Deps, WrongState
from support_agent.agent.state import TicketState

TIMER_LOCK = "servewell:sla_timer"
SKIP_STATUS = ("resolved", "redirected", "escalated", "closed", "waiting_l2")

DUE_SQL = """
SELECT t.run_id::text, t.ticket_id, t.status, t.route, p.pending_id::text, p.kind
FROM itsm.tickets t
LEFT JOIN itsm.pending p
  ON p.run_id = t.run_id AND p.ticket_id = t.ticket_id AND p.cleared_at IS NULL
WHERE t.escalate_by IS NOT NULL
  AND now() + t.clock_offset > t.escalate_by
  AND t.status <> ALL(%s)
ORDER BY t.escalate_by
"""


@dataclass(frozen=True)
class Due:
    run_id: str
    ticket_id: str
    status: str
    route: str | None
    pending_id: str | None
    kind: str | None


@dataclass(frozen=True)
class TickResult:
    run_id: str
    ticket_id: str
    action: str  # handoff | lost_race | busy | skipped
    detail: str = ""


async def due_tickets(conn: psycopg.AsyncConnection[Any]) -> list[Due]:
    cur = await conn.execute(DUE_SQL, (list(SKIP_STATUS),))
    return [Due(*row) for row in await cur.fetchall()]


@dataclass
class SlaTimer:
    app: Any
    deps: Deps
    locker: Locker
    conninfo: str
    only_runs: frozenset[str] | None = None  # tests: limit a tick to these run ids

    @asynccontextmanager
    async def _only_runner(self) -> AsyncIterator[bool]:
        conn = await psycopg.AsyncConnection.connect(self.conninfo, autocommit=True)
        try:
            cur = await conn.execute(
                "SELECT pg_try_advisory_lock(hashtextextended(%s, 0))", (TIMER_LOCK,)
            )
            row = await cur.fetchone()
            got = bool(row and row[0])
            try:
                yield got
            finally:
                if got:
                    await conn.execute(
                        "SELECT pg_advisory_unlock(hashtextextended(%s, 0))", (TIMER_LOCK,)
                    )
        finally:
            await conn.close()

    async def tick(self) -> list[TickResult]:
        async with self._only_runner() as got:
            if not got:
                return []
            conn = await psycopg.AsyncConnection.connect(self.conninfo, autocommit=True)
            try:
                due = [d for d in await due_tickets(conn)
                       if self.only_runs is None or d.run_id in self.only_runs]  # fmt: skip
            finally:
                await conn.close()
            return [await self._one(d) for d in due]

    async def _one(self, d: Due) -> TickResult:
        if d.pending_id:
            try:
                out = await resume(
                    self.app, self.deps, d.run_id, d.ticket_id, d.pending_id, "timeout", {},
                    locker=self.locker, idem_step=f"sla_breach:{d.pending_id}",
                )  # fmt: skip
            except WrongState as exc:  # a reply or an approval won, or it is running now
                return TickResult(d.run_id, d.ticket_id, "lost_race", str(exc)[:200])
            return TickResult(d.run_id, d.ticket_id, "handoff", _reason(out))
        return await self._finished(d)

    async def _finished(self, d: Due) -> TickResult:
        """A finished graph handed to a human L1: start a HANDOFF on the same thread."""
        cfg = thread(d.run_id, d.ticket_id)
        snap = await self.app.aget_state(cfg)
        if not snap.values or snap.next:
            return TickResult(d.run_id, d.ticket_id, "skipped", "no finished graph")
        state = TicketState.model_validate(snap.values)
        if state.status != "with_l1":
            return TickResult(d.run_id, d.ticket_id, "skipped", f"status {state.status}")
        try:
            async with self.locker.hold(d.run_id, d.ticket_id):
                # As if the Clarify wait had handed off: its edge goes to Handoff.
                await self.app.aupdate_state(
                    cfg, {"handoff_reason": "sla_breach", "status": "in_progress"}, as_node="wait"
                )
                result = await self.app.ainvoke(None, cfg)
        except WrongState as exc:
            return TickResult(d.run_id, d.ticket_id, "busy", str(exc)[:200])
        del result
        snap = await self.app.aget_state(cfg)
        return TickResult(d.run_id, d.ticket_id, "handoff",
                          str(snap.values.get("handoff_reason")))  # fmt: skip


def _reason(out: RunOutcome) -> str:
    return str(out.state.handoff_reason)


def schedule(timer: SlaTimer, interval_s: int) -> Any:
    """Start the APScheduler job (the API process runs one; S12)."""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import-untyped]

    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(timer.tick, "interval", seconds=interval_s, max_instances=1,
                      coalesce=True, id="sla_timer")  # fmt: skip
    scheduler.start()
    return scheduler
