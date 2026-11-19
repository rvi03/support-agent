"""S8 agent checks on the tune half: abstention (CP8.2) and the model check (CP8.4).

Runs Enrich -> Triage -> Policy -> Router on masked tune tickets (D39) through
the real servers as `agent-reader`, with the model alias given on the command
line (D62). Ticket replay time is the clock (D48).

- `abstention`: for each of the 20 tickets in eval/abstention.json, `eval-runner`
  registers its labelled runbooks as run-scoped exclusions (S6), and the ticket
  must end with no runbook and a `no_kb_match` handoff; any other reason is a
  fail (D57). Each ticket also runs once without exclusions (positive control),
  where it must find a runbook.
- `model-check ALIAS`: the 40 tickets in eval/model_check.json; K1, K5,
  structured-output validity, tool calls, tokens and latency; appends a section
  to eval/reports/model_check.md.

Guards: tool results pass through unmasked here. The tickets are the masked
source rows and the KB is sanitized at index time; the agent-side masker and
prompt scan are wired by the S10 graph and graded by the S14 checker (K11).
"""

from __future__ import annotations

import asyncio
import json
import statistics
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg

from support_agent.agent.llm import ChatClient, TicketBudget
from support_agent.agent.nodes.enrich import enrich
from support_agent.agent.nodes.policy import policy
from support_agent.agent.nodes.router import route
from support_agent.agent.nodes.triage import SopCache, TriageDeps, triage
from support_agent.agent.tools import (
    ItDataClient,
    KnowledgeClient,
    McpToolClient,
    TokenSource,
    ToolCallError,
)
from support_agent.common.config import AgentSettings, EvalSettings, get_settings
from support_agent.common.db import dsn
from support_agent.intake.schema import MaskedTicket

ROOT = Path(__file__).resolve().parents[3]
ABSTENTION = ROOT / "eval" / "abstention.json"
MODEL_CHECK = ROOT / "eval" / "model_check.json"
REPORT = ROOT / "eval" / "reports" / "model_check.md"
ABSTENTION_REPORT = ROOT / "eval" / "reports" / "abstention.md"
CONCURRENCY = 4
L2_ROUTES = frozenset({"handoff", "human"})
COLUMNS = (
    "ticket_id, store_id, date_opened, subject, description, store_name, priority, category, "
    "subcategory, asset_id, system_version, tags, escalation_flag, related_tickets, ticket_history"
)


def _pass(data: dict[str, Any], _ticket: str | None) -> dict[str, Any]:
    return data


@dataclass
class Record:
    ticket_id: str
    route: str
    rule: int
    handoff_reason: str | None
    runbook_id: str | None
    quote_check: str | None
    valid: bool
    first_try_valid: bool
    tool_calls: int
    llm_calls: int
    tokens: int
    latency_s: float
    rules_fired: list[str]
    abstained: bool = False
    triage_route: str | None = None
    triggers: list[str] | None = None  # model triggers as "name:evidence"
    conflicts: list[str] | None = None
    error: str | None = None

    @property
    def level(self) -> str:
        """Where the ticket ends: handoff and human are L2 now; an l1_then_l2 ticket
        walks the runbook (Resolver) or goes to a human L1 first and then to L2 by
        design, as the labels' `l2_escalation` with a guide-first action expects."""
        if self.route in L2_ROUTES:
            return "L2"
        if self.route in ("resolver", "l1_pack") and self.triage_route == "l1_then_l2":
            return "L2"
        return "L1"


@dataclass
class Labels:
    routing: str
    runbooks: frozenset[str]


