"""S11 Resolver walks, scripted model, live platform (`make up`); mock values only (D70).

CP11.1 printer walk to fixed; CP11.2 approval branches, autonomy, L2 tasks, stale
decisions and connection scope; CP11.5 a device the runbook does not cover.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest

from support_agent.agent.runtime import WrongState
from tests.integration.walk_harness import (
    ScriptedLLM,
    answer,
    reset_autonomy,
    rows,
    shift_wall,
    start,
    ticket,
    triage_verdict,
    turn,
)

pytestmark = pytest.mark.integration
PRINTER = triage_verdict("runbooks/printer-offline.md", "Printers", "Receipt Printer")
FROZEN = triage_verdict("runbooks/pos-screen-frozen.md", "POS", "POS Terminal")
MODEL = "StarMC Print v2"  # the device model of PRN-0003-P1
SAY = "MODEL TEXT: please factory reset everything"


def _tid() -> str:
    return f"LOCAL-S11-{uuid.uuid4().hex[:8].upper()}"


def _store_messages(run_id: str, tid: str) -> list[tuple[str, str, str | None]]:
    return [
        (r[0], r[1], r[2])
        for r in rows(
            "SELECT kind, body, section_id FROM itsm.store_messages WHERE run_id = %s "
            "AND ticket_id = %s ORDER BY id",
            run_id, tid,
        )
    ]  # fmt: skip


def _actions(run_id: str, tid: str) -> list[tuple[Any, ...]]:
    return rows(
        "SELECT action_id, tier, autonomy_state_at_run, approval_id, outcome FROM itsm.actions "
        "WHERE run_id = %s AND ticket_id = %s ORDER BY id",
        run_id, tid,
    )  # fmt: skip


def _status(run_id: str, tid: str) -> str:
    return str(rows("SELECT status FROM itsm.tickets WHERE run_id = %s AND ticket_id = %s",
                    run_id, tid)[0][0])  # fmt: skip


# ---- CP11.1 ----------------------------------------------------------------------------


async def _printer_to_fixed() -> None:
    tid = _tid()
    llm = ScriptedLLM(PRINTER, [
        turn("next", "po-physical-check", reason=SAY),
        turn("next", "po-usb-recognition", reply_quote="the USB cable is firm",
             connection="usb", connection_quote="the USB cable is firm"),
        turn("next", "po-restart-pos-app"),
        turn("fixed", reply_quote="it prints again now"),
    ])  # fmt: skip
    agent, run_id, out = await start(ticket(tid), llm)
    try:
        assert out.paused and out.paused["kind"] == "store_reply", out.state.handoff_reason
        out = await answer(agent, run_id, out, {"text": "Done. Power light is on and the USB "
                           "cable is firm, but the POS still shows Offline."})  # fmt: skip
        assert out.paused and out.paused["kind"] == "store_reply"
        out = await answer(agent, run_id, out, {"text": "Done, it prints again now."})
        s = out.state
        assert out.paused is None and s.status == "resolved", (s.status, s.handoff_reason)
        assert s.walk and s.walk.connection == "usb"
        assert [(a[0], a[1], a[4]) for a in _actions(run_id, tid)] == [
            ("check_printer_recognition", "read_only", "no_change")
        ]
        msgs = _store_messages(run_id, tid)
        kinds = [m[0] for m in msgs]
        assert kinds == ["framing_template", "step", "framing_template", "step", "summary"]
        assert all(SAY not in m[1] for m in msgs)  # the model's words never reach the store
        assert "Physical Check" in msgs[1][1] and msgs[1][2].endswith(
            "immediate-steps-first-2-minutes"
        )
        assert "Check that Windows lists the printer" in msgs[-1][1]
        assert "Testa" in msgs[-1][1]  # the first name, filled by the reply sender only
        notes = rows("SELECT kind, body FROM itsm.ticket_comments WHERE run_id = %s AND "
                     "ticket_id = %s", run_id, tid)  # fmt: skip
        assert any(k == "note" and b.startswith("Walk summary:") and "Testa" not in b
                   for k, b in notes)  # fmt: skip
        assert _status(run_id, tid) == "resolved"
        chain = [r[0] for r in rows(
            "SELECT action FROM audit.events WHERE run_id = %s AND ticket_id = %s AND "
            "step = 'agent' ORDER BY id", run_id, tid)]  # fmt: skip
        for node in ("triage", "policy", "resolver", "dispatch", "wait_walk", "finish",
                     "communicate"):  # fmt: skip
            assert node in chain, chain
    finally:
        await agent.aclose()


def test_cp11_1_printer_walks_to_fixed() -> None:
    asyncio.run(_printer_to_fixed())


# ---- CP11.2 ----------------------------------------------------------------------------


async def _approve_then_autonomous() -> None:
    reset_autonomy("restart_print_spooler", MODEL)
    tid = _tid()
    llm = ScriptedLLM(PRINTER, [turn("next", "po-usb-spooler-restart"), turn("fixed")])
    agent, run_id, out = await start(ticket(tid), llm)
    try:
        assert out.paused and out.paused["kind"] == "approval", out.state.handoff_reason
        card = out.paused["approval"]
        assert card["action_id"] == "restart_print_spooler" and card["tier"] == "reversible"
        out = await answer(agent, run_id, out, {"decision": "approve", "decided_by": "l2-mock"})
        assert out.state.status == "resolved", out.state.handoff_reason
        acts = _actions(run_id, tid)
        assert len(acts) == 1 and acts[0][3] is not None and acts[0][2] == "supervised"
        # A repeated run_fix with the same key returns the first reply; no new row.
        approval = str(acts[0][3])
        from support_agent.agent.runtime import Itsm

        itsm = Itsm(agent.deps.itsm, uuid.UUID(run_id), tid, "SW-0003")
        b = agent.deps.bindings.get("runbooks/printer-offline.md", "po-usb-spooler-restart")
        assert b is not None
        args = dict(asset_id="PRN-0003-P1", section_id=b.section, quote=b.span,
                    action_id="restart_print_spooler", approval_id=approval)  # fmt: skip
        await itsm.call("run_fix", "wait_walk", "walk-1-fix-0", **args)
        assert len(_actions(run_id, tid)) == 1
    finally:
        await agent.aclose()
    # ACTION_AUTONOMY_RUNS = 1: the next ticket runs it with no pause.
    tid2 = _tid()
    llm2 = ScriptedLLM(PRINTER, [turn("next", "po-usb-spooler-restart"), turn("fixed")])
    agent, run2, out = await start(ticket(tid2), llm2)
    try:
        assert out.paused is None and out.state.status == "resolved", out.state.handoff_reason
        acts = _actions(run2, tid2)
        assert len(acts) == 1 and acts[0][2] == "autonomous" and acts[0][3] is None
    finally:
        await agent.aclose()
        reset_autonomy("restart_print_spooler", MODEL)


def test_cp11_2_supervised_approve_once_then_autonomous() -> None:
    asyncio.run(_approve_then_autonomous())


async def _reject_hands_off() -> None:
    tid = _tid()
    llm = ScriptedLLM(PRINTER, [turn("next", "po-usb-clear-queue")])  # destructive
    agent, run_id, out = await start(ticket(tid), llm)
    try:
        assert out.paused and out.paused["kind"] == "approval"
        out = await answer(
            agent,
            run_id,
            out,
            {
                "decision": "reject",
                "decided_by": "l2-mock",
                "reason": "jobs for open orders in the queue",
            },
        )
        s = out.state
        assert s.status == "escalated" and s.handoff_reason == "approval_rejected"
        assert s.note_text and "jobs for open orders" in s.note_text
        assert _actions(run_id, tid) == []
        hist = rows("SELECT event, state_after, runs_after FROM itsm.action_autonomy_history "
                    "WHERE run_id = %s AND ticket_id = %s", run_id, tid)  # fmt: skip
        assert hist == [("reject", "supervised", 0)]
    finally:
        await agent.aclose()


def test_cp11_2_reject_hands_off_and_demotes() -> None:
    asyncio.run(_reject_hands_off())


async def _void_and_stale() -> None:
    reset_autonomy("restart_print_spooler", MODEL)
    tid = _tid()
    llm = ScriptedLLM(PRINTER, [turn("next", "po-usb-spooler-restart"), turn("fixed")])
    agent, run_id, out = await start(ticket(tid), llm)
    try:
        assert out.paused and out.paused["kind"] == "approval"
        old = out
        shift_wall(agent, 16)  # decided 16 wall minutes later: void, asked again
        out = await answer(agent, run_id, out, {"decision": "approve", "decided_by": "l2-mock"})
        assert out.paused and out.paused["kind"] == "approval"
        assert out.paused["pending_id"] != old.paused["pending_id"]  # type: ignore[index]
        assert out.paused["approval"]["approval_id"] != old.paused["approval"]["approval_id"]  # type: ignore[index]
        assert len(rows("SELECT 1 FROM itsm.approvals WHERE run_id = %s AND ticket_id = %s",
                        run_id, tid)) == 2  # fmt: skip
        shift_wall(agent, 0)
        with pytest.raises(WrongState):  # the old card after the re-ask (Codex F2)
            await answer(agent, run_id, old, {"decision": "approve", "decided_by": "l2-mock"})
        assert _actions(run_id, tid) == []
        out = await answer(agent, run_id, out, {"decision": "approve", "decided_by": "l2-mock"})
        assert out.state.status == "resolved"
        assert len(_actions(run_id, tid)) == 1
    finally:
        await agent.aclose()
        reset_autonomy("restart_print_spooler", MODEL)


def test_cp11_2_expired_approval_is_asked_again_and_stale_card_refused() -> None:
    asyncio.run(_void_and_stale())


async def _destructive_store_step_is_l2_task() -> None:
    tid = _tid()
    llm = ScriptedLLM(FROZEN, [turn("next", "psf-force-quit"), turn("stuck")])
    raw = ticket(tid, store_id="SW-0003", asset_id="POS-0003-T1", category="POS",
                 subject="POS touchscreen frozen", description="The POS touchscreen accepts "
                 "no input; taps and swipes produce no response since 10 minutes.")  # fmt: skip
    agent, run_id, out = await start(raw, llm)
    try:
        assert out.paused and out.paused["kind"] == "l2_task", out.state.handoff_reason
        tasks = rows("SELECT reason, result FROM itsm.l2_tasks WHERE run_id = %s AND "
                     "ticket_id = %s", run_id, tid)  # fmt: skip
        assert tasks == [("destructive_store_step", None)]
        assert all("End Task" not in m[1] for m in _store_messages(run_id, tid))
        out = await answer(
            agent,
            run_id,
            out,
            {
                "result": "done",
                "note": "Ended the task; the screen is still frozen.",
                "done_by": "l2-mock",
            },
        )
        s = out.state
        assert s.status == "escalated" and s.handoff_reason == "steps_exhausted"
        assert rows("SELECT result FROM itsm.l2_tasks WHERE run_id = %s AND ticket_id = %s",
                    run_id, tid) == [("done",)]  # fmt: skip
    finally:
        await agent.aclose()


def test_cp11_2_destructive_store_step_becomes_l2_task() -> None:
    asyncio.run(_destructive_store_step_is_l2_task())


async def _connection_scope_blocks() -> None:
    tid = _tid()
    llm = ScriptedLLM(PRINTER, [
        turn("next", "po-physical-check"),
        turn("next", "po-net-ping", reply_quote="It's on USB", connection="usb",
             connection_quote="It's on USB"),
        turn("stuck"),
    ])  # fmt: skip
    agent, run_id, out = await start(ticket(tid), llm)
    try:
        out = await answer(agent, run_id, out, {"text": "It's on USB, light on, still offline."})
        s = out.state
        assert s.handoff_reason == "steps_exhausted", s.handoff_reason
        assert "check 4" in llm.seen[-1]["feedback"] and "scope_network" in llm.seen[-1]["feedback"]
        assert _actions(run_id, tid) == []
    finally:
        await agent.aclose()


def test_cp11_2_connection_scope_blocks_network_step() -> None:
    asyncio.run(_connection_scope_blocks())


# ---- CP11.5 ----------------------------------------------------------------------------


async def _version_not_covered() -> None:
    tid = _tid()
    llm = ScriptedLLM(FROZEN, [
        turn("next", "psf-wait", version="not_covered"),
        turn("next", "psf-mouse-test", reply_quote="waited", version="not_covered"),
        turn("stuck", version="not_covered"),
    ])  # fmt: skip
    raw = ticket(tid, store_id="SW-0044", asset_id="POS-0044-T1", category="POS",
                 subject="POS touchscreen frozen", description="The POS touchscreen accepts "
                 "no input; taps and swipes produce no response.")  # fmt: skip
    agent, run_id, out = await start(raw, llm)
    try:
        assert out.paused and out.paused["kind"] == "store_reply", out.state.handoff_reason
        out = await answer(agent, run_id, out, {"text": "We waited, still frozen."})
        s = out.state
        assert s.handoff_reason == "version_not_covered" and s.status == "escalated"
        steps = [m for m in _store_messages(run_id, tid) if m[0] == "step"]
        assert len(steps) == 1 and "Wait 30 seconds" in steps[0][1]
        assert "generic_only" in llm.seen[-1]["feedback"]
        gap = rows("SELECT result FROM audit.events WHERE run_id = %s AND ticket_id = %s AND "
                   "action = 'version_not_covered'", run_id, tid)  # fmt: skip
        assert gap == [("not_covered",)]
        assert s.note_text and "not covered" in s.note_text
    finally:
        await agent.aclose()


def test_cp11_5_version_not_covered_generic_then_handoff() -> None:
    asyncio.run(_version_not_covered())
