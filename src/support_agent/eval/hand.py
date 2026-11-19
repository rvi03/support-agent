"""S14 build step 10: hand-score forms and their import (CP14.3, D39, D56, review M8).

`make hand-forms RUN=<run>` writes CSV forms in eval/hand/ plus one readable item
file per row in eval/hand/items/ (masked text only):

- tune run: `calibration.csv` (10 tune items: 5 K8 walks, 5 K15b notes, drawn with
  a fixed seed, fewer when the run has fewer) and `k9_tune.csv` (the 18 tune tricky
  tickets);
- held-out run: `k13.csv` (20 walks, 10 notes), `k9_heldout.csv` (18 tricky) and
  `cards.csv` (10 fault cards drawn with a fixed seed from the held-out cards,
  never chosen from failed walks).

Fill the `human` column with pass or fail (and `notes` if useful). `make
hand-import FORM=<form> RUN=<run>` reads it: agreement (judge pass/fail equals the
human's, K13 definition) for calibration and k13, the pass share for k9 and cards,
and pushes each human score to the item's trace in Langfuse. A held-out form is
refused unless the freeze manifest still matches (D56).
"""

from __future__ import annotations

import csv
import json
import random
import sys
from pathlib import Path
from typing import Any

from support_agent.common.config import EvalSettings, get_settings
from support_agent.eval import freeze
from support_agent.eval.metrics.judge import transcript

ROOT = Path(__file__).resolve().parents[3]
RUNS = ROOT / "eval" / "runs"
HAND = ROOT / "eval" / "hand"
ITEMS = HAND / "items"
CARDS = ROOT / "eval" / "fault_cards"
SEED = 20261119
LABELS: dict[str, tuple[str, str | None, str, str | None]] = {}
SCORES: dict[str, Any] = {}
FIELDS = ["form", "ticket", "kpi", "item_file", "judge", "human", "notes"]


def _load(name: str) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, Any]]:
    meta = json.loads((RUNS / name / "expected.json").read_text())
    results = {json.loads(x)["source_ticket_id"]: json.loads(x)
               for x in (RUNS / name / "results.jsonl").read_text().splitlines()}  # fmt: skip
    scores_path = RUNS / name / "scores.json"
    scores = json.loads(scores_path.read_text()) if scores_path.is_file() else {}
    return meta, results, scores


def _item_file(form: str, tid: str, kpi: str, res: dict[str, Any], extra: str = "") -> str:
    ITEMS.mkdir(parents=True, exist_ok=True)
    path = ITEMS / f"{form}-{tid}-{kpi}.md"
    v = res.get("view") or {}
    body = [f"# {form}: {tid} ({kpi})", "", f"Subject: {v.get('subject') or '-'}",
            f"Category: {v.get('category') or '-'}", "", transcript(res), ""]  # fmt: skip
    notes = [n for n in ((res.get("it_view") or {}).get("notes") or [])
             if n["kind"] in ("l2_note", "l1_pack")]  # fmt: skip
    for n in notes:
        body += [f"## {n['kind']}", "", n["body"], ""]
    if extra:
        body += [extra, ""]
    label = LABELS.get(tid)
    if label:
        body += [
            "## Expected (label)",
            "",
            f"- Routing: {label[0]}; escalation reason: {label[1] or '-'}",
            f"- Resolution: {label[2]}",
            f"- Tricky-ticket behaviour: {label[3] or '-'}",
            "",
        ]
    reason = ((SCORES.get(tid) or {}).get(kpi) or {}).get("reason")
    if reason:
        body += ["## Judge's reason (score blind first, then compare)", "", str(reason), ""]
    path.write_text("\n".join(body))
    return str(path.relative_to(ROOT))


def _judge(scores: dict[str, Any], tid: str, kpi: str) -> str:
    s = (scores.get(tid) or {}).get(kpi)
    if not s or s.get("excluded"):
        return ""
    return "pass" if s.get("passed") else "fail"


def _pick(cands: list[str], n: int, salt: str) -> list[str]:
    rng = random.Random(f"{SEED}:{salt}")  # noqa: S311 - a reproducible sample, not crypto
    return sorted(rng.sample(sorted(cands), min(n, len(cands))))


def _write(path: Path, rows: list[dict[str, str]]) -> None:
    HAND.mkdir(parents=True, exist_ok=True)
    if path.exists() and any(r.get("human") for r in csv.DictReader(path.open())):
        print(f"kept {path.name}: it already holds human scores")
        return
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {path.relative_to(ROOT)} ({len(rows)} rows)")


def _labels(ids: list[str]) -> None:
    import psycopg

    from support_agent.common.db import dsn

    s = get_settings(EvalSettings)
    with psycopg.connect(dsn(s.database_url_eval, s.db_host)) as conn:
        for tid, routing, reason, summary, chaos in conn.execute(
            "SELECT ticket_id, correct_routing, escalation_reason, correct_resolution_summary, "
            "chaos_correct_behavior FROM eval.labels WHERE ticket_id = ANY(%s)",
            (ids,),
        ):
            LABELS[tid] = (routing, reason, summary, chaos)


