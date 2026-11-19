"""CP10.1 and the D53 pending contract, live (`make up`, real model on the `agent` alias).

One fixture ticket per route (tests/fixtures/tickets, mock contact values only,
D70) through `ticket-local`'s in-process path: intake -> graph -> itsm. Each
route and the final status are asserted, and the itsm ticket row matches.

Pending contract (with the Clarify route): a resume with an unknown `pending_id`,
or the right id with the wrong kind, is `WrongState`, and the checkpoint and
the itsm rows are unchanged; the right resume completes; repeating it is
`WrongState`.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

import psycopg
import pytest

from support_agent.agent.app import build_agent
from support_agent.agent.graph import resume, run_ticket, thread
from support_agent.agent.runtime import WrongState
from support_agent.cli.ticket_local import initial_state, intake, main_async
from support_agent.common.config import AgentSettings, get_settings
from tests.integration.platform_env import load_env, superuser_url

pytestmark = pytest.mark.integration
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "tickets"
ANSWER = "The receipt printer at the front counter shows Offline in the POS and jobs stay queued."

# fixture -> (route, final status, handoff reason or None, itsm status)
EXPECTED = {
    "l1_pack": ("l1_pack", "with_l1", None, "in_progress"),
    "handoff": ("handoff", "escalated", "sop_trigger", "escalated"),
    "human": ("human", "escalated", "unknown_system", "escalated"),
    "redirect": ("redirect", "redirected", None, "redirected"),
}


def _row(run_id: str, ticket_id: str) -> dict[str, Any]:
    with psycopg.connect(superuser_url(load_env())) as c:
        cur = c.execute(
            "SELECT status, route, assignee_queue FROM itsm.tickets "
            "WHERE run_id = %s AND ticket_id = %s",
            (run_id, ticket_id),
        )
        row = cur.fetchone()
        assert row is not None, "no itsm ticket row"
        return dict(zip(("status", "route", "queue"), row, strict=True))


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_each_route_reaches_its_outcome(name: str) -> None:
    route, status, reason, itsm_status = EXPECTED[name]
    run_id = str(uuid.uuid4())
    out = asyncio.run(main_async(FIXTURES / f"route_{name}.json", [], run_id=run_id, quiet=True))
    s = out.state
    assert out.paused is None
    assert s.route is not None and s.route.route == route, (s.route, s.handoff_reason)
    assert s.status == status
    assert s.handoff_reason == reason
    assert s.failed_node is None
    row = _row(run_id, s.ticket.ticket_id)
    assert row["status"] == itsm_status
    if status == "escalated":
        assert s.note_text and "Store contact: on file (vault)" in s.note_text


def test_resolver_route_walks_the_runbook() -> None:
    """S11: the Group A route walks (store steps, IT actions, approvals) to fixed or L2."""
    run_id = str(uuid.uuid4())
    replies = ["Done. Power light on, USB cable firm, the POS still shows Offline."] * 10
    out = asyncio.run(
        main_async(FIXTURES / "route_resolver.json", replies, run_id=run_id, quiet=True)
    )
    s = out.state
    assert out.paused is None and s.failed_node is None
    assert s.route is not None and s.route.route == "resolver"
    assert s.walk is not None and s.walk.steps
    assert (s.status, s.handoff_reason) in {
        ("resolved", None), ("escalated", "steps_exhausted"), ("escalated", "budget_exceeded"),
    }, (s.status, s.handoff_reason)  # fmt: skip
    assert _row(run_id, s.ticket.ticket_id)["status"] == s.status


def test_clarify_asks_once_then_triages_again() -> None:
    run_id = str(uuid.uuid4())
    # After the answer the ticket may go on to the walk (S11): later pauses get store replies.
    replies = [ANSWER] + ["Done. The POS still shows the printer Offline."] * 10
    out = asyncio.run(
        main_async(FIXTURES / "route_clarify.json", replies, run_id=run_id, quiet=True)
    )
    s = out.state
    assert s.clarify_count == 1
    assert [d.kind for d in s.drafts][0] == "clarify"
    assert s.route is not None and s.route.route != "clarify"
    assert "Store's answer to" in s.ticket.description


def _pending(run_id: str, ticket_id: str) -> list[tuple[Any, ...]]:
    with psycopg.connect(superuser_url(load_env())) as c:
        return c.execute(
            "SELECT pending_id, kind, cleared_at IS NOT NULL, cleared_by FROM itsm.pending "
            "WHERE run_id = %s AND ticket_id = %s ORDER BY created_at",
            (run_id, ticket_id),
        ).fetchall()


async def _pending_contract() -> None:
    raw = json.loads((FIXTURES / "route_clarify.json").read_text())
    result = intake(raw)
    tid = result.ticket.ticket_id
    agent = await build_agent(get_settings(AgentSettings))
    run_id = str(uuid.uuid4())
    try:
        first = await run_ticket(agent.app, initial_state(result, run_id), locker=agent.locker)
        assert first.paused is not None and first.paused["kind"] == "answer"
        pid = str(first.paused["pending_id"])
        cfg = thread(run_id, tid)
        before = (await agent.app.aget_state(cfg)).values
        rows_before = _pending(run_id, tid)
        assert len(rows_before) == 1 and rows_before[0][2] is False

        for bad_id, kind in ((str(uuid.uuid4()), "answer"), (pid, "approval")):
            with pytest.raises(WrongState):
                await resume(agent.app, agent.deps, run_id, tid, bad_id, kind, {"text": ANSWER},
                             locker=agent.locker)  # fmt: skip
            assert (await agent.app.aget_state(cfg)).values == before
            assert _pending(run_id, tid) == rows_before

        done = await resume(agent.app, agent.deps, run_id, tid, pid, "answer", {"text": ANSWER},
                            locker=agent.locker)  # fmt: skip
        # Back to Triage; a printer answer may go on to the walk and pause there (S11).
        assert done.state.clarify_count == 1
        assert done.paused is None or done.paused["kind"] == "store_reply"
        assert _pending(run_id, tid)[0][2:] == (True, "answer")
        with pytest.raises(WrongState):
            await resume(agent.app, agent.deps, run_id, tid, pid, "answer", {"text": ANSWER},
                         locker=agent.locker)  # fmt: skip
        # The same ticket twice in one run is refused (D45).
        with pytest.raises(WrongState):
            await run_ticket(agent.app, initial_state(result, run_id), locker=agent.locker)
    finally:
        await agent.aclose()


def test_pending_contract() -> None:
    asyncio.run(_pending_contract())
