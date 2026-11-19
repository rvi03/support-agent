"""CP11.3: the SLA timer hands off a paused ticket past escalate-by under the replay
clock, once; and an approval racing the timer has exactly one winner (Codex F2).
Scripted model, live platform (`make up`); mock values only (D70)."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

import psycopg
import pytest

from support_agent.agent.app import Agent
from support_agent.agent.graph import thread
from support_agent.agent.runtime import WrongState
from support_agent.agent.sla_timer import SlaTimer, due_tickets
from support_agent.common.config import AgentSettings, get_settings
from support_agent.common.db import dsn
from tests.integration.walk_harness import (
    ScriptedLLM,
    answer,
    db,
    reset_autonomy,
    rows,
    start,
    ticket,
    triage_verdict,
    turn,
)

pytestmark = pytest.mark.integration
PRINTER = triage_verdict("runbooks/printer-offline.md", "Printers", "Receipt Printer")
MODEL = "StarMC Print v2"


def _timer(agent: Agent, *runs: str) -> SlaTimer:
    s = get_settings(AgentSettings)
    return SlaTimer(agent.app, agent.deps, agent.locker, dsn(s.database_url_agent, s.db_host),
                    only_runs=frozenset(runs))  # fmt: skip


def _push_clock(run_id: str, tid: str, minutes: int) -> None:
    """Move one ticket's own clock (the itsm row the timer reads) forward."""
    with db() as c:
        c.execute(
            "UPDATE itsm.tickets SET clock_offset = clock_offset + make_interval("
            "mins => %s) WHERE run_id = %s AND ticket_id = %s",
            (minutes, run_id, tid),
        )


def _tid() -> str:
    return f"LOCAL-S11T-{uuid.uuid4().hex[:8].upper()}"


async def _two_tickets() -> None:
    a, b = _tid(), _tid()
    agent, run_id, out_a = await start(
        ticket(a, opened=datetime(2026, 3, 10, 4, 0, tzinfo=UTC)),
        ScriptedLLM(PRINTER, [turn("next", "po-physical-check")]),
    )
    try:
        _, _, out_b = await start(
            ticket(b, opened=datetime(2026, 4, 2, 9, 30, tzinfo=UTC)),
            ScriptedLLM(PRINTER, [turn("next", "po-physical-check")]), run_id=run_id,
            agent=agent,
        )  # fmt: skip
        assert out_a.paused and out_b.paused
        timer = _timer(agent, run_id)
        assert await timer.tick() == []  # neither is past escalate-by yet
        _push_clock(run_id, a, 200)  # P3: escalate-by is 180 minutes after opening
        first = await timer.tick()
        assert [(r.ticket_id, r.action, r.detail) for r in first] == [(a, "handoff", "sla_breach")]
        assert await timer.tick() == []  # no duplicate
        status = dict(rows("SELECT ticket_id, status FROM itsm.tickets WHERE run_id = %s",
                           run_id))  # fmt: skip
        assert status == {a: "escalated", b: "waiting_store"}
        reasons = rows("SELECT reason FROM audit.events WHERE run_id = %s AND ticket_id = %s "
                       "AND action = 'escalate_to_l2' AND step = 'itsm'", run_id, a)  # fmt: skip
        assert reasons == [("sla_breach",)]
        cleared = rows("SELECT cleared_by FROM itsm.pending WHERE run_id = %s AND ticket_id = %s",
                       run_id, a)  # fmt: skip
        assert cleared == [("timeout",)]
        assert rows("SELECT cleared_at IS NULL FROM itsm.pending WHERE run_id = %s AND "
                    "ticket_id = %s", run_id, b) == [(True,)]  # fmt: skip
    finally:
        await agent.aclose()


def test_cp11_3_timer_hands_off_only_the_ticket_past_escalate_by() -> None:
    asyncio.run(_two_tickets())


