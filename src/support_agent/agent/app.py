"""Build the running agent from `AgentSettings` (S10): clients, guards, audit, vault,
checkpointer and the per-ticket lock.

- it-data results pass the full `ResultGuard` (mask + scan); KB results only the
  vault exact match (`KbGuard`, D92); itsm results the vault exact match too.
- Audit events and the safety net write as `agent_actor`.
- The checkpointer uses schema `agent` (made by db-init, D45).
- The lock is `pg_try_advisory_lock(hashtextextended(run_id:ticket_id))` on its own
  connection, released in `finally` (S10 build step 10).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import psycopg
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from support_agent.agent.graph import Busy, build_graph, state_types
from support_agent.agent.llm import ChatClient
from support_agent.agent.observe import LangfuseTracer, NoTracer, Tracer
from support_agent.agent.runtime import Deps
from support_agent.agent.state import TicketState
from support_agent.agent.tools import KbGuard, McpToolClient, ResultGuard, TokenSource
from support_agent.common.audit import AuditEvent, awrite_event, write_event
from support_agent.common.config import AgentSettings, ClockMode
from support_agent.common.db import dsn
from support_agent.intake.masker import Masker
from support_agent.intake.moderation import (
    ModerationBudget,
    ModerationClient,
    Moderator,
)
from support_agent.intake.pipeline import process_reply
from support_agent.intake.reference import load_agent_reference
from support_agent.intake.safety_net import SafetyNet, reload_contact


@dataclass
class AdvisoryLocker:
    conninfo: str

    @asynccontextmanager
    async def hold(self, run_id: str, ticket_id: str) -> AsyncIterator[None]:
        key = f"{run_id}:{ticket_id}"
        conn = await psycopg.AsyncConnection.connect(self.conninfo, autocommit=True)
        try:
            cur = await conn.execute("SELECT pg_try_advisory_lock(hashtextextended(%s, 0))", (key,))
            row = await cur.fetchone()
            if not row or not row[0]:
                raise Busy(f"ticket {ticket_id} is already running in run {run_id}")
            try:
                yield
            finally:
                await conn.execute("SELECT pg_advisory_unlock(hashtextextended(%s, 0))", (key,))
        finally:
            await conn.close()


@dataclass
class Agent:
    app: Any
    deps: Deps
    locker: AdvisoryLocker
    saver_cm: Any
    conns: list[Any]

    async def aclose(self) -> None:
        self.deps.tracer.flush()
        await self.deps.llm.aclose()
        await self.saver_cm.__aexit__(None, None, None)
        for c in self.conns:
            r = c.close()
            if asyncio.iscoroutine(r):
                await r


def _tracer(s: AgentSettings) -> Tracer:
    if s.langfuse_public_key and s.langfuse_secret_key and s.langfuse_host:
        return LangfuseTracer(
            s.langfuse_public_key.get_secret_value(),
            s.langfuse_secret_key.get_secret_value(),
            s.langfuse_host,
        )
    return NoTracer()


async def build_agent(s: AgentSettings, *, model_alias: str | None = None) -> Agent:
    conninfo = dsn(s.database_url_agent, s.db_host)
    sync = psycopg.connect(conninfo, autocommit=True)  # safety net + moderation audit
    aconn = await psycopg.AsyncConnection.connect(conninfo, autocommit=True)
    lock = asyncio.Lock()

    def sync_audit(event: AuditEvent) -> int:
        return write_event(sync, event)

    async def audit(event: AuditEvent) -> int:
        async with lock:
            return await awrite_event(aconn, event)

    async def vault_name(ticket_id: str) -> str | None:
        async with lock:
            cur = await aconn.execute(
                "SELECT full_name FROM pii.vault WHERE ticket_id = %s", (ticket_id,)
            )
            row = await cur.fetchone()
        return str(row[0]) if row and row[0] else None

    reference = load_agent_reference(sync)
    masker = Masker(reference)
    net = SafetyNet(reference, sync_audit, actor="agent-actor")
    issuer = s.keycloak_issuer
    reader = TokenSource(issuer, "agent-reader", s.keycloak_secret_agent_reader.get_secret_value())
    actor = TokenSource(issuer, "agent-actor", s.keycloak_secret_agent_actor.get_secret_value())
    key = s.litellm_master_key.get_secret_value()
    alias = model_alias or s.model_agent
    moderator = Moderator(
        ModerationClient(s.litellm_base_url, key, model=s.model_moderation), net, sync_audit,
        actor="agent-actor",
    )  # fmt: skip

    async def moderate_reply(state: TicketState, text: str) -> tuple[str, str]:
        tid = state.ticket.ticket_id

        def work() -> tuple[str, str]:
            reload_contact(sync, tid)
            row = sync.execute(
                "SELECT mask_map FROM pii.vault WHERE ticket_id = %s", (tid,)
            ).fetchone()
            reply = process_reply(
                tid, text, masker, dict(row[0]) if row and row[0] else {}, safety_net=net,
                moderator=moderator, budget=ModerationBudget(s.moderation_max_calls),
            )  # fmt: skip
            mod = reply.moderation
            if mod is None or mod.failed:
                return reply.text, "failed"
            return reply.text, mod.label.value

        return await asyncio.to_thread(work)

    deps = Deps(
        llm=ChatClient(s.litellm_base_url, key, model=alias),
        it_data=McpToolClient(s.it_data_url, reader, ResultGuard(masker, net)),
        knowledge=McpToolClient(s.knowledge_url, reader, KbGuard(net)),
        itsm=McpToolClient(s.itsm_url, actor, KbGuard(net)),
        safety_net=net,
        audit=audit,
        vault_name=vault_name,
        tracer=_tracer(s),
        llm_max_calls=s.llm_max_calls,
        token_budget=s.token_budget_per_ticket,
        triage_max_tool_calls=s.triage_max_tool_calls,
        confidence_min=s.confidence_min,
        model_alias=alias,
        moderate_reply=moderate_reply,
        replay_reply_delay_min=(
            s.replay_reply_delay_min if s.clock_mode == ClockMode.REPLAY else 0.0
        ),
    )
    saver_cm = AsyncPostgresSaver.from_conn_string(
        conninfo + ("&" if "?" in conninfo else "?") + "options=-csearch_path%3Dagent",
        serde=JsonPlusSerializer(allowed_msgpack_modules=state_types()),
    )
    saver = await saver_cm.__aenter__()
    return Agent(build_graph(deps, saver), deps, AdvisoryLocker(conninfo), saver_cm, [sync, aconn])
