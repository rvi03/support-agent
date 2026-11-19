"""`make k4 SPLIT=tune`: K4 fixed-query replay and retrieval ablation (S6 step 6).

Query = the masked subject + description, `search_kb(doc_type=runbook)`; a hit is any
labelled runbook in the top 1 / top 3 documents (kpis.md K4). Variants:
BM25, vector, hybrid, hybrid + code rule; section-first vs document-first; raw text
vs a device + symptom + code query.

Pick rule (D83): the simplest setting that reaches 90% hit@3 AND puts a section holding
the code on top for every code in the KB error tables (query `error <code>` with the
code's device family). K4 tickets rarely hold codes, so hit@3 alone can't see code misses.

The tune half runs freely; the held-out half (S14) only on the frozen settings (D39, D56).
INC-00246 lists no runbook, so it is left out (kpis.md).
Writes eval/reports/ablation_tune.md with the run's kb_rev.
"""

from __future__ import annotations

import asyncio
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg
from psycopg import AsyncConnection

from support_agent.common.config import EvalSettings, get_settings
from support_agent.common.db import dsn
from support_agent.kb.codes import table_codes
from support_agent.kb.embed import embed
from support_agent.kb.metadata import FAMILY
from support_agent.mcp.knowledge import search, tokenizer

TARGET = 0.90
NO_RUNBOOK = {"INC-00246"}
REPORT = Path("eval/reports/ablation_tune.md")
K = 5


@dataclass(frozen=True)
class Case:
    ticket_id: str
    raw_query: str
    device_query: str
    family: str | None
    runbooks: frozenset[str]


@dataclass(frozen=True)
class Setting:
    name: str
    variant: search.Variant
    query: str  # "raw" | "device"
    family: bool  # pass the ticket category's device family (as if established)
    simplicity: int


SETTINGS = (
    Setting("BM25", search.Variant("bm25", False), "raw", False, 1),
    Setting("vector", search.Variant("vector", False), "raw", False, 2),
    Setting("hybrid", search.Variant("hybrid", False), "raw", False, 3),
    Setting("hybrid + code rule", search.Variant("hybrid", True), "raw", False, 4),
    Setting("hybrid + code rule, family given", search.Variant("hybrid", True), "raw", True, 5),
    Setting(
        "hybrid + code rule, document-first",
        search.Variant("hybrid", True, "document"),
        "raw",
        False,
        6,
    ),  # fmt: skip
    Setting("hybrid + code rule, device query", search.Variant("hybrid", True), "device", False, 7),
)


def device_query(subject: str, description: str, system_version: str | None) -> str:
    """Device + symptom + code (D19), built by code for the replay: the ticket's own
    system/version, its subject, and the codes in its text."""
    codes = tokenizer.codes_in(f"{subject} {description}")
    return " ".join(p for p in (system_version or "", subject, " ".join(codes)) if p)


def load_cases(conn: psycopg.Connection[Any], half: str) -> list[Case]:
    if half not in ("tune", "heldout"):
        raise SystemExit("half must be tune or heldout")
    if half == "heldout":  # S14: only on the frozen settings (D56)
        from support_agent.eval import freeze

        freeze.check()
    rows = conn.execute(
        "SELECT t.ticket_id, t.subject, t.description, t.system_version, t.category, "
        "       l.relevant_kb_docs "
        "FROM eval.split s JOIN eval.labels l USING (ticket_id) "
        "JOIN tickets.source_tickets t USING (ticket_id) "
        "WHERE s.half = %s AND s.cohort = 'labelled' ORDER BY t.ticket_id",
        (half,),
    ).fetchall()
    cases = []
    for tid, subject, desc, version, category, docs in rows:
        runbooks = frozenset(d for d in docs if d.startswith("runbooks/"))
        if tid in NO_RUNBOOK or not runbooks:
            continue
        cases.append(
            Case(
                tid,
                f"{subject}\n{desc}",
                device_query(subject, desc, version),
                FAMILY.get(category),
                runbooks,
            )
        )
    return cases


async def code_cases(conn: AsyncConnection[Any], rev: str) -> list[tuple[str, str]]:
    """(code, device family) for every code in the published KB's error tables."""
    cur = await conn.execute(
        "SELECT doc_id, masked_text, device_family FROM kb.documents WHERE kb_rev = %s", (rev,)
    )
    rows = await cur.fetchall()
    family = {doc: fams[0] for doc, _, fams in rows if fams}
    codes = table_codes({doc: text for doc, text, _ in rows})
    return sorted({(c, family[d]) for d, cs in codes.items() for c in cs if tokenizer.codes_in(c)})


async def code_test(
    conn: AsyncConnection[Any], rev: str, cases: list[tuple[str, str]],
    vectors: dict[str, list[float]], s: Setting,
) -> int:  # fmt: skip
    """How many codes get a section holding the code as the top result."""
    ok = 0
    for code, family in cases:
        q = f"error {code}"
        ranked = await search.rank(
            conn, q, search.Filters(device_family=family), k=3, vector=vectors[q],
            variant=s.variant, rev=rev,
        )  # fmt: skip
        if not ranked.documents:
            continue
        sid = ranked.documents[0].sections[0].section_id
        cur = await conn.execute(
            "SELECT bm25_tokens FROM kb.sections WHERE kb_rev = %s AND section_id = %s",
            (rev, sid),
        )
        row = await cur.fetchone()
        ok += bool(row and tokenizer.term(tokenizer.normalize_code(code)) in row[0])
    return ok


