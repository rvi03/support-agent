"""Hybrid search over the current KB revision (S6 step 4; rag-design.md section 7).

1. Candidates per section, filters applied inside both queries: top 50 by BM25
   (pg_textsearch on our own tokens) and top 50 by cosine (pgvector).
2. Reciprocal Rank Fusion (k = 60).
3. Exact-code rule: with an established `device_family`, sections holding a code of
   the query (normalized form) go to the top. Without a family, those sections are
   returned for every family in `code_sections`, with no promotion.
4. Roll up to documents: score = best section (section-first), or the sum of the
   top 3 sections (document-first, an ablation variant).

Excluded documents (eval abstention runs) are left out of every candidate query,
so nothing ranked or cached can bring them back (Codex P4).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from support_agent.kb.embed import vector_literal
from support_agent.mcp.knowledge import tokenizer

CANDIDATES = 50
RRF_K = 60
SNIPPET_CHARS = 300
BEST_SECTIONS = 3
BM25_INDEX = "kb.sections_bm25"

Mode = Literal["bm25", "vector", "hybrid"]
Rollup = Literal["section", "document"]


@dataclass(frozen=True)
class Variant:
    mode: Mode = "hybrid"
    code_rule: bool = True
    rollup: Rollup = "section"


DEFAULT = Variant()


@dataclass(frozen=True)
class Filters:
    doc_type: str | None = None
    device_family: str | None = None
    category: str | None = None
    exclude_doc_ids: tuple[str, ...] = ()


@dataclass
class Hit:
    section_id: str
    doc_id: str
    score: float = 0.0
    promoted: bool = False
    ranks: dict[str, int] = field(default_factory=dict)


@dataclass
class DocHit:
    doc_id: str
    score: float
    sections: list[Hit]


@dataclass
class Ranked:
    kb_rev: str
    documents: list[DocHit]
    code_sections: list[dict[str, Any]]
    codes: list[str]


Conn = AsyncConnection[Any]


def _where(f: Filters, params: dict[str, Any]) -> str:
    clauses = ["kb_rev = %(rev)s"]
    if f.doc_type:
        clauses.append("doc_type = %(doc_type)s")
        params["doc_type"] = f.doc_type
    if f.device_family:
        clauses.append("device_family && ARRAY[%(family)s]::text[]")
        params["family"] = f.device_family
    if f.category:
        clauses.append("%(category)s = ANY(categories)")
        params["category"] = f.category
    if f.exclude_doc_ids:
        clauses.append("NOT (doc_id = ANY(%(excl)s))")
        params["excl"] = list(f.exclude_doc_ids)
    return " AND ".join(clauses)


async def current_rev(conn: Conn) -> str | None:
    cur = await conn.execute("SELECT kb_rev FROM kb.revisions WHERE is_current")
    row = await cur.fetchone()
    return str(row[0]) if row else None


async def _rows(conn: Conn, query: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(query, params)
        return await cur.fetchall()


async def bm25_candidates(conn: Conn, rev: str, text: str, f: Filters) -> list[tuple[str, str]]:
    q = tokenizer.query_text(text)
    if not q:
        return []
    params: dict[str, Any] = {"rev": rev, "q": q, "idx": BM25_INDEX, "n": CANDIDATES}
    where = _where(f, params)
    rows = await _rows(
        conn,
        f"SELECT section_id, doc_id, bm25_tokens <@> to_bm25query(%(q)s, %(idx)s) AS s "  # noqa: S608 - fixed clauses
        f"FROM kb.sections WHERE {where} ORDER BY s, section_id LIMIT %(n)s",
        params,
    )
    return [(r["section_id"], r["doc_id"]) for r in rows if r["s"] < 0]


async def vector_candidates(
    conn: Conn, rev: str, vector: Sequence[float], f: Filters
) -> list[tuple[str, str]]:
    params: dict[str, Any] = {"rev": rev, "v": vector_literal(vector), "n": CANDIDATES}
    where = _where(f, params)
    rows = await _rows(
        conn,
        f"SELECT section_id, doc_id FROM kb.sections WHERE {where} "  # noqa: S608 - fixed clauses
        "ORDER BY embedding <=> %(v)s::vector, section_id LIMIT %(n)s",
        params,
    )
    return [(r["section_id"], r["doc_id"]) for r in rows]


async def code_candidates(
    conn: Conn, rev: str, codes: list[str], f: Filters
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"rev": rev, "terms": [tokenizer.term(c) for c in codes]}
    where = _where(f, params)
    return await _rows(
        conn,
        f"SELECT section_id, doc_id, device_family FROM kb.sections "  # noqa: S608 - fixed clauses
        f"WHERE {where} AND bm25_tokens && %(terms)s::text[] ORDER BY doc_id, ord",
        params,
    )


def fuse(lists: dict[str, list[tuple[str, str]]]) -> dict[str, Hit]:
    hits: dict[str, Hit] = {}
    for name, items in lists.items():
        for rank, (sid, doc) in enumerate(items, start=1):
            hit = hits.setdefault(sid, Hit(sid, doc))
            hit.score += 1.0 / (RRF_K + rank)
            hit.ranks[name] = rank
    return hits


def roll_up(hits: dict[str, Hit], k: int, rollup: Rollup) -> list[DocHit]:
    by_doc: dict[str, list[Hit]] = defaultdict(list)
    for hit in hits.values():
        by_doc[hit.doc_id].append(hit)
    docs: list[DocHit] = []
    for doc_id, items in by_doc.items():
        items.sort(key=lambda h: (-h.promoted, -h.score, h.section_id))
        best = items[:BEST_SECTIONS]
        if rollup == "section":
            score = best[0].score + (1.0 if best[0].promoted else 0.0)
        else:
            score = sum(h.score for h in best) + (1.0 if best[0].promoted else 0.0)
        docs.append(DocHit(doc_id, score, best))
    docs.sort(key=lambda d: (-d.score, d.doc_id))
    return docs[:k]


async def rank(
    conn: Conn,
    query: str,
    filters: Filters,
    *,
    k: int,
    vector: Sequence[float] | None,
    variant: Variant = DEFAULT,
    rev: str | None = None,
) -> Ranked:
    rev = rev or await current_rev(conn)
    if rev is None:
        raise LookupError("no current KB revision; run `make index`")
    lists: dict[str, list[tuple[str, str]]] = {}
    if variant.mode in ("bm25", "hybrid"):
        lists["bm25"] = await bm25_candidates(conn, rev, query, filters)
    if variant.mode in ("vector", "hybrid"):
        if vector is None:
            raise ValueError("vector search needs a query vector")
        lists["vector"] = await vector_candidates(conn, rev, vector, filters)
    hits = fuse(lists)
    codes = tokenizer.codes_in(query) if variant.code_rule else []
    code_sections: list[dict[str, Any]] = []
    if codes:
        matches = await code_candidates(conn, rev, codes, filters)
        if filters.device_family:
            for m in matches:
                hit = hits.setdefault(m["section_id"], Hit(m["section_id"], m["doc_id"]))
                hit.promoted = True
        else:
            code_sections = [
                {
                    "section_id": m["section_id"],
                    "doc_id": m["doc_id"],
                    "device_family": list(m["device_family"]),
                }
                for m in matches
            ]
    return Ranked(rev, roll_up(hits, k, variant.rollup), code_sections, codes)


async def section_details(conn: Conn, rev: str, ids: list[str]) -> dict[str, dict[str, Any]]:
    rows = await _rows(
        conn,
        "SELECT section_id, parent_section_id, path, masked_text, conflict_ids, token_count "
        "FROM kb.sections WHERE kb_rev = %(rev)s AND section_id = ANY(%(ids)s)",
        {"rev": rev, "ids": ids},
    )
    return {r["section_id"]: r for r in rows}


async def document_facts(conn: Conn, rev: str, ids: list[str]) -> dict[str, dict[str, Any]]:
    rows = await _rows(
        conn,
        "SELECT d.doc_id, d.title, d.doc_type, d.truncated, "
        "  coalesce((SELECT array_agg(c.conflict_id ORDER BY c.conflict_id) FROM kb.conflicts c "
        "            WHERE c.kb_rev = d.kb_rev AND d.doc_id = ANY(c.docs)), '{}') AS conflict_ids "
        "FROM kb.documents d WHERE d.kb_rev = %(rev)s AND d.doc_id = ANY(%(ids)s)",
        {"rev": rev, "ids": ids},
    )
    return {r["doc_id"]: r for r in rows}


def snippet(text: str) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= SNIPPET_CHARS else flat[: SNIPPET_CHARS - 1] + "…"
