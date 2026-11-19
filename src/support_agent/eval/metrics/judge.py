"""S14 build step 5: GEval judges on the `judge` alias (D41, D65, CP14.3).

DeepEval's GEval runs with `LiteLLMJudge`, a DeepEvalBaseLLM that calls our LiteLLM
router (never OpenAI directly, so the eval holds no OpenAI key, D46). The rubrics
are the fixed files in eval/rubrics/. Transcripts are built from the masked API
view (the eval-runner sees messages from state, name left out) and the simulator's
own replies, never from `store_messages` (review M3).

- K8 on the D144 scope (score_item decides eligibility in metrics/code.py);
- K15b on the last L2 note of a handed-off labelled ticket;
- K15c on the L1 pack of a labelled ticket routed `l1_pack`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import yaml
from deepeval.metrics import GEval
from deepeval.models import DeepEvalBaseLLM
from deepeval.test_case import LLMTestCase, SingleTurnParams

from support_agent.common.config import EvalSettings, get_settings
from support_agent.eval.metrics.code import GROUP_A, Context, Score, handed_off, notes, outcome

ROOT = Path(__file__).resolve().parents[4]
RUBRICS = ROOT / "eval" / "rubrics"
PARAMS = [SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT, SingleTurnParams.EXPECTED_OUTPUT]


class LiteLLMJudge(DeepEvalBaseLLM):  # type: ignore[no-untyped-call]
    def __init__(self, base_url: str, key: str, alias: str) -> None:
        self.base_url, self.key, self.alias = base_url.rstrip("/"), key, alias
        self.model_id: str | None = None

    def load_model(self) -> Any:
        return self

    def _body(self, prompt: str) -> dict[str, Any]:
        return {"model": self.alias, "messages": [{"role": "user", "content": prompt}],
                "reasoning_effort": "low",
                "metadata": {"tags": ["eval", "judge"]}}  # fmt: skip

    def _text(self, data: dict[str, Any]) -> str:
        self.model_id = data.get("model") or self.model_id
        return str(data["choices"][0]["message"].get("content") or "")

    def generate(self, prompt: str, *args: Any, **kwargs: Any) -> str:
        r = httpx.post(f"{self.base_url}/v1/chat/completions", json=self._body(prompt),
                       headers={"Authorization": f"Bearer {self.key}"}, timeout=300)  # fmt: skip
        r.raise_for_status()
        return self._text(r.json())

    async def a_generate(self, prompt: str, *args: Any, **kwargs: Any) -> str:
        async with httpx.AsyncClient(timeout=300) as c:
            r = await c.post(f"{self.base_url}/v1/chat/completions", json=self._body(prompt),
                             headers={"Authorization": f"Bearer {self.key}"})  # fmt: skip
        r.raise_for_status()
        return self._text(r.json())

    def get_model_name(self) -> str:
        return f"litellm:{self.alias}"


def rubric(name: str, model: DeepEvalBaseLLM) -> GEval:
    r = yaml.safe_load((RUBRICS / f"{name}.yaml").read_text())
    return GEval(name=r["name"], criteria=r["criteria"], evaluation_steps=r["evaluation_steps"],
                 evaluation_params=PARAMS, model=model, threshold=float(r["threshold"]),
                 async_mode=False)  # fmt: skip


def transcript(res: dict[str, Any]) -> str:
    v = res.get("view") or {}
    o = outcome(v)
    lines = ["Agent messages to the store, in order:"]
    lines += [f"- [{m['kind']}] {m['text']}" for m in v.get("messages") or []]
    lines.append("Store replies, in order:")
    lines += [f"- {r['text']}" for r in res.get("store_replies") or []] or ["- none"]
    lines.append("IT actions run:")
    lines += [f"- {a['action_id']} ({a['tier']}): {a['outcome']}: {a.get('result') or ''}"
              for a in v.get("actions") or []] or ["- none"]  # fmt: skip
    walk = v.get("walk") or {}
    lines.append(f"Walk: runbook {walk.get('runbook_id') or v.get('runbook_id')}, steps "
                 + ", ".join(f"{s['step_id']} ({s['kind']}: {s.get('outcome')})"
                             for s in walk.get("steps") or []))  # fmt: skip
    lines.append(f"Ticket ended: status {v.get('status')}, route {o.get('route')}, handoff reason "
                 f"{o.get('handoff_reason') or '-'}")  # fmt: skip
    return "\n".join(lines)


def ticket_text(res: dict[str, Any]) -> str:
    v = res.get("view") or {}
    return f"Ticket subject: {v.get('subject') or ''}\nCategory: {v.get('category') or ''}"


@dataclass
class Judges:
    k8: GEval
    k15b: GEval
    k15c: GEval
    model: LiteLLMJudge

    @classmethod
    def load(cls) -> Judges:
        s = get_settings(EvalSettings)
        m = LiteLLMJudge(s.litellm_base_url, s.litellm_master_key.get_secret_value(),
                         s.model_judge)  # fmt: skip
        return cls(rubric("k8", m), rubric("k15b", m), rubric("k15c", m), m)

    def _run(self, metric: GEval, case: LLMTestCase) -> Score:
        try:
            metric.measure(case)
        except Exception as exc:  # noqa: BLE001 - a judge error is a recorded fail
            return Score(False, None, f"judge error: {type(exc).__name__}: {exc}"[:300],
                         missing=True)  # fmt: skip
        ok = bool(metric.success)
        return Score(ok, float(metric.score or 0.0), (metric.reason or "")[:500])

    def score_item(self, ctx: Context, tid: str, res: dict[str, Any] | None,
                   ticket: dict[str, Any], label: dict[str, Any] | None,
                   ) -> dict[str, Score]:  # fmt: skip
        out: dict[str, Score] = {}
        if label is None or res is None or res.get("status") != "done":
            return out
        runbooks = {d for d in label["relevant_kb_docs"] if d.startswith("runbooks/")}
        expected = (f"Expected resolution: {label['correct_resolution_summary']}\n"
                    f"Expected behaviour: {label['chaos_correct_behavior']}")  # fmt: skip
        if (ticket.get("category") in GROUP_A and label["correct_routing"] == "l1_guided"
                and runbooks & ctx.walkable):  # fmt: skip
            out["K8"] = self._run(
                self.k8,
                LLMTestCase(
                    input=ticket_text(res), actual_output=transcript(res), expected_output=expected
                ),
            )
        route = outcome(res["view"]).get("route")
        l2 = notes(res, "l2_note")
        if handed_off(res["view"]) and label["correct_routing"] != "l2_escalation":
            out["K15b"] = Score(excluded="label_not_l2")  # no escalation reason to judge against
        elif handed_off(res["view"]) and l2:
            exp = (f"Expected escalation reason: {label.get('escalation_reason') or 'none given'}\n"
                   f"Expected resolution: {label['correct_resolution_summary']}")  # fmt: skip
            out["K15b"] = self._run(
                self.k15b,
                LLMTestCase(input=ticket_text(res), actual_output=l2[-1], expected_output=exp),
            )
        packs = notes(res, "l1_pack")
        if route == "l1_pack" and packs:
            out["K15c"] = self._run(
                self.k15c,
                LLMTestCase(
                    input=ticket_text(res),
                    actual_output=packs[-1],
                    expected_output=f"Expected resolution: {label['correct_resolution_summary']}",
                ),
            )
        return out


def dump(scores: dict[str, Score]) -> str:
    return json.dumps({k: v.__dict__ for k, v in scores.items()})