@dataclass
class Score:
    setting: Setting
    hit1: int
    hit3: int
    n: int
    latency_ms: list[float]
    tokens: list[int]
    misses: list[str]
    codes_ok: int = 0
    codes_total: int = 0

    @property
    def codes_pass(self) -> bool:
        return self.codes_total > 0 and self.codes_ok == self.codes_total

    @property
    def rate3(self) -> float:
        return self.hit3 / self.n


async def run_setting(
    conn: AsyncConnection[Any], rev: str, cases: list[Case], vectors: dict[str, list[float]],
    s: Setting,
) -> Score:  # fmt: skip
    hit1 = hit3 = 0
    latency: list[float] = []
    tokens: list[int] = []
    misses: list[str] = []
    for c in cases:
        q = c.raw_query if s.query == "raw" else c.device_query
        filters = search.Filters(doc_type="runbook", device_family=c.family if s.family else None)
        started = time.perf_counter()
        ranked = await search.rank(
            conn, q, filters, k=K, vector=vectors[q], variant=s.variant, rev=rev
        )
        ids = [h.section_id for d in ranked.documents for h in d.sections]
        details = await search.section_details(conn, rev, ids)
        latency.append((time.perf_counter() - started) * 1000)
        tokens.append(sum(len(search.snippet(d["masked_text"])) // 4 for d in details.values()))
        docs = [d.doc_id for d in ranked.documents]
        hit1 += bool(docs[:1] and docs[0] in c.runbooks)
        top3 = bool(set(docs[:3]) & c.runbooks)
        hit3 += top3
        if not top3:
            misses.append(c.ticket_id)
    return Score(s, hit1, hit3, len(cases), latency, tokens, misses)


def report(rev: str, scores: list[Score], winner: Score | None) -> str:
    lines = [
        f"# K4 replay and retrieval ablation ({REPORT.stem.split('_')[-1]} half)",
        "",
        f"- kb_rev: `{rev}`",
        f"- Tickets: {scores[0].n} tune labelled tickets with a labelled runbook "
        "(INC-00246 lists none). Held-out is not run here (D39, S14).",
        "- Query: masked subject + description (raw) or system version + subject + codes "
        "(device); `search_kb(doc_type=runbook)`, k = 5. Hit = any labelled runbook in the top N.",
        "- Latency: ranking + section fetch in-process (no MCP hop, no query embedding: "
        "vectors are computed once per query before timing).",
        "",
        "- Code test: `error <code>` with the code's device family, for every code in the KB "
        "error tables; a pass is a section holding the code as the top result.",
        "",
        "| Setting | hit@1 | hit@3 | code on top | p50 ms | p95 ms | KB tokens / call | misses@3 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for sc in scores:
        lat = sorted(sc.latency_ms)
        lines.append(
            f"| {sc.setting.name} | {sc.hit1 / sc.n:.1%} | {sc.rate3:.1%} | "
            f"{sc.codes_ok}/{sc.codes_total} | {statistics.median(lat):.1f} | "
            f"{lat[int(0.95 * (len(lat) - 1))]:.1f} | "
            f"{statistics.mean(sc.tokens):.0f} | {len(sc.misses)} |"
        )
    lines.append("")
    if winner:
        lines += [
            f"**Chosen: {winner.setting.name}**: the simplest setting with hit@3 >= "
            f"{TARGET:.0%} ({winner.rate3:.1%}) that also puts the code's section on top for "
            f"every KB code ({winner.codes_ok}/{winner.codes_total}) (D83).",
            "",
            f"Misses at 3: {', '.join(winner.misses) or 'none'}",
        ]
    else:
        lines.append(
            f"No setting reaches {TARGET:.0%} hit@3 and passes the code test; see S6 risks."
        )
    return "\n".join(lines) + "\n"


async def amain(settings: EvalSettings, half: str) -> int:
    url = dsn(settings.database_url_eval, settings.db_host)
    with psycopg.connect(url) as sync:
        cases = load_cases(sync, half)
    url_conn = await AsyncConnection.connect(url, autocommit=True)
    async with url_conn as conn:
        rev = await search.current_rev(conn)
        if rev is None:
            print("No current KB revision; run `make index`")
            return 1
        codes = await code_cases(conn, rev)
    texts = sorted(
        {c.raw_query for c in cases} | {c.device_query for c in cases}
        | {f"error {code}" for code, _ in codes}
    )  # fmt: skip
    vecs = embed(
        texts,
        base_url=settings.litellm_base_url,
        key=settings.litellm_master_key.get_secret_value(),
        model=settings.model_embed,
        dim=settings.embed_dim,
    )
    vectors = dict(zip(texts, vecs, strict=True))
    async with await AsyncConnection.connect(url, autocommit=True) as conn:
        scores = []
        for s in SETTINGS:
            sc = await run_setting(conn, rev, cases, vectors, s)
            sc.codes_ok, sc.codes_total = await code_test(conn, rev, codes, vectors, s), len(codes)
            scores.append(sc)
    passing = [sc for sc in scores if sc.rate3 >= TARGET and sc.codes_pass]
    winner = min(passing, key=lambda sc: sc.setting.simplicity) if passing else None
    text = report(rev, scores, winner)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(text)
    print(text)
    return 0 if winner else 1


def main(argv: list[str] | None = None) -> int:
    global REPORT
    args = sys.argv[1:] if argv is None else argv
    half = args[0] if args else "tune"
    if half == "heldout":
        REPORT = Path("eval/reports/ablation_heldout.md")
    return asyncio.run(amain(get_settings(EvalSettings), half))


if __name__ == "__main__":
    raise SystemExit(main())
