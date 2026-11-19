"""S14 build step 5: code metrics per item (kpis.md, D56, D95, D144, D146).

Pure functions over one item's final API view and its label, plus `KpiMetric`, a
DeepEval `BaseMetric` that wraps them for `deepeval test run`. Eligibility comes
from the label and the ticket, never from what the agent did, so a missing or
errored item is a fail and never shrinks a denominator (D56).

- agent L2 (K1-K3, D95, D146): Triage routed `l2_now`, `l1_then_l2` or `human`, or
  the ticket ended in a handoff for a reason other than a walk-time reason (the L1
  decision was already made: no approved steps, steps exhausted, version not
  covered, a rejected approval, the SLA or a KB revision change).
- K3 is scored per item as "not escalated" (pass), and reported as the share
  escalated, so lower is better as in kpis.md.
- K6 first action: guide when Triage chose an L1 route (`l1_guided`, `l1_then_l2`),
  escalate when it chose `l2_now`/`human` or Policy handed off before any walk.
- K7: every store message of kind `step` holds an approved binding span of the
  walked runbook word for word (whitespace folded), and every walk step id is a
  binding of that runbook.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from deepeval.metrics import BaseMetric
from deepeval.test_case import LLMTestCase

from support_agent.eval import k15a

ROOT = Path(__file__).resolve().parents[4]
BINDINGS = ROOT / "src" / "support_agent" / "agent" / "bindings.yaml"
GROUP_A = ("POS", "Printers")
L2_TRIAGE = frozenset({"l2_now", "l1_then_l2", "human"})
L1_TRIAGE = frozenset({"l1_guided", "l1_then_l2"})
WALK_REASONS = frozenset({
    "no_approved_steps", "steps_exhausted", "version_not_covered", "approval_rejected",
    "sla_breach", "kb_rev_changed",
})  # fmt: skip


@dataclass
class Score:
    passed: bool = False
    value: float | None = None
    reason: str = ""
    missing: bool = False
    excluded: str | None = None


def _missing(res: dict[str, Any] | None) -> Score | None:
    if res is None:
        return Score(missing=True, reason="missing: no result line")
    if res.get("status") != "done" or not res.get("view"):
        return Score(missing=True, reason=f"{res.get('status')}: {res.get('error') or '-'}")
    return None


@dataclass(frozen=True)
class Context:
    spans: dict[str, dict[str, str]]  # runbook -> binding id -> span

    @classmethod
    def load(cls, path: Path = BINDINGS) -> Context:
        data = yaml.safe_load(path.read_text())
        return cls({rb: {s["id"]: s.get("span", "") for s in steps}
                    for rb, steps in data["runbooks"].items()})  # fmt: skip

    @property
    def walkable(self) -> frozenset[str]:
        return frozenset(self.spans)


def outcome(view: dict[str, Any]) -> dict[str, Any]:
    return view.get("outcome") or {}


def agent_l2(view: dict[str, Any]) -> bool:
    o = outcome(view)
    if o.get("triage_route") in L2_TRIAGE:
        return True
    route = o.get("route") or view.get("route")
    return route in ("handoff", "human") and o.get("handoff_reason") not in WALK_REASONS


def first_action(view: dict[str, Any]) -> str:
    o = outcome(view)
    if o.get("triage_route") in L1_TRIAGE:
        return "guide"
    if o.get("triage_route") in ("l2_now", "human") or (o.get("route") or view.get("route")) in (
        "handoff",
        "human",
    ):
        return "escalate"
    return str(o.get("route") or view.get("route") or "none")


def _fold(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("**", "").replace("*", "")).strip()


def k7(ctx: Context, view: dict[str, Any]) -> Score:
    walk = view.get("walk") or {}
    rb = walk.get("runbook_id") or view.get("runbook_id")
    steps_sent = [m for m in view.get("messages") or [] if m.get("kind") == "step"]
    if not steps_sent:
        return Score(excluded="no_steps_sent")
    spans = ctx.spans.get(str(rb), {})
    bad = [s["step_id"] for s in walk.get("steps") or [] if s["step_id"] not in spans]
    folded = [_fold(sp) for sp in spans.values() if sp]
    unmatched = [
        m["text"][:60] for m in steps_sent if not any(f in _fold(m["text"]) for f in folded)
    ]
    if bad or unmatched:
        return Score(False, 0.0, f"steps not bound {bad}; texts without a span {unmatched}")
    return Score(True, 1.0, f"{len(steps_sent)} steps, all approved spans")


def handed_off(view: dict[str, Any]) -> bool:
    """Ended with L2: a handoff route, or a walk that escalated (status or queue)."""
    route = outcome(view).get("route") or view.get("route")
    return route in ("handoff", "human") or view.get("status") == "escalated" \
        or view.get("assignee_queue") == "l2"  # fmt: skip


def notes(res: dict[str, Any], kind: str) -> list[str]:
    return [n["body"] for n in ((res.get("it_view") or {}).get("notes") or []) if n["kind"] == kind]


def score_item(
    ctx: Context,
    tid: str,
    res: dict[str, Any] | None,
    ticket: dict[str, Any],
    label: dict[str, Any] | None,
) -> dict[str, Score]:
    out: dict[str, Score] = {}
    miss = _missing(res)
    view = (res or {}).get("view") or {}
    group_a = ticket.get("category") in GROUP_A
    if label is not None:
        want_l2 = label["correct_routing"] == "l2_escalation"
        if miss:
            out["K1"] = out["K5"] = out["K6"] = miss
            out["K2" if label["should_escalate"] else "K3"] = miss
        else:
            l2 = agent_l2(view)
            o = outcome(view)
            why = (f"triage {o.get('triage_route')}, route {o.get('route')}, "
                   f"reason {o.get('handoff_reason')}")  # fmt: skip
            side = "L2" if l2 else "L1"
            k1 = f"agent {side} vs label {label['correct_routing']}; {why}"
            out["K1"] = Score(l2 == want_l2, float(l2 == want_l2), k1)
            if label["should_escalate"]:
                out["K2"] = Score(l2, float(l2), f"escalate expected; {why}")
            else:
                out["K3"] = Score(not l2, float(l2), f"no escalation expected; {why}")
        runbooks = [d for d in label["relevant_kb_docs"] if d.startswith("runbooks/")]
        if not runbooks:
            out["K5"] = Score(excluded="label_lists_no_runbook")
        elif not miss:
            rb = view.get("runbook_id") or (view.get("walk") or {}).get("runbook_id")
            out["K5"] = Score(
                rb in runbooks, float(rb in runbooks), f"picked {rb}; label {runbooks}"
            )
        exp = label["expected_agent_action"]
        if exp == "verify_resolution_accuracy":
            out["K6"] = Score(excluded="one_off_action_INC_00097")
        elif not miss:
            want = "guide" if exp == "retrieve_runbook_and_guide" else "escalate"
            got = first_action(view)
            out["K6"] = Score(got == want, float(got == want), f"first action {got}, label {want}")
        if group_a:
            out["K7"] = miss or k7(ctx, view)
        # K8 scope (D144): l1_guided Group A tickets on a walkable runbook; judge scores it.
        if group_a and label["correct_routing"] == "l1_guided":
            if not set(runbooks) & ctx.walkable:
                out["K8"] = Score(excluded="out_of_poc_scope")
            elif miss:
                out["K8"] = miss
    if miss:
        return out
    if handed_off(view):
        l2_notes = notes(res or {}, "l2_note")
        if not l2_notes:
            out["K15a"] = Score(False, 0.0, "handed off but no L2 note readable", missing=True)
        else:
            r = k15a.check(l2_notes[-1])
            out["K15a"] = Score(r.ok, float(r.ok), "; ".join(r.problems) or "all mandatory fields")
    return out


class KpiMetric(BaseMetric):  # type: ignore[no-untyped-call]
    """DeepEval wrapper: the test case's metadata holds the item's precomputed Score."""

    def __init__(self, kpi: str) -> None:
        self.kpi = kpi
        self.threshold = 1.0

    @property
    def __name__(self) -> str:  # DeepEval reads the metric's name from here
        return self.kpi

    def measure(self, test_case: LLMTestCase, *args: Any, **kwargs: Any) -> float:
        s: Score = (test_case.metadata or {})["scores"][self.kpi]
        self.score = 1.0 if s.passed else 0.0
        self.success = s.passed
        self.reason = s.reason
        return self.score

    async def a_measure(self, test_case: LLMTestCase, *args: Any, **kwargs: Any) -> float:
        return self.measure(test_case)

    def is_successful(self) -> bool:
        return bool(self.success)
