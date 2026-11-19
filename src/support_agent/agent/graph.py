"""The agent graph (S10 build step 1, S11; agent-architecture.md, Overall flow).

    open ─► enrich ─► triage ─► policy ─┬─► resolver ⇄ dispatch ⇄ wait_walk ⏸ (S11)
     │                                  │     ├─ fixed ─► finish ───────────┐
     │                                  │     └─ stuck ─► handoff ──────────┤
     │                                  ├─► handoff ────────────────────┤
     │                                  ├─► l1_pack ────────────────────┤─► communicate ─► END
     │                                  ├─► redirect ───────────────────┤        │
     │                                  └─► clarify ────────────────────┘        ▼ (question sent)
     └─ threat / forbidden / failed ─► handoff;  off_topic ─► redirect      wait ⏸ ─► triage

- `thread_id = f"{run_id}:{ticket_id}"` (D45); the Postgres checkpointer lives in
  schema `agent`.
- `open` writes the itsm ticket right after intake (review M11) and applies the
  moderation behaviour of the intake label (S10 build step 3).
- Any node failure sets `failed_node` and the next edge goes to Handoff.
- `run_ticket()` and `resume(run_id, ticket_id, pending_id, kind, payload)` hold
  the per-ticket advisory lock; `resume` clears the pending item first with the
  atomic compare-and-clear (D53), so a stale or losing call is `WrongState` and
  nothing in state changes.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Protocol

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from support_agent.agent.messages import person_will_contact, refusal
from support_agent.agent.nodes.clarify import clarify_node, wait_answer_node
from support_agent.agent.nodes.communicate import communicate_node
from support_agent.agent.nodes.enrich import enrich
from support_agent.agent.nodes.handoff import handoff_node
from support_agent.agent.nodes.l1_pack import l1_pack_node
from support_agent.agent.nodes.policy import policy
from support_agent.agent.nodes.redirect import redirect_node
from support_agent.agent.nodes.resolver import (
    dispatch_node,
    finish_node,
    resolver_node,
    wait_walk_node,
)
from support_agent.agent.nodes.router import route
from support_agent.agent.nodes.triage import TriageDeps, triage
from support_agent.agent.runtime import Deps, NodeCtx, WrongState, wrap
from support_agent.agent.state import HandoffReason, StoreDraft, TicketState
from support_agent.agent.tools import ToolCallError
from support_agent.mcp.base.errors import ErrorCode

# Types the checkpointer may deserialize (LangGraph msgpack allow-list).
STATE_MODULES = (
    "support_agent.agent.state",
    "support_agent.intake.schema",
    "support_agent.mcp.it_data.models",
)


def state_types() -> list[tuple[str, str]]:
    """(module, class) of every model and enum the state can hold."""
    import enum
    import importlib
    import inspect

    from pydantic import BaseModel

    out = []
    for name in STATE_MODULES:
        module = importlib.import_module(name)
        for cls_name, cls in inspect.getmembers(module, inspect.isclass):
            if cls.__module__ == name and issubclass(cls, BaseModel | enum.Enum):
                out.append((name, cls_name))
    return out


# ---- nodes over the S8 functions -------------------------------------------------------


async def open_node(state: TicketState, ctx: NodeCtx) -> dict[str, Any]:
    t = state.ticket
    await ctx.itsm.call(
        "create_ticket", "open", "create", date_opened=t.date_opened.isoformat(),
        asset_id=t.asset_id, priority=t.priority, category=t.category,
        clock_offset_s=state.clock_offset_s, submitted_by_user=state.submitted_by_user,
        source_ticket_id=state.source_ticket_id,
    )  # fmt: skip
    label = state.moderation_label
    if label in ("threat", "forbidden", "failed"):
        text = refusal(t.ticket_id) if label == "forbidden" else person_will_contact(t.ticket_id)
        return {
            "handoff_reason": "moderation",
            "drafts": [StoreDraft(kind="status_template", text=text)],
            "_result": "handoff",
            "_audit_reason": f"moderation:{label}",
        }
    return {"abuse_count": int(label == "abusive"), "_result": label}


async def enrich_node(state: TicketState, ctx: NodeCtx) -> dict[str, Any]:
    facts = await enrich(state.ticket, ctx.it_data)
    return {"facts": facts, "_audit": {"flags": [str(f) for f in facts.flags]}}


async def triage_node(state: TicketState, ctx: NodeCtx) -> dict[str, Any]:
    if state.facts is None:
        raise RuntimeError("triage before enrich")
    tid = state.ticket.ticket_id
    deps = TriageDeps(
        llm=ctx.deps.llm,
        kb=ctx.kb,
        it_data=ctx.it_data,
        budget=ctx.budget,
        sop=ctx.deps.sop,
        max_tool_calls=ctx.deps.triage_max_tool_calls,
        # Inputs were checked where they came in; the whole prompt gets the vault match (D111).
        scan_prompt=lambda fixed, data: ctx.deps.safety_net.scan_vault(
            fixed + "\n" + data, tid, "prompt"
        ),
        run_id=ctx.run_id,
    )
    result = await triage(state.ticket, state.facts, deps)
    out = result.output
    return {
        "triage": result,
        "_result": out.route if out else "failed",
        "_audit_reason": result.handoff_reason,
        "_audit": {
            "runbook_id": out.runbook_id if out else None,
            "cited": result.cited_runbook,
            "quote_check": result.quote_check,
            "tool_calls": result.tool_calls,
            "redirect_to": out.redirect_to if out else None,
            "missing_fact": out.missing_fact if out else None,
        },
    }


def _route_reason(state: TicketState, rule: int, sla_passed: bool) -> HandoffReason | None:
    p = state.policy
    if p is None:
        return None
    if rule == 1:
        return p.handoff_reason or ("sla_breach" if sla_passed else "l2_needed")
    if rule == 2:
        return "unknown_system"
    if rule == 5:
        return "still_vague"
    if rule == 8:
        return "sop_trigger" if p.escalate_now else "l2_needed"
    return None


async def policy_node(state: TicketState, ctx: NodeCtx) -> dict[str, Any]:
    if state.facts is None or state.triage is None:
        raise RuntimeError("policy before triage")
    pol = policy(state.ticket, state.facts, state.triage, confidence_min=ctx.deps.confidence_min)
    now = ctx.now()
    dec = route(state.triage, pol, clarify_count=state.clarify_count, now=now)
    after = state.model_copy(update={"policy": pol})
    reason = _route_reason(after, dec.rule, now > pol.sla.escalate_by)
    return {
        "policy": pol,
        "route": dec,
        "handoff_reason": reason if dec.route in ("handoff", "human") else None,
        "_result": dec.route,
        "_audit_reason": reason,
        "_audit": {"rule": dec.rule, "priority": pol.priority, "rules_fired": pol.rules_fired},
    }


# ---- edges -----------------------------------------------------------------------------


def after_open(state: TicketState) -> str:
    if state.failed_node or state.handoff_reason:
        return "handoff"
    return "redirect" if state.moderation_label == "off_topic" else "enrich"


def ok_or_handoff(next_node: str) -> Any:
    def edge(state: TicketState) -> str:
        return "handoff" if state.failed_node else next_node

    edge.__name__ = f"to_{next_node}"
    return edge


def after_policy(state: TicketState) -> str:
    if state.failed_node or state.route is None:
        return "handoff"
    return {"human": "handoff"}.get(state.route.route, state.route.route)


def after_resolver(state: TicketState) -> str:
    walk = state.walk
    if state.failed_node or state.handoff_reason or walk is None:
        return "handoff"
    if walk.end == "fixed":
        return "finish"
    return "dispatch" if walk.proposal else "handoff"


def after_dispatch(state: TicketState) -> str:
    if state.failed_node or state.handoff_reason or state.walk is None:
        return "handoff"
    return "wait_walk" if state.walk.waiting else "resolver"


def after_wait_walk(state: TicketState) -> str:
    if state.failed_node or state.handoff_reason or state.walk is None:
        return "handoff"
    return "dispatch" if state.walk.last_event == "approval_void" else "resolver"


def after_communicate(state: TicketState) -> str:
    return "wait" if state.status == "waiting_store" and not state.failed_node else END


def after_wait(state: TicketState) -> str:
    return "handoff" if state.failed_node or state.handoff_reason else "triage"


def build_graph(deps: Deps, checkpointer: BaseCheckpointSaver[Any] | None = None) -> Any:
    g: StateGraph[TicketState] = StateGraph(TicketState)
    nodes = {
        "open": open_node, "enrich": enrich_node, "triage": triage_node, "policy": policy_node,
        "resolver": resolver_node, "dispatch": dispatch_node, "wait_walk": wait_walk_node,
        "finish": finish_node, "handoff": handoff_node, "l1_pack": l1_pack_node,
        "redirect": redirect_node, "clarify": clarify_node, "communicate": communicate_node,
        "wait": wait_answer_node,
    }  # fmt: skip
    for name, fn in nodes.items():
        g.add_node(name, wrap(name, fn, deps))  # type: ignore[call-overload]
    g.add_edge(START, "open")
    g.add_conditional_edges("open", after_open, ["handoff", "redirect", "enrich"])
    g.add_conditional_edges("enrich", ok_or_handoff("triage"), ["handoff", "triage"])
    g.add_conditional_edges("triage", ok_or_handoff("policy"), ["handoff", "policy"])
    g.add_conditional_edges(
        "policy", after_policy, ["handoff", "resolver", "l1_pack", "redirect", "clarify"]
    )
    g.add_conditional_edges("resolver", after_resolver, ["handoff", "finish", "dispatch"])
    g.add_conditional_edges("dispatch", after_dispatch, ["handoff", "wait_walk", "resolver"])
    g.add_conditional_edges("wait_walk", after_wait_walk, ["handoff", "dispatch", "resolver"])
    g.add_conditional_edges("finish", ok_or_handoff("communicate"), ["handoff", "communicate"])
    for name in ("l1_pack", "redirect", "clarify"):
        g.add_conditional_edges(name, ok_or_handoff("communicate"), ["handoff", "communicate"])
    g.add_edge("handoff", "communicate")
    g.add_conditional_edges("communicate", after_communicate, ["wait", END])
    g.add_conditional_edges("wait", after_wait, ["handoff", "triage"])
    return g.compile(checkpointer=checkpointer)


# ---- running ---------------------------------------------------------------------------


class Locker(Protocol):
    def hold(self, run_id: str, ticket_id: str) -> Any: ...


class Busy(WrongState):
    """The ticket is running now: the API maps it to 409, like any lost race (D53)."""


@dataclass
class RunOutcome:
    state: TicketState
    paused: dict[str, Any] | None  # the interrupt value: pending_id, kind


RECURSION_LIMIT = 200  # a walk loops resolver -> dispatch -> wait_walk per step


def thread(run_id: str, ticket_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": f"{run_id}:{ticket_id}"},
            "recursion_limit": RECURSION_LIMIT}  # fmt: skip


@asynccontextmanager
async def _noop_lock(run_id: str, ticket_id: str) -> AsyncIterator[None]:
    yield


async def _outcome(app: Any, cfg: dict[str, Any], result: dict[str, Any]) -> RunOutcome:
    snap = await app.aget_state(cfg)
    state = TicketState.model_validate(snap.values)
    interrupts = result.get("__interrupt__") or []
    return RunOutcome(state, dict(interrupts[0].value) if interrupts else None)


async def run_ticket(app: Any, state: TicketState, *, locker: Locker | None = None) -> RunOutcome:
    cfg = thread(state.run_id, state.ticket.ticket_id)
    if (await app.aget_state(cfg)).values:
        raise WrongState(f"ticket {state.ticket.ticket_id} already ran in run {state.run_id}")
    lock = locker.hold(state.run_id, state.ticket.ticket_id) if locker else _noop_lock("", "")
    async with lock:
        result = await app.ainvoke(state, cfg)
    return await _outcome(app, cfg, result)


async def claim(
    app: Any,
    deps: Deps,
    run_id: str,
    ticket_id: str,
    pending_id: str,
    kind: str,
    *,
    idem_step: str | None = None,
) -> None:
    """The compare-and-clear of one pause (D53), without running the graph. The caller
    holds the ticket lock. A stale `pending_id`, a wrong kind or a lost race is
    `WrongState` and changes nothing. The API claims before its 202 (S12), so a stale
    or losing call gets 409 at once; `continue_run` then runs in the background."""
    cfg = thread(run_id, ticket_id)
    snap = await app.aget_state(cfg)
    if not snap.values or not snap.next:
        raise WrongState("no paused run for this ticket")
    state = TicketState.model_validate(snap.values)
    from support_agent.agent.runtime import Itsm

    itsm = Itsm(deps.itsm, uuid.UUID(run_id), ticket_id, state.ticket.store_id)
    try:
        await itsm.call(
            "clear_pending", "resume",
            idem_step or f"{pending_id}:{kind}:{uuid.uuid4().hex[:8]}",
            pending_id=pending_id, kind=kind,
        )  # fmt: skip
    except ToolCallError as exc:
        if exc.code in (ErrorCode.CONFLICT, ErrorCode.INVALID):
            raise WrongState(exc.reason) from None
        raise


async def continue_run(
    app: Any, run_id: str, ticket_id: str, kind: str, payload: dict[str, Any]
) -> RunOutcome:
    """Resume the graph after a won `claim` (the caller still holds the lock)."""
    cfg = thread(run_id, ticket_id)
    value = {"timeout": True} if kind == "timeout" else payload
    result = await app.ainvoke(Command(resume=value), cfg)
    return await _outcome(app, cfg, result)


async def resume(
    app: Any,
    deps: Deps,
    run_id: str,
    ticket_id: str,
    pending_id: str,
    kind: str,
    payload: dict[str, Any],
    *,
    locker: Locker | None = None,
    idem_step: str | None = None,
) -> RunOutcome:
    """One contract for every pause (D53): lock, `claim`, `continue_run`. The
    compare-and-clear decides the winner; a stale call, a wrong kind or a lost race is
    `WrongState` and changes nothing. `kind="timeout"` (the SLA timer) clears a pause
    of any kind and resumes with `{"timeout": True}`; `idem_step` names its key
    (`sla_breach`)."""
    lock = locker.hold(run_id, ticket_id) if locker else _noop_lock("", "")
    async with lock:
        await claim(app, deps, run_id, ticket_id, pending_id, kind, idem_step=idem_step)
        return await continue_run(app, run_id, ticket_id, kind, payload)