def forms(name: str) -> int:
    meta, results, scores = _load(name)
    _labels(list(results))
    SCORES.update(scores)
    half = meta["split"]

    def judged(kpi: str) -> list[str]:
        return [t for t in scores if _judge(scores, t, kpi)]

    tricky = [t for t, r in results.items() if r.get("cohort") == "tricky"]

    def rows(form: str, tids: list[str], kpi: str, extra: dict[str, str] | None = None
             ) -> list[dict[str, str]]:  # fmt: skip
        return [{"form": form, "ticket": t, "kpi": kpi,
                 "item_file": _item_file(form, t, kpi, results[t], (extra or {}).get(t, "")),
                 "judge": _judge(scores, t, kpi), "human": "", "notes": ""}
                for t in tids if t in results]  # fmt: skip

    if half == "tune":
        cal = rows("calibration", _pick(judged("K8"), 5, "cal-k8"), "K8")
        cal += rows("calibration", _pick(judged("K15b"), 10 - len(cal), "cal-k15b"), "K15b")
        _write(HAND / "calibration.csv", cal)
        _write(HAND / "k9_tune.csv", rows("k9_tune", sorted(tricky), "K9", _k9_hint(results)))
    else:
        k13 = rows("k13", _pick(judged("K8"), 20, "k13-walks"), "K8")
        k13 += rows("k13", _pick(judged("K15b") + judged("K15c"), 10, "k13-notes"), "K15b")
        _write(HAND / "k13.csv", k13)
        _write(HAND / "k9_heldout.csv",
               rows("k9_heldout", sorted(tricky), "K9", _k9_hint(results)))  # fmt: skip
    cards = [p.stem for p in CARDS.glob("INC-*.yaml")
             if (results.get(p.stem) or {}).get("split") == "heldout"]  # fmt: skip
    if cards:
        extra = {c: "## Fault card\n\n" + (CARDS / f"{c}.yaml").read_text() for c in cards}
        _write(HAND / "cards.csv", rows("cards", _pick(cards, 10, "cards"), "card", extra))
    return 0


def _k9_hint(results: dict[str, dict[str, Any]]) -> dict[str, str]:
    """The trick type is shown so the scorer can apply its expected behaviour."""
    import psycopg

    from support_agent.common.db import dsn

    s = get_settings(EvalSettings)
    with psycopg.connect(dsn(s.database_url_eval, s.db_host)) as conn:
        rows = conn.execute("SELECT ticket_id, chaos_type FROM eval.ticket_index "
                            "WHERE ticket_id = ANY(%s)", (list(results),)).fetchall()  # fmt: skip
    return {t: f"Trick type: {c}. Pass when the agent handled the trick as its type expects "
               "(agent-check.md E-cases)." for t, c in rows if c}  # fmt: skip


def import_form(form: str, name: str) -> int:
    path = HAND / f"{form}.csv"
    rows = [r for r in csv.DictReader(path.open()) if (r.get("human") or "").strip()]
    if not rows:
        raise SystemExit(f"{path.name} has no human scores yet")
    if form in ("k13", "k9_heldout", "cards"):
        freeze.check()
    meta, results, _ = _load(name)
    agree = sum(1 for r in rows if r["judge"] and r["human"].strip().lower() == r["judge"])
    judged = sum(1 for r in rows if r["judge"])
    passed = sum(1 for r in rows if r["human"].strip().lower() == "pass")
    summary = {"form": form, "scored": len(rows), "human_pass": passed,
               "agreement": f"{agree}/{judged}" if judged else "-"}  # fmt: skip
    from langfuse import Langfuse

    from support_agent.eval.dataset import LangfuseDataset

    lf = LangfuseDataset(get_settings(EvalSettings)).lf
    for r in rows:
        res = results.get(r["ticket"]) or {}
        if res.get("ticket_id"):
            lf.create_score(
                name=f"{r['kpi']}_human",
                value=1.0 if r["human"].strip().lower() == "pass" else 0.0,
                trace_id=Langfuse.create_trace_id(seed=f"{meta['run_id']}:{res['ticket_id']}"),
                data_type="NUMERIC", comment=(r.get("notes") or "")[:500],
                metadata={"form": form, "judge": r["judge"]},
            )  # fmt: skip
    lf.flush()
    (HAND / f"{form}.summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary))
    return 0


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[0] == "forms":
        return forms(argv[1])
    if len(argv) >= 3 and argv[0] == "import":
        return import_form(argv[1], argv[2])
    raise SystemExit("usage: hand forms RUN | hand import FORM RUN")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
