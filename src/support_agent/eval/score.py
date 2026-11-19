"""S14 build steps 5 and 11: score a finished run, push scores, write the report.

`make eval-score RUN=<run> [TUNE=<tune run>]` (the judge phase; runs only after the
agent phase, so a score never feeds back into a run):

1. reads `eval/runs/<run>/expected.json` and `results.jsonl`, and the labels from
   `eval.labels`; denominators come from the expected list and the labels, fixed
   before scoring; a missing or errored item is a fail, never dropped (D56);
2. code metrics (DeepEval `BaseMetric`s in eval/metrics/code.py): K1, K2, K3, K5,
   K6, K7, K15a, and K14 time and cost;
3. GEval with the fixed rubrics in eval/rubrics/ on the `judge` alias
   (eval/metrics/judge.py): K8 on the D144 walk scope, K15b on L2 notes, K15c on
   L1 packs; transcripts come from the masked API view, never `store_messages`;
4. every score goes to the item's agent trace in Langfuse, and each item is linked
   to the dataset run named after the run folder (CP14.1);
5. writes `eval/reports/<run>.md`: overall, by group (A POS/Printers, B other,
   C tricky as an overlapping slice) and by category, with the tune run beside it
   when given, every KPI against its kpis.md target; a held-out run is appended to
   the ledger `eval/reports/heldout_runs.md` with its freeze hash.

K4 (retrieval hit@3) is the replay in eval/k4.py (`make k4 SPLIT=…`), reported there.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg

from support_agent.common.config import EvalSettings, get_settings
from support_agent.common.db import dsn
from support_agent.eval import freeze
from support_agent.eval.metrics import code as cm

ROOT = Path(__file__).resolve().parents[3]
RUNS = ROOT / "eval" / "runs"
REPORTS = ROOT / "eval" / "reports"
LEDGER = REPORTS / "heldout_runs.md"
LABEL_COLUMNS = (
    "correct_routing", "should_escalate", "escalation_reason", "expected_agent_action",
    "relevant_kb_docs", "correct_resolution_summary", "chaos_correct_behavior",
)  # fmt: skip
TARGETS = {
    "K1": (">=", 0.85), "K2": (">=", 0.95), "K3": ("<=", 0.15), "K5": (">=", 0.90),
    "K6": (">=", 0.85), "K7": (">=", 1.0), "K8": (">=", 0.80), "K15a": (">=", 1.0),
    "K15b": (">=", 0.80), "K15c": (">=", 0.80),
}  # fmt: skip
KPI_NAMES = {
    "K1": "Routing accuracy (L1 vs L2)", "K2": "Escalations caught",
    "K3": "Needless escalations", "K5": "Right runbook walked", "K6": "Right first action",
    "K7": "Steps come from the runbook", "K8": "Fix matches the correct answer (D144 scope)",
    "K15a": "L2 note mandatory fields", "K15b": "L2 note quality (judge)",
    "K15c": "L1 pack quality (judge)",
}  # fmt: skip


@dataclass
class Run:
    name: str
    meta: dict[str, Any]
    results: dict[str, dict[str, Any]]
    tickets: dict[str, dict[str, Any]]  # source ticket -> category, cohort, chaos_type
    labels: dict[str, dict[str, Any]]
    scores: dict[str, dict[str, cm.Score]] = field(default_factory=dict)


def load_run(name: str, conn: psycopg.Connection[Any]) -> Run:
    folder = RUNS / name
    meta = json.loads((folder / "expected.json").read_text())
    results: dict[str, dict[str, Any]] = {}
    path = folder / "results.jsonl"
    for line in path.read_text().splitlines() if path.is_file() else []:
        r = json.loads(line)
        results[r["source_ticket_id"]] = r
    ids = list(meta["items"])
    tickets = {
        tid: {"category": cat, "cohort": cohort, "half": half, "chaos_type": chaos}
        for tid, cat, cohort, half, chaos in conn.execute(
            "SELECT t.ticket_id, t.category, s.cohort, s.half, i.chaos_type "
            "FROM tickets.source_tickets t JOIN eval.split s USING (ticket_id) "
            "LEFT JOIN eval.ticket_index i USING (ticket_id) WHERE t.ticket_id = ANY(%s)",
            (ids,),
        )
    }
    cols = ", ".join(LABEL_COLUMNS)
    labels = {
        row[0]: dict(zip(LABEL_COLUMNS, row[1:], strict=True))
        for row in conn.execute(
            f"SELECT ticket_id, {cols} FROM eval.labels WHERE ticket_id = ANY(%s)",  # noqa: S608
            (ids,),
        )
    }
    return Run(name, meta, results, tickets, labels)


def score_run(run: Run, *, judge: bool = True) -> None:
    from support_agent.eval.metrics import judge as jm

    ctx = cm.Context.load()
    geval = jm.Judges.load() if judge else None
    for tid in run.meta["items"]:
        res = run.results.get(tid)
        t = run.tickets.get(tid, {})
        label = run.labels.get(tid)
        s = cm.score_item(ctx, tid, res, t, label)
        if geval is not None:
            s.update(geval.score_item(ctx, tid, res, t, label))
        run.scores[tid] = s


def group_of(t: dict[str, Any]) -> str:
    return "A" if t.get("category") in cm.GROUP_A else "B"


@dataclass
class Agg:
    eligible: int = 0
    passed: int = 0
    failed: int = 0
    missing: int = 0
    excluded: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    @property
    def value(self) -> float | None:
        return self.passed / self.eligible if self.eligible else None


def aggregate(run: Run, kpi: str, pick: Any = None) -> Agg:
    a = Agg()
    for tid, scores in run.scores.items():
        if pick is not None and not pick(run.tickets.get(tid, {})):
            continue
        s = scores.get(kpi)
        if s is None:
            continue
        if s.excluded:
            a.excluded[s.excluded] += 1
            continue
        a.eligible += 1
        if s.missing:
            a.missing += 1
            a.failed += 1
        elif s.passed:
            a.passed += 1
        else:
            a.failed += 1
    return a


def kpi_value(kpi: str, a: Agg) -> float | None:
    """K3 is reported as the share escalated (lower is better); the rest as the pass share."""
    if kpi == "K3":
        return a.failed / a.eligible if a.eligible else None
    return a.value


def _pct(v: float | None) -> str:
    return "-" if v is None else f"{v:.1%}"


def _meets(kpi: str, v: float | None) -> str:
    if v is None:
        return "-"
    op, target = TARGETS[kpi]
    ok = v >= target if op == ">=" else v <= target
    return "yes" if ok else "**no**"


def k14(run: Run) -> dict[str, float]:
    rows = [r for r in run.results.values() if r.get("view")]
    tok = [((r["view"].get("outcome") or {}).get("tokens") or 0) for r in rows]
    cost = [((r["view"].get("outcome") or {}).get("cost_usd") or 0.0) for r in rows]
    secs = [r.get("seconds") or 0.0 for r in rows]
    n = max(len(rows), 1)
    return {
        "tickets": len(rows), "tokens_mean": sum(tok) / n, "tokens_max": max(tok or [0]),
        "cost_mean": sum(cost) / n, "cost_total": sum(cost), "seconds_mean": sum(secs) / n,
        "seconds_max": max(secs or [0]),
    }  # fmt: skip


def report(run: Run, tune: Run | None) -> str:
    half = run.meta["split"]
    finished = sum(1 for r in run.results.values() if r["status"] == "done")
    lines = [
        f"# Eval report: {run.name}",
        "",
        f"- Run id `{run.meta['run_id']}`, split `{half}`, started {run.meta['started_at']}.",
        f"- Items expected {len(run.meta['items'])}, finished "
        f"{finished}, missing or errored {len(run.meta['items']) - finished}"
        " (each counts as a fail).",
        f"- Freeze hash: `{run.meta.get('freeze_hash') or 'not frozen (tune run)'}`.",
    ]
    if tune:
        lines.append(f"- Tune run beside it: `{tune.name}` (run id `{tune.meta['run_id']}`).")
    lines += [
        "",
        "Scope notes (stated before the run):",
        "- D144: the POC walks only `printer-offline` and `pos-screen-frozen`. K8 is scored on "
        "the l1_guided tickets whose labelled runbooks include one of them; every other "
        "l1_guided ticket is excluded from K8 as `out_of_poc_scope` and ends in a handoff "
        "(`no_approved_steps`) by design.",
        "- K1-K3 score the routing decision (Triage's route after Policy, D95); a ticket "
        "handed off only because its runbook has no approved steps keeps its L1 decision (D146).",
        "- K8 walks use scripted approvals (`mock-l2`) and simulated L2 work, so K8 is not an "
        "autonomous fix rate; the store is a simulator answering from a fault card, with the "
        "outcome decided by code (D40, D58).",
        "- The design notes (agent-check.md E1-E18) were written from all 256 tickets before the "
        "split; the history tools serve earlier tickets of the same store from both halves.",
        "",
        "## KPIs",
        "",
        "| KPI | Name | Value | Target | Meets | Eligible | Passed | Failed (missing) | "
        "Excluded | Tune |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for kpi in TARGETS:
        a = aggregate(run, kpi)
        tv = _pct(kpi_value(kpi, aggregate(tune, kpi))) if tune else "-"
        op, target = TARGETS[kpi]
        exc = ", ".join(f"{k} {v}" for k, v in sorted(a.excluded.items())) or "-"
        lines.append(
            f"| {kpi} | {KPI_NAMES[kpi]} | {_pct(kpi_value(kpi, a))} | {op} {target:.0%} | "
            f"{_meets(kpi, kpi_value(kpi, a))} | {a.eligible} | {a.passed} | "
            f"{a.failed} ({a.missing}) | {exc} | {tv} |"
        )
    lines += ["", "## By group", "", "| KPI | A (POS, Printers) | B (other) | C (tricky slice) |",
              "|---|---|---|---|"]  # fmt: skip
    for kpi in TARGETS:
        cells = []
        for pick in (
            lambda t: group_of(t) == "A",
            lambda t: group_of(t) == "B",
            lambda t: t.get("cohort") == "tricky",
        ):
            a = aggregate(run, kpi, pick)
            cells.append(
                f"{_pct(kpi_value(kpi, a))} ({a.passed}/{a.eligible})" if a.eligible else "-"
            )
        lines.append(f"| {kpi} | " + " | ".join(cells) + " |")
    cats = sorted({t.get("category") or "?" for t in run.tickets.values()})
    lines += ["", "## By category", "", "| KPI | " + " | ".join(cats) + " |",
              "|---|" + "---|" * len(cats)]  # fmt: skip
    for kpi in ("K1", "K2", "K3", "K5", "K6"):
        cells = []
        for c in cats:
            a = aggregate(run, kpi, lambda t, c=c: (t.get("category") or "?") == c)
            cells.append(
                f"{_pct(kpi_value(kpi, a))} ({a.passed}/{a.eligible})" if a.eligible else "-"
            )
        lines.append(f"| {kpi} | " + " | ".join(cells) + " |")
    m = k14(run)
    lines += [
        "",
        "## K14 time and cost",
        "",
        f"- {m['tickets']} finished tickets: tokens mean {m['tokens_mean']:.0f}, max "
        f"{m['tokens_max']:.0f}; cost mean ${m['cost_mean']:.4f}, total ${m['cost_total']:.2f} "
        f"(agent only; simulator and judge calls are on their own traces); wall time mean "
        f"{m['seconds_mean']:.0f} s, max {m['seconds_max']:.0f} s (includes simulated replies "
        "and approvals).",
        "",
        "## Misses",
        "",
        "Every failed item with its reason (gaps to explain).",
        "",
    ]
    for kpi in TARGETS:
        bad = [(tid, s[kpi]) for tid, s in sorted(run.scores.items())
               if kpi in s and not s[kpi].excluded and not s[kpi].passed]  # fmt: skip
        if bad:
            lines.append(f"- **{kpi}** ({len(bad)}): " + "; ".join(
                f"{tid}: {sc.reason}" for tid, sc in bad[:40]))  # fmt: skip
    lines.append("")
    return "\n".join(lines)


def push_langfuse(run: Run, settings: EvalSettings) -> int:
    import httpx
    from langfuse import Langfuse

    from support_agent.eval.dataset import ITEM_PREFIX, LangfuseDataset

    lf: Langfuse = LangfuseDataset(settings).lf
    assert settings.langfuse_public_key and settings.langfuse_secret_key  # noqa: S101
    auth = (settings.langfuse_public_key.get_secret_value(),
            settings.langfuse_secret_key.get_secret_value())  # fmt: skip
    linked = 0
    with httpx.Client(timeout=30.0) as http:
        for tid, scores in run.scores.items():
            res = run.results.get(tid) or {}
            if not res.get("ticket_id"):
                continue
            trace_id = Langfuse.create_trace_id(seed=f"{run.meta['run_id']}:{res['ticket_id']}")
            r = http.post(f"{settings.langfuse_host}/api/public/dataset-run-items", auth=auth,
                          json={"runName": run.name, "datasetItemId": ITEM_PREFIX + tid,
                                "traceId": trace_id,
                                "metadata": {"split": run.tickets.get(tid, {}).get("half"),
                                             "run_id": run.meta["run_id"]}})  # fmt: skip
            r.raise_for_status()
            linked += 1
            for kpi, s in scores.items():
                if s.excluded:
                    continue
                lf.create_score(name=kpi, value=1.0 if s.passed else 0.0, trace_id=trace_id,
                                data_type="NUMERIC", comment=(s.reason or "")[:500],
                                metadata={"run": run.name, "missing": s.missing,
                                          "raw": s.value})  # fmt: skip
    lf.flush()
    return linked


def ledger(run: Run, text: str) -> None:
    if run.meta["split"] == "tune":
        return
    head = []
    for kpi in ("K1", "K2", "K3", "K5", "K8"):
        head.append(f"{kpi} {_pct(kpi_value(kpi, aggregate(run, kpi)))}")
    if not LEDGER.is_file():
        LEDGER.write_text("# Held-out runs (ledger, D56)\n\nEvery held-out run, in order; "
                          "none is ever dropped.\n\n")  # fmt: skip
    with LEDGER.open("a") as f:
        f.write(f"- {datetime.now(UTC):%Y-%m-%d %H:%M}Z `{run.name}` run `{run.meta['run_id']}`, "
                f"freeze `{run.meta.get('freeze_hash')}`: {', '.join(head)}\n")  # fmt: skip


def main(argv: list[str]) -> int:
    opts = dict(zip(argv[::2], argv[1::2], strict=False))
    name = opts.get("--run")
    if not name:
        raise SystemExit("usage: score --run NAME [--tune NAME] [--no-judge] [--no-push]")
    settings = get_settings(EvalSettings)
    with psycopg.connect(dsn(settings.database_url_eval, settings.db_host)) as conn:
        run = load_run(name, conn)
        tune = load_run(opts["--tune"], conn) if opts.get("--tune") else None
    if run.meta["split"] != "tune":
        frozen = freeze.check(settings)
        if run.meta.get("freeze_hash") != frozen:
            raise SystemExit(f"held-out scoring refused: run froze {run.meta.get('freeze_hash')}, "
                             f"now {frozen}")  # fmt: skip
    judge = "--no-judge" not in argv
    score_run(run, judge=judge)
    if tune:
        score_run(tune, judge=judge)
    REPORTS.mkdir(exist_ok=True)
    text = report(run, tune)
    (REPORTS / f"{name}.md").write_text(text)
    (RUNS / name / "scores.json").write_text(json.dumps(
        {tid: {k: v.__dict__ for k, v in s.items()} for tid, s in run.scores.items()},
        indent=1, default=str))  # fmt: skip
    if "--no-push" not in argv:
        print(f"langfuse: {push_langfuse(run, settings)} items linked to dataset run {name}")
    ledger(run, text)
    print(f"report: eval/reports/{name}.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