async def _race_once(agent: Agent, delay_s: float) -> str:
    reset_autonomy("restart_print_spooler", MODEL)
    tid = _tid()
    llm = ScriptedLLM(PRINTER, [turn("next", "po-usb-spooler-restart"), turn("fixed")])
    _, run_id, out = await start(ticket(tid), llm, agent=agent)
    assert out.paused and out.paused["kind"] == "approval", out.state.handoff_reason
    _push_clock(run_id, tid, 200)  # the timer sees the ticket past escalate-by
    timer = _timer(agent, run_id)
    async with await psycopg.AsyncConnection.connect(timer.conninfo) as conn:
        due = await due_tickets(conn)
    assert any(d.ticket_id == tid and d.kind == "approval" for d in due)  # a real contender

    async def approve() -> Any:
        await asyncio.sleep(delay_s)  # stagger, so either side can win
        try:
            return await answer(agent, run_id, out, {"decision": "approve",
                                                     "decided_by": "l2-mock"})  # fmt: skip
        except WrongState as exc:
            return exc

    ticked, approved = await asyncio.gather(timer.tick(), approve())
    actions = rows("SELECT count(*) FROM itsm.actions WHERE run_id = %s AND ticket_id = %s",
                   run_id, tid)[0][0]  # fmt: skip
    escalated = rows(
        "SELECT count(*) FROM audit.events WHERE run_id = %s AND ticket_id = %s "
        "AND action = 'escalate_to_l2' AND step = 'itsm'", run_id, tid,
    )[0][0]  # fmt: skip
    timer_won = any(r.action == "handoff" for r in ticked)
    approve_won = not isinstance(approved, WrongState)
    assert timer_won != approve_won, (ticked, approved)
    if timer_won:
        assert actions == 0 and escalated == 1
        return "timer"
    # The approval won the pending item, but the clock is past escalate-by, so the
    # server runs nothing and the ticket hands off (S12a, D136); the API's P3 would
    # already have refused that approval.
    assert actions == 0 and escalated == 1, (actions, escalated)
    assert approved.state.handoff_reason == "sla_breach"
    assert all(r.action != "handoff" for r in ticked)
    return "approve"


async def _race() -> list[str]:
    agent, _, _ = await start(ticket(_tid()), ScriptedLLM(PRINTER, [turn("stuck")]))
    try:
        return [await _race_once(agent, (i % 4) * 0.1) for i in range(20)]
    finally:
        await agent.aclose()
        reset_autonomy("restart_print_spooler", MODEL)


def test_cp11_3_approval_and_timer_race_has_one_winner() -> None:
    winners = asyncio.run(_race())
    assert len(winners) == 20
    assert set(winners) == {"timer", "approve"}  # both sides won some runs
    print("winners:", {w: winners.count(w) for w in set(winners)})


async def _orphan() -> None:
    """S12a: the API claimed the pending item (before its 202) and the process stopped
    before the background resume; the timer must still hand the ticket off."""
    from support_agent.agent.graph import claim

    reset_autonomy("restart_print_spooler", MODEL)
    tid = _tid()
    llm = ScriptedLLM(PRINTER, [turn("next", "po-usb-spooler-restart"), turn("fixed")])
    agent, run_id, out = await start(ticket(tid), llm)
    try:
        assert out.paused and out.paused["kind"] == "approval", out.state.handoff_reason
        await claim(agent.app, agent.deps, run_id, tid, str(out.paused["pending_id"]), "approval")
        # crash here: no continue_run; the pending item is cleared, the graph still paused
        _push_clock(run_id, tid, 200)
        ticked = await _timer(agent, run_id).tick()
        assert [(r.ticket_id, r.action, r.detail) for r in ticked] == [
            (tid, "handoff", "sla_breach")
        ]
        assert not (await agent.app.aget_state(thread(run_id, tid))).next
        assert rows("SELECT count(*) FROM itsm.actions WHERE run_id = %s AND ticket_id = %s",
                    run_id, tid) == [(0,)]  # fmt: skip
        assert rows("SELECT status FROM itsm.tickets WHERE run_id = %s AND ticket_id = %s",
                    run_id, tid) == [("escalated",)]  # fmt: skip
    finally:
        await agent.aclose()
        reset_autonomy("restart_print_spooler", MODEL)


def test_s12a_orphaned_claim_is_handed_off_by_the_timer() -> None:
    asyncio.run(_orphan())
