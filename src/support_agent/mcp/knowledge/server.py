"""knowledge MCP server: retrieval only, over the current KB revision (S6 step 5).

Run: `python -m support_agent.mcp.knowledge` (container `knowledge`, port 8102, role
`knowledge_ro`). Tools:
- `search_kb`, `get_document` (scope `kb:read`, agent-reader);
- `register_exclusions`, `is_excluded` (scope `kb:eval`, eval-runner only; OPA P7).

The run and ticket come from the request `_meta` (`current_call()`), so the agent
can never set or read an exclusion, and the per-run KB-text budget follows the run.
`get_runbook_steps` joins in S9.
"""

from __future__ import annotations

import math
from typing import Any

import httpx
from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from support_agent.common.config import KnowledgeSettings
from support_agent.common.db import dsn
from support_agent.kb.embed import aembed_one
from support_agent.mcp.base.auth import JwtVerifier
from support_agent.mcp.base.errors import ErrorCode, ToolFailure
from support_agent.mcp.base.opa import OpaClient
from support_agent.mcp.base.server import McpService, Policy, current_call
from support_agent.mcp.knowledge import search
from support_agent.mcp.knowledge.models import (
    CodeSection,
    Document,
    DocumentHit,
    GetDocumentIn,
    GetDocumentResult,
    IsExcludedIn,
    IsExcludedResult,
    RegisterExclusionsIn,
    RegisterExclusionsResult,
    SearchKbIn,
    SearchKbResult,
    SectionHit,
    SectionRef,
)
from support_agent.mcp.knowledge.state import Store, ValkeyStore, budget_key

NAME = "knowledge"
POLICY_PREFIX = "knowledge"
SCOPE_READ = "kb:read"
SCOPE_EVAL = "kb:eval"
EVAL_CLIENT = "eval-runner"

Conn = AsyncConnection[Any]
QueryEmbedder = Any  # async (text) -> list[float]


def kb_tokens(text: str) -> int:
    """KB-text budget unit: about 4 characters per token (the budget is approximate)."""
    return math.ceil(len(text) / 4)


class Knowledge:
    def __init__(self, store: Store, embed_query: QueryEmbedder, budget: int) -> None:
        self.store, self.embed_query, self.budget = store, embed_query, budget

    async def excluded(self) -> tuple[str, ...]:
        run_id = current_call().run_id
        if run_id is None:
            return ()
        return tuple(sorted(await self.store.exclusions(run_id)))

    async def charge(self, tokens: int) -> tuple[bool, int]:
        """(allowed, used after this call). Over budget: nothing is charged."""
        ctx = current_call()
        key = budget_key(ctx.run_id, ctx.ticket_id)
        if key is None:
            return True, tokens
        used = await self.store.get_budget(key)
        if used + tokens > self.budget:
            return False, used
        return True, await self.store.incr_budget(key, tokens)


