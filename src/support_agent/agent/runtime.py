"""Node runtime: dependencies, per-node context and the `@node` wrapper (S10 build step 2).

Every graph node is `async def fn(state, ctx) -> dict` wrapped by `wrap(name, fn, deps)`:

- A Langfuse span per node (trace id from `run_id:ticket_id`); input and output are
  the masked state summary only (review M3).
- LLM calls, tokens and cost are carried in state; `TicketBudget` is rebuilt from
  state for each node, so the caps hold across a resume in another process.
  Over `LLM_MAX_CALLS` or `TOKEN_BUDGET_PER_TICKET` -> HANDOFF (`budget_exceeded`).
- Retries with backoff live in the clients (LLM: `ChatClient`; MCP: `McpToolClient`).
  A failure that outlasts them becomes HANDOFF with a D57 reason code; Handoff and
  Communicate never hand off again (Handoff falls back to the code-built note).
- The audit event is written before the node's result is accepted; an audit
  failure fails the node (D9).
- A LangGraph interrupt passes through untouched (the pause is not a failure).
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from langgraph.errors import GraphBubbleUp

from support_agent.agent.bindings import Bindings, default_bindings
from support_agent.agent.gate import Gate, GateOutput, GateResult
from support_agent.agent.llm import (
    BudgetExceeded,
    ChatClient,
    InvalidOutput,
    LlmUnavailable,
    TicketBudget,
)
from support_agent.agent.messages import catalogue, template
from support_agent.agent.nodes.triage import SopCache
from support_agent.agent.observe import HANDOFFS, LLM_CALLS, NODE_LATENCY, NODE_RESULTS, Tracer
from support_agent.agent.state import HandoffReason, TicketState
from support_agent.agent.tools import ItDataClient, KnowledgeClient, McpToolClient, ToolCallError
from support_agent.common.audit import AuditEvent
from support_agent.intake.safety_net import PIIBlocked, SafetyNet
from support_agent.mcp.base.errors import ErrorCode
from support_agent.mcp.itsm.registry import Registry, default_registry
from support_agent.mcp.knowledge.models import GetDocumentResult

ACTOR = "agent-actor"
# Nodes that never hand off again: they are the handoff path.
TERMINAL = frozenset({"handoff", "communicate"})


class GateBlocked(RuntimeError):  # noqa: N818 - a handoff signal
    def __init__(self, result: GateResult) -> None:
        super().__init__(f"gate check {result.check}: {result.reason}")
        self.result = result


class WrongState(RuntimeError):  # noqa: N818 - the API maps it to 409 (D53)
    pass


def reason_for(exc: BaseException) -> HandoffReason:
    if isinstance(exc, BudgetExceeded):
        return "budget_exceeded"
    if isinstance(exc, LlmUnavailable):
        return "llm_unavailable"
    if isinstance(exc, PIIBlocked | GateBlocked):
        return "gate_block"
    if isinstance(exc, InvalidOutput):
        return "invalid_output"
    return "tool_error"


# ---- dependencies ----------------------------------------------------------------------


class AuditSink(Protocol):
    async def __call__(self, event: AuditEvent) -> int: ...


class VaultReader(Protocol):
    async def __call__(self, ticket_id: str) -> str | None: ...


class KbSections:
    """Section ids of every KB document seen found in this process, per kb_rev, for
    gate check 7 without a second (budget-charged) fetch."""

    def __init__(self) -> None:
        self.docs: dict[tuple[str | None, str], frozenset[str]] = {}

    def record(self, result: GetDocumentResult) -> None:
        doc = result.document
        if result.status == "found" and doc is not None:
            self.docs[(result.kb_rev, doc.doc_id)] = frozenset(s.section_id for s in doc.sections)

    def lookup(self, kb_rev: str | None, doc_id: str) -> frozenset[str] | None:
        return self.docs.get((kb_rev, doc_id))


class RecordingKnowledge(KnowledgeClient):
    """KnowledgeClient that remembers the sections of every document it fetched."""

    def __init__(self, client: McpToolClient, sections: KbSections, **kw: Any) -> None:
        super().__init__(client, **kw)
        self.sections = sections

    async def get_document(self, doc_id: str) -> GetDocumentResult:
        result = await super().get_document(doc_id)
        self.sections.record(result)
        return result


@dataclass
class Deps:
    llm: ChatClient
    it_data: McpToolClient
    knowledge: McpToolClient
    itsm: McpToolClient
    safety_net: SafetyNet
    audit: AuditSink
    vault_name: VaultReader
    tracer: Tracer
    sop: SopCache = field(default_factory=SopCache)
    sections: KbSections = field(default_factory=KbSections)
    llm_max_calls: int = 15
    token_budget: int = 120_000
    triage_max_tool_calls: int = 6
    confidence_min: float = 0.5
    model_alias: str = "agent"
    # Moderation of store replies and the masker for them (Clarify answers).
    moderate_reply: Callable[[TicketState, str], Awaitable[tuple[str, str]]] | None = None
    wall: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    # Resolver walk (S11): approved steps, the action registry (data), and the replay
    # clock's simulated store-reply delay (0 in live mode, D48).
    bindings: Bindings = field(default_factory=default_bindings)
    registry: Registry = field(default_factory=default_registry)
    replay_reply_delay_min: float = 0.0

    def curated_words(self) -> str:
        """Our own fixed text (templates, approved steps, registry results), for gate 5."""
        results = "\n".join(
            f"{a.description}\n{a.simulated_result.text}" for a in self.registry.actions
        )
        return "\n".join((catalogue(), self.bindings.words(), results))


class Itsm:
    """itsm-actions calls bound to (run, ticket, store) in `_meta` (D84), each with its
    idem key `<run_id>:<ticket_id>:<node>:<step>` (D45)."""

    def __init__(self, client: McpToolClient, run_id: uuid.UUID, ticket_id: str, store_id: str):
        self.client, self.run_id, self.ticket_id, self.store_id = (
            client,
            run_id,
            ticket_id,
            store_id,
        )

    def key(self, node: str, step: str) -> str:
        return f"{self.run_id}:{self.ticket_id}:{node}:{step}"

    async def call(self, tool: str, node: str, step: str, **args: Any) -> dict[str, Any]:
        body = {k: v for k, v in args.items() if v is not None}
        body["idem_key"] = self.key(node, step)
        return await self.client.call(
            tool, body, ticket_id=self.ticket_id, run_id=self.run_id, store_id=self.store_id
        )


@dataclass
class NodeCtx:
    deps: Deps
    run_id: uuid.UUID
    budget: TicketBudget
    it_data: ItDataClient
    kb: RecordingKnowledge
    itsm: Itsm
    gate: Gate
    clock_offset: timedelta

    def now(self) -> datetime:
        """Ticket time (D48): wall clock plus the replay offset."""
        return self.deps.wall() + self.clock_offset

    async def check(self, output: GateOutput, ticket_id: str) -> GateResult:
        return await self.gate.check(output, ticket_id)


def make_ctx(deps: Deps, state: TicketState, kb_rev: str | None) -> NodeCtx:
    run_id = uuid.UUID(state.run_id)
    t = state.ticket
    kb = RecordingKnowledge(deps.knowledge, deps.sections, ticket_id=t.ticket_id, run_id=run_id)

    async def kb_exists(doc_id: str, section_id: str | None) -> bool:
        known = deps.sections.lookup(kb_rev, doc_id)
        if known is None:
            result = await kb.get_document(doc_id)
            if result.status != "found" or (kb_rev and result.kb_rev != kb_rev):
                return False
            known = deps.sections.lookup(result.kb_rev, doc_id) or frozenset()
        return section_id is None or section_id in known

    return NodeCtx(
        deps=deps,
        run_id=run_id,
        budget=TicketBudget(
            deps.llm_max_calls,
            deps.token_budget,
            calls=state.llm_calls,
            tokens=state.tokens,
            cost_usd=state.cost_usd,
        ),
        it_data=ItDataClient(deps.it_data, ticket_id=t.ticket_id, run_id=run_id),
        kb=kb,
        itsm=Itsm(deps.itsm, run_id, t.ticket_id, t.store_id),
        gate=Gate(deps.safety_net, kb_exists, template, deps.curated_words()),
        clock_offset=timedelta(seconds=state.clock_offset_s),
    )


def summary(state: TicketState) -> dict[str, Any]:
    """The masked state a span may show: ids, route and reasons, never text or vault values."""
    out = state.triage.output if state.triage else None
    return {
        "ticket_id": state.ticket.ticket_id,
        "run_id": state.run_id,
        "category": state.ticket.category,
        "moderation": state.moderation_label,
        "triage_route": out.route if out else None,
        "runbook_id": out.runbook_id if out else None,
        "route": state.route.route if state.route else None,
        "rule": state.route.rule if state.route else None,
        "priority": state.policy.priority if state.policy else None,
        "handoff_reason": state.handoff_reason,
        "status": state.status,
        "clarify_count": state.clarify_count,
        "llm_calls": state.llm_calls,
        "tokens": state.tokens,
    }


NodeFn = Callable[[TicketState, NodeCtx], Awaitable[dict[str, Any]]]


def wrap(name: str, fn: NodeFn, deps: Deps) -> Callable[[TicketState], Awaitable[dict[str, Any]]]:
    async def run(state: TicketState) -> dict[str, Any]:
        kb_rev = state.triage.kb_rev if state.triage else None
        ctx = make_ctx(deps, state, kb_rev)
        calls_before, tokens_before, cost_before = state.llm_calls, state.tokens, state.cost_usd
        started = time.monotonic()
        reason: HandoffReason | None = None
        error: str | None = None
        with deps.tracer.span(state.run_id, state.ticket.ticket_id, name, summary(state)) as span:
            try:
                update = await fn(state, ctx)
                result = "ok"
            except GraphBubbleUp:  # an interrupt (pause), not a failure
                raise
            except Exception as exc:
                if name in TERMINAL:
                    span.end_with({"error": type(exc).__name__}, level="ERROR")
                    raise
                reason = reason_for(exc)
                error = f"{type(exc).__name__}: {exc}"[:300]
                if isinstance(exc, ToolCallError) and exc.code == ErrorCode.DENIED:
                    error = f"denied: {exc.tool}: {exc.reason}"[:300]
                update = {"handoff_reason": reason, "failed_node": name}
                result = "handoff"
            calls = ctx.budget.calls - calls_before
            if calls:
                span.generation(
                    model=deps.model_alias,
                    calls=calls,
                    tokens=ctx.budget.tokens - tokens_before,
                    cost_usd=ctx.budget.cost_usd - cost_before,
                    prompt=update.pop("_prompt", None),
                )
            update.pop("_prompt", None)
            audit_reason = (
                update.pop("_audit_reason", None) or reason or update.get("handoff_reason")
            )
            payload = update.pop("_audit", {})
            update |= {
                "llm_calls": ctx.budget.calls,
                "tokens": ctx.budget.tokens,
                "cost_usd": ctx.budget.cost_usd,
            }
            after = state.model_copy(
                update={k: v for k, v in update.items() if not k.startswith("_")}
            )
            span.end_with(summary(after), level="WARNING" if result == "handoff" else None)
        # Audit before the result is accepted; a failed write fails the node (D9).
        audit_id = await deps.audit(
            AuditEvent(
                step="agent",
                actor=ACTOR,
                action=name,
                result=result if result != "ok" else str(update.get("_result", "ok")),
                run_id=ctx.run_id,
                ticket_id=state.ticket.ticket_id,
                reason=audit_reason,
                source="graph",
                kb_rev=after.triage.kb_rev if after.triage else None,
                payload={**payload, **({"error": error} if error else {}), "llm_calls": calls},
            )
        )
        update.pop("_result", None)
        update["audit_ids"] = [*state.audit_ids, audit_id]
        NODE_LATENCY.labels(name).observe(time.monotonic() - started)
        NODE_RESULTS.labels(name, result).inc()
        if calls:
            LLM_CALLS.labels(name).inc(calls)
        if reason:
            HANDOFFS.labels(reason).inc()
        return update

    run.__name__ = name
    return run