class Harness:
    def __init__(self, alias: str) -> None:
        self.agent = get_settings(AgentSettings)
        self.eval = get_settings(EvalSettings)
        self.alias = alias
        issuer = self.agent.keycloak_issuer
        self.reader = TokenSource(
            issuer, "agent-reader", self.agent.keycloak_secret_agent_reader.get_secret_value()
        )
        self.runner = TokenSource(
            issuer, "eval-runner", self.eval.keycloak_secret_eval_runner.get_secret_value()
        )
        self.it_data = McpToolClient(self.agent.it_data_url, self.reader, _pass)
        self.knowledge = McpToolClient(self.agent.knowledge_url, self.reader, _pass)
        self.kb_admin = McpToolClient(self.agent.knowledge_url, self.runner, _pass)
        self.llm = ChatClient(
            self.agent.litellm_base_url,
            self.agent.litellm_master_key.get_secret_value(),
            model=alias,
        )
        self.sop = SopCache()
        self.db = psycopg.connect(dsn(self.eval.database_url_eval, self.eval.db_host))

    def ticket(self, ticket_id: str) -> MaskedTicket:
        cur = self.db.execute(
            f"SELECT {COLUMNS} FROM tickets.source_tickets t JOIN eval.split s USING (ticket_id) "  # noqa: S608
            "WHERE ticket_id = %s AND s.half = 'tune'",
            (ticket_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise SystemExit(f"{ticket_id} is not a tune-half ticket (D39)")
        data = dict(zip([c.name for c in cur.description or []], row, strict=True))
        return MaskedTicket(**{k: v for k, v in data.items() if v is not None})

    def labels(self, ticket_id: str) -> Labels:
        row = self.db.execute(
            "SELECT correct_routing, relevant_kb_docs FROM eval.labels WHERE ticket_id = %s",
            (ticket_id,),
        ).fetchone()
        if row is None:
            raise SystemExit(f"{ticket_id} has no label")
        return Labels(row[0], frozenset(d for d in row[1] if d.startswith("runbooks/")))

    async def exclude(self, run_id: uuid.UUID, doc_ids: list[str]) -> None:
        await self.kb_admin.call(
            "register_exclusions", {"run_id": str(run_id), "doc_ids": doc_ids}, run_id=run_id
        )

    async def run(self, ticket_id: str, run_id: uuid.UUID) -> Record:
        t = self.ticket(ticket_id)
        budget = TicketBudget(self.agent.llm_max_calls, self.agent.token_budget_per_ticket)
        started = time.monotonic()
        try:
            facts = await enrich(
                t, ItDataClient(self.it_data, ticket_id=t.ticket_id, run_id=run_id)
            )
        except ToolCallError as exc:
            return Record(t.ticket_id, "handoff", 1, "tool_error", None, None, False, False,
                          0, 0, 0, time.monotonic() - started, [], error=str(exc))  # fmt: skip
        deps = TriageDeps(
            llm=self.llm,
            kb=KnowledgeClient(self.knowledge, ticket_id=t.ticket_id, run_id=run_id),
            it_data=ItDataClient(self.it_data, ticket_id=t.ticket_id, run_id=run_id),
            budget=budget,
            sop=self.sop,
            max_tool_calls=self.agent.triage_max_tool_calls,
            run_id=run_id,
        )
        tri = await triage(t, facts, deps)
        pol = policy(t, facts, tri, confidence_min=self.agent.confidence_min)
        dec = route(tri, pol, clarify_count=0, now=t.date_opened)
        out = tri.output
        return Record(
            ticket_id=t.ticket_id,
            route=dec.route,
            rule=dec.rule,
            handoff_reason=pol.handoff_reason,
            runbook_id=out.runbook_id if out else None,
            quote_check=tri.quote_check,
            valid=out is not None,
            first_try_valid=tri.first_try_valid,
            tool_calls=tri.tool_calls,
            llm_calls=budget.calls,
            tokens=budget.tokens,
            latency_s=time.monotonic() - started,
            rules_fired=pol.rules_fired,
            abstained=tri.abstained,
            triage_route=out.route if out else None,
            triggers=[f"{h.trigger}: {h.evidence[:60]}" for h in out.sop_triggers] if out else [],
            conflicts=list(out.doc_conflicts) if out else [],
        )

    async def many(self, jobs: list[tuple[str, uuid.UUID]]) -> list[Record]:
        sem = asyncio.Semaphore(CONCURRENCY)

        async def one(tid: str, rid: uuid.UUID) -> Record:
            async with sem:
                return await self.run(tid, rid)

        # The SOP is fetched once before the fan-out so the cache is filled once.
        await self.sop.get(
            KnowledgeClient(self.knowledge, ticket_id=jobs[0][0], run_id=uuid.uuid4())
        )
        return list(await asyncio.gather(*(one(t, r) for t, r in jobs)))


# ---- abstention ----------------------------------------------------------------------


def family_runbooks(h: Harness, labelled: frozenset[str]) -> list[str]:
    """Every runbook sharing a device family with the labelled ones (scope `family`)."""
    rows = h.db.execute(
        "SELECT doc_id, device_family FROM kb.documents WHERE doc_type = 'runbook' "
        "AND kb_rev = (SELECT kb_rev FROM kb.documents LIMIT 1)"
    ).fetchall()
    fams = {f for doc, fam in rows if doc in labelled for f in fam if f != "payment"}
    return sorted({doc for doc, fam in rows if fams & set(fam)} | labelled)


async def abstention(alias: str, scope: str = "family") -> int:
    h = Harness(alias)
    ids: list[str] = json.loads(ABSTENTION.read_text())["tickets"]
    excluded_jobs = []
    for tid in ids:
        rid = uuid.uuid4()
        labelled = h.labels(tid).runbooks
        docs = family_runbooks(h, labelled) if scope == "family" else sorted(labelled)
        await h.exclude(rid, docs)
        excluded_jobs.append((tid, rid))
    excluded = await h.many(excluded_jobs)
    control = await h.many([(tid, uuid.uuid4()) for tid in ids])
    lines = [
        f"# Abstention check (S8, CP8.2), exclusion scope `{scope}`",
        "",
        f"Model alias `{alias}`, {datetime.now(UTC):%Y-%m-%d %H:%M} UTC, {len(ids)} Group A "
        "tune tickets. Pass = with the labelled runbooks excluded, Triage abstains (valid "
        "output, a search ran, no verified runbook: reason `no_kb_match`, D57) and the "
        "ticket takes no L1 path; a tool, budget, output or LLM failure is a fail. Policy's "
        "route reason may be stronger (an SOP trigger). Control (no exclusions) must find "
        "a runbook.",
        "",
        "| Ticket | Excluded: abstained | route | policy reason | runbook | Control: runbook |",
        "|---|---|---|---|---|---|",
    ]
    passed = control_ok = wrong = 0
    for ex, co in zip(excluded, control, strict=True):
        labelled = h.labels(ex.ticket_id).runbooks
        # Triage abstained (its own reason is no_kb_match, D57) and the ticket did not
        # reach an L1 path; an infrastructure failure is a fail, not an abstention.
        ok = ex.abstained and ex.route not in ("resolver", "l1_pack")
        wrong += ex.runbook_id in labelled
        passed += ok
        control_ok += co.runbook_id is not None
        lines.append(
            f"| {ex.ticket_id} | {'yes' if ok else 'NO'} | {ex.route} | {ex.handoff_reason} | "
            f"{ex.runbook_id or '-'} | {co.runbook_id or '-'} |"
        )
    lines += [
        "",
        f"- Abstained (`no_kb_match`): **{passed}/{len(ids)}**; labelled runbook walked "
        f"with it excluded: **{wrong}**; another runbook cited: "
        f"**{sum(1 for e in excluded if e.runbook_id)}**.",
        f"- Control found a runbook: **{control_ok}/{len(ids)}**.",
        "",
    ]
    report = ABSTENTION_REPORT.with_name(f"abstention_{scope}.md")
    report.write_text("\n".join(lines))
    print("\n".join(lines))
    return 0 if passed == len(ids) and wrong == 0 and control_ok == len(ids) else 1


# ---- model check ---------------------------------------------------------------------


def _pct(n: int, d: int) -> str:
    return f"{100 * n / d:.1f}% ({n}/{d})" if d else "n/a"


async def model_check(alias: str) -> int:
    h = Harness(alias)
    spec = json.loads(MODEL_CHECK.read_text())
    ids: list[str] = spec["group_a"] + spec["mixed"]
    records = await h.many([(tid, uuid.uuid4()) for tid in ids])
    k1 = k5 = k5_total = valid = first = 0
    rows = []
    for r in records:
        lab = h.labels(r.ticket_id)
        want = "L2" if lab.routing == "l2_escalation" else "L1"
        k1 += r.level == want
        if lab.runbooks and lab.routing == "l1_guided":
            k5_total += 1
            k5 += r.runbook_id in lab.runbooks
        valid += r.valid
        first += r.first_try_valid
        rows.append(
            f"| {r.ticket_id} | {want} | {r.level} ({r.route}, line {r.rule}, "
            f"{r.triage_route}) | "
            f"{r.handoff_reason or '-'} | {r.runbook_id or '-'} | {r.quote_check or '-'} | "
            f"{r.tool_calls} | {r.tokens} | {r.latency_s:.1f} | "
            f"{'; '.join(r.triggers or []) or '-'} | {', '.join(r.conflicts or []) or '-'} |"
        )
    n = len(records)
    lat = sorted(r.latency_s for r in records)
    k1_rate = k1 / n
    invalid_rate = 1 - valid / n
    section = [
        f"## `{alias}` ({datetime.now(UTC):%Y-%m-%d %H:%M} UTC)",
        "",
        f"- K1 routing L1/L2: **{_pct(k1, n)}** (target >= 85%)",
        f"- K5 right runbook (L1-routed labelled tickets with a runbook): **{_pct(k5, k5_total)}** "
        "(target >= 90%)",
        f"- Structured output valid: **{_pct(valid, n)}**; "
        f"valid on the first try: {_pct(first, n)}",
        f"- Latency p50 {statistics.median(lat):.1f} s, max {lat[-1]:.1f} s; tokens per ticket "
        f"mean {statistics.mean(r.tokens for r in records):.0f}, max "
        f"{max(r.tokens for r in records)}; LLM calls mean "
        f"{statistics.mean(r.llm_calls for r in records):.1f}",
        f"- Rule X1: {'pass' if k1_rate >= 0.85 and invalid_rate <= 0.05 else 'FAIL'} "
        "(K1 >= 85% and invalid output <= 5%)",
        "",
        "| Ticket | Label | Agent | Handoff reason | Runbook | Quote check | Tools | Tokens | s "
        "| Model triggers | Conflicts |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
        *rows,
        "",
    ]
    if not REPORT.exists():
        REPORT.write_text(
            "# Model check (S8, CP8.4)\n\n40 fixed tune-half tickets (eval/model_check.json: "
            "20 Group A, 20 mixed); Enrich -> Triage -> Policy -> Router; K1 counts handoff "
            "and human as L2, and a Resolver or L1-pack ticket that Triage routed "
            "l1_then_l2 as L2 too (it walks the runbook first, then hands off by design); "
            "every other route is L1. K5 over the L1-labelled tickets with a labelled "
            "runbook.\n\n"
        )
    with REPORT.open("a") as f:
        f.write("\n".join(section) + "\n")
    print("\n".join(section[:8]))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args or args[0] not in ("abstention", "model-check", "one"):
        raise SystemExit("usage: agent_run abstention|model-check|one [ALIAS] [TICKET]")
    alias = args[1] if len(args) > 1 else "agent"
    if args[0] == "abstention":
        return asyncio.run(abstention(alias, args[2] if len(args) > 2 else "family"))
    if args[0] == "model-check":
        return asyncio.run(model_check(alias))

    async def one() -> int:
        h = Harness(alias)
        rec = (await h.many([(args[2], uuid.uuid4())]))[0]
        print(json.dumps(rec.__dict__, indent=1, default=str))
        return 0

    return asyncio.run(one())


if __name__ == "__main__":
    raise SystemExit(main())