def register(service: McpService, kn: Knowledge) -> None:
    @service.tool(scope=SCOPE_READ)
    async def search_kb(args: SearchKbIn, conn: Conn) -> SearchKbResult:
        """Hybrid BM25 + vector search over KB sections, rolled up to documents. Filter by
        doc_type, device_family (only when the device is established) and category.
        Returns documents with score, best sections (id, parent id, path, snippet),
        and truncated flag."""
        filters = search.Filters(
            args.doc_type, args.device_family, args.category, await kn.excluded()
        )
        vector = await kn.embed_query(args.query)
        ranked = await search.rank(conn, args.query, filters, k=args.k, vector=vector)
        if not ranked.documents and not ranked.code_sections:
            return SearchKbResult(status="none", kb_rev=ranked.kb_rev, codes=ranked.codes)
        ids = [h.section_id for d in ranked.documents for h in d.sections]
        details = await search.section_details(conn, ranked.kb_rev, ids)
        facts = await search.document_facts(
            conn, ranked.kb_rev, [d.doc_id for d in ranked.documents]
        )
        documents = []
        for d in ranked.documents:
            f = facts[d.doc_id]
            documents.append(
                DocumentHit(
                    doc_id=d.doc_id,
                    title=f["title"],
                    doc_type=f["doc_type"],
                    score=round(d.score, 6),
                    truncated=f["truncated"],
                    sections=[
                        SectionHit(
                            section_id=h.section_id,
                            parent_section_id=details[h.section_id]["parent_section_id"],
                            path=details[h.section_id]["path"],
                            snippet=search.snippet(details[h.section_id]["masked_text"]),
                            promoted=h.promoted,
                        )
                        for h in d.sections
                    ],
                )
            )
        result = SearchKbResult(
            status="found",
            kb_rev=ranked.kb_rev,
            documents=documents,
            codes=ranked.codes,
            code_sections=[CodeSection(**c) for c in ranked.code_sections],
        )
        allowed, used = await kn.charge(
            sum(kb_tokens(s.snippet) for d in documents for s in d.sections)
        )
        if not allowed:
            return SearchKbResult(
                status="budget_exceeded", kb_rev=ranked.kb_rev, budget_used=used,
                budget_limit=kn.budget,
            )  # fmt: skip
        return result.model_copy(update={"budget_used": used, "budget_limit": kn.budget})

    @service.tool(scope=SCOPE_READ)
    async def get_document(args: GetDocumentIn, conn: Conn) -> GetDocumentResult:
        """A whole sanitized document of the current revision: text, section ids,
        metadata, related documents and the truncated flag. The agent reads it and
        notices for itself when documents disagree (S8a: no conflict register)."""
        rev = await search.current_rev(conn)
        if rev is None or args.doc_id in await kn.excluded():
            return GetDocumentResult(status="not_found", kb_rev=rev)
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT doc_id, doc_type, title, categories, device_family, covered_systems, "
                "related, revision, last_updated, truncated, masked_text "
                "FROM kb.documents WHERE kb_rev = %s AND doc_id = %s",
                (rev, args.doc_id),
            )
            doc = await cur.fetchone()
            if doc is None:
                return GetDocumentResult(status="not_found", kb_rev=rev)
            await cur.execute(
                "SELECT section_id, parent_section_id, path, ord, "
                "CASE WHEN %s THEN masked_text END AS masked_text FROM kb.sections "
                "WHERE kb_rev = %s AND doc_id = %s ORDER BY ord",
                (args.with_section_text, rev, args.doc_id),
            )
            sections = await cur.fetchall()
        allowed, used = await kn.charge(kb_tokens(doc["masked_text"]))
        if not allowed:
            return GetDocumentResult(
                status="budget_exceeded", kb_rev=rev, budget_used=used, budget_limit=kn.budget
            )
        return GetDocumentResult(
            status="found",
            kb_rev=rev,
            document=Document(
                **{k: (list(v) if isinstance(v, list | tuple) else v) for k, v in doc.items()},
                sections=[SectionRef(**s) for s in sections],
            ),
            budget_used=used,
            budget_limit=kn.budget,
        )

    @service.tool(scope=SCOPE_EVAL)
    async def register_exclusions(
        args: RegisterExclusionsIn, conn: Conn
    ) -> RegisterExclusionsResult:
        """Eval only: leave these documents out of every search and document call of one
        run (abstention test). Only `eval-runner` may call it (OPA P7)."""
        if current_call().client_id != EVAL_CLIENT:
            raise ToolFailure(ErrorCode.DENIED, "eval_only")
        excluded = await kn.store.add_exclusions(args.run_id, list(args.doc_ids))
        return RegisterExclusionsResult(status="registered", run_id=args.run_id, excluded=excluded)

    @service.tool(scope=SCOPE_EVAL)
    async def is_excluded(args: IsExcludedIn, conn: Conn) -> IsExcludedResult:
        """Eval only: whether a document is excluded for a run (S8 quote check)."""
        if current_call().client_id != EVAL_CLIENT:
            raise ToolFailure(ErrorCode.DENIED, "eval_only")
        hit = args.doc_id in await kn.store.exclusions(args.run_id)
        return IsExcludedResult(status="excluded" if hit else "not_excluded")


def build_service(
    settings: KnowledgeSettings,
    *,
    verifier: JwtVerifier | None = None,
    policy: Policy | None = None,
    pool: AsyncConnectionPool[AsyncConnection[Any]] | None = None,
    store: Store | None = None,
    embed_query: QueryEmbedder | None = None,
) -> McpService:
    if store is None:
        if settings.valkey_url_knowledge is None:
            raise SystemExit("VALKEY_URL_KNOWLEDGE is required to serve the knowledge server")
        store = ValkeyStore(settings.valkey_url_knowledge.get_secret_value())
    if embed_query is None:
        http = httpx.AsyncClient(timeout=20.0)
        key = settings.litellm_master_key.get_secret_value()

        async def embed_query(text: str) -> list[float]:
            return await aembed_one(
                http, text, base_url=settings.litellm_base_url, key=key,
                model=settings.model_embed, dim=settings.embed_dim,
            )  # fmt: skip

    service = McpService(
        name=NAME,
        policy_prefix=POLICY_PREFIX,
        issuer=settings.keycloak_issuer,
        verifier=verifier
        or JwtVerifier(issuer=settings.keycloak_issuer, audience=NAME, jwks_url=settings.jwks_url),
        policy=policy or OpaClient(settings.opa_url),
        pool=pool
        or AsyncConnectionPool(
            dsn(settings.database_url_knowledge, settings.db_host),
            min_size=1,
            max_size=5,
            open=False,
            kwargs={"autocommit": True},
        ),
        public_url=f"http://localhost:{settings.knowledge_port}",
    )
    register(service, Knowledge(store, embed_query, settings.kb_budget_tokens))
    return service
