"""Scripted Resolver walks against the running platform (S11; mock values only, D70).

`ScriptedLLM` stands in for the model: Triage gets a fixed verdict citing the
ticket's runbook, each Resolver turn is the next scripted `ResolverTurn` (a
function of the turn's data, so a script can react), and the L2 note write fails
so the code-built fallback note is used. Everything else is real: intake,
it-data, knowledge, itsm-actions, OPA, the checkpointer and the audit.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg

from support_agent.agent.app import Agent, build_agent
from support_agent.agent.graph import RunOutcome, resume, run_ticket
from support_agent.agent.llm import ChatClient, Reply, TicketBudget
from support_agent.cli.ticket_local import initial_state, intake
from support_agent.common.config import AgentSettings, get_settings
from tests.integration.platform_env import load_env, superuser_url

Turn = dict[str, Any] | Callable[[dict[str, Any]], dict[str, Any]]

RUNBOOK_EVIDENCE = {
    "runbooks/printer-offline.md": (
        "runbooks/printer-offline.md#symptoms",
        'Printer shows "Offline" status in ServeWell POS system',
    ),
    "runbooks/pos-screen-frozen.md": (
        "runbooks/pos-screen-frozen.md#symptoms",
        "Touchscreen accepts no input; taps and swipes produce no response",
    ),
}


def turn(
    decision: str,
    step_id: str | None = None,
    *,
    reply_quote: str | None = None,
    tried: list[tuple[str, str]] | None = None,
    connection: str = "unknown",
    connection_quote: str | None = None,
    version: str = "covered",
    reason: str = "scripted",
) -> dict[str, Any]:
    return {
        "decision": decision, "step_id": step_id, "reply_quote": reply_quote,
        "tried": [{"step_id": s, "quote": q} for s, q in (tried or [])],
        "connection": connection, "connection_quote": connection_quote,
        "version_covered": version, "version_quote": None, "escalate_quote": None,
        "reason": reason,
    }  # fmt: skip


def triage_verdict(runbook_id: str, category: str, device: str) -> dict[str, Any]:
    section, quote = RUNBOOK_EVIDENCE[runbook_id]
    return {
        "real_category": category, "real_device": device, "trick_flags": [],
        "runbook_id": runbook_id, "runbook_evidence": {"section_id": section, "quote": quote},
        "sop_triggers": [], "doc_conflicts": [], "route": "l1_guided", "redirect_to": None,
        "missing_fact": None, "reason": "scripted triage", "confidence": 0.9,
    }  # fmt: skip


class ScriptedLLM(ChatClient):
    def __init__(self, triage: dict[str, Any], turns: list[Turn]) -> None:
        super().__init__("http://127.0.0.1:9", "unused")
        self.triage, self.turns = triage, list(turns)
        self.seen: list[dict[str, Any]] = []  # each Resolver turn's data

    async def complete(  # type: ignore[override]
        self, messages: list[dict[str, Any]], budget: TicketBudget, **kw: Any
    ) -> Reply:
        budget.check()
        budget.calls += 1
        budget.tokens += 100
        tools = kw.get("tools") or []
        if any(t["function"]["name"] == "submit_triage" for t in tools):
            call = {
                "id": "c1",
                "type": "function",
                "function": {"name": "submit_triage", "arguments": json.dumps(self.triage)},
            }
            return Reply(message={"role": "assistant", "content": None, "tool_calls": [call]})
        name = ((kw.get("response_format") or {}).get("json_schema") or {}).get("name")
        if name == "resolver_turn":
            text = messages[-1]["content"]
            body = text[text.index("<data>") + 6 : text.index("</data>")]
            data = json.loads(body)
            data["feedback"] = text[text.index("</data>") + 7 :]
            self.seen.append(data)
            if not self.turns:
                return Reply(message={"content": json.dumps(turn("stuck", reason="script end"))})
            nxt = self.turns.pop(0)
            out = nxt(data) if callable(nxt) else nxt
            return Reply(message={"content": json.dumps(out)})
        return Reply(message={"content": "{}"})  # L2 note / L1 pack: invalid -> fallback


def ticket(
    ticket_id: str,
    *,
    store_id: str = "SW-0003",
    asset_id: str = "PRN-0003-P1",
    category: str = "Printers",
    subject: str = "Receipt printer shows offline",
    description: str = (
        "Receipt printer at the front counter shows Offline in the POS since this morning. "
        "Print jobs queue but nothing comes out."
    ),
    opened: datetime | None = None,
    priority: str = "P3",
) -> dict[str, Any]:
    when = opened or datetime(2026, 3, 10, 4, 0, tzinfo=UTC)
    return {
        "store_id": store_id, "store_name": "ServeWell - Mock", "date_opened": when.isoformat(),
        "submitted_by": "Testa Mockwell", "contact_phone": "+91-90000-00001",
        "priority": priority, "ticket_id": ticket_id, "category": category,
        "asset_id": asset_id, "system_version": None, "subject": subject,
        "description": description,
    }  # fmt: skip


async def start(
    raw: dict[str, Any],
    llm: ChatClient | None,
    *,
    run_id: str | None = None,
    agent: Agent | None = None,
) -> tuple[Agent, str, RunOutcome]:
    result = intake(raw)
    agent = agent or await build_agent(get_settings(AgentSettings))
    if llm is not None:
        agent.deps.llm = llm
    run_id = run_id or str(uuid.uuid4())
    out = await run_ticket(agent.app, initial_state(result, run_id), locker=agent.locker)
    return agent, run_id, out


async def answer(agent: Agent, run_id: str, out: RunOutcome, payload: dict[str, Any]) -> RunOutcome:
    if out.paused is None:
        raise AssertionError(f"not paused: {out.state.status} {out.state.handoff_reason}")
    return await resume(
        agent.app, agent.deps, run_id, out.state.ticket.ticket_id,
        str(out.paused["pending_id"]), str(out.paused["kind"]), payload, locker=agent.locker,
    )  # fmt: skip


def db() -> psycopg.Connection[Any]:
    return psycopg.connect(superuser_url(load_env()), autocommit=True)


def rows(sql: str, *args: Any) -> list[tuple[Any, ...]]:
    with db() as c:
        return c.execute(sql, args).fetchall()


def reset_autonomy(action_id: str, model: str) -> None:
    with db() as c:
        c.execute(
            "UPDATE itsm.action_autonomy SET state = 'supervised', runs_in_a_row = 0, "
            "why = 'test reset' WHERE action_id = %s AND device_model = %s",
            (action_id, model),
        )


def shift_wall(agent: Agent, minutes: float) -> None:
    agent.deps.wall = lambda: datetime.now(UTC) + timedelta(minutes=minutes)
