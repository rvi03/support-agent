"""Tracing and metrics for graph nodes (S10 build step 2; D9).

- Langfuse: one trace per (run_id, ticket_id), its id derived from that pair, so
  a resume in another process lands in the same trace. One span per node; the
  LLM calls a node made are one generation child with their tokens and the
  real cost LiteLLM reported (K14). Span input and output are the masked state
  summary only; nothing read from `pii.vault` ever enters a span (review M3).
- Prometheus: node latency, LLM calls and handoffs by reason. The API process
  (S12) exposes them; in `ticket-local` they only count.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Protocol

from prometheus_client import Counter, Histogram

NODE_LATENCY = Histogram("agent_node_seconds", "Graph node latency", ["node"])
NODE_RESULTS = Counter("agent_node_results_total", "Graph node results", ["node", "result"])
LLM_CALLS = Counter("agent_llm_calls_total", "LLM calls made by graph nodes", ["node"])
HANDOFFS = Counter("agent_handoffs_total", "Tickets handed off, by reason code", ["reason"])


class Span(Protocol):
    def end_with(self, output: dict[str, Any], *, level: str | None = None) -> None: ...
    def generation(
        self, *, model: str, calls: int, tokens: int, cost_usd: float, prompt: str | None
    ) -> None: ...


class Tracer(Protocol):
    def span(self, run_id: str, ticket_id: str, node: str, summary: dict[str, Any]) -> Any: ...
    def flush(self) -> None: ...


@dataclass
class _NoSpan:
    outputs: list[dict[str, Any]] = field(default_factory=list)

    def end_with(self, output: dict[str, Any], *, level: str | None = None) -> None:
        self.outputs.append(output)

    def generation(
        self, *, model: str, calls: int, tokens: int, cost_usd: float, prompt: str | None
    ) -> None:
        return None


class NoTracer:
    """Tracing off (no Langfuse keys) or in unit tests; keeps what it was given."""

    def __init__(self) -> None:
        self.spans: list[tuple[str, dict[str, Any], _NoSpan]] = []

    @contextmanager
    def span(
        self, run_id: str, ticket_id: str, node: str, summary: dict[str, Any]
    ) -> Iterator[_NoSpan]:
        s = _NoSpan()
        self.spans.append((node, summary, s))
        yield s

    def flush(self) -> None:
        return None


class _LfSpan:
    def __init__(self, obs: Any) -> None:
        self.obs = obs
        self.output: dict[str, Any] = {}
        self.level: str | None = None

    def end_with(self, output: dict[str, Any], *, level: str | None = None) -> None:
        self.output, self.level = output, level

    def generation(
        self, *, model: str, calls: int, tokens: int, cost_usd: float, prompt: str | None
    ) -> None:
        gen = self.obs.start_observation(
            name="llm",
            as_type="generation",
            model=model,
            metadata={"calls": calls, "prompt": prompt},
            usage_details={"total": tokens},
            cost_details={"total": cost_usd},
        )
        gen.end()


class LangfuseTracer:
    def __init__(self, public_key: str, secret_key: str, host: str) -> None:
        from langfuse import Langfuse

        self.lf = Langfuse(public_key=public_key, secret_key=secret_key, host=host)

    def trace_id(self, run_id: str, ticket_id: str) -> str:
        return str(self.lf.create_trace_id(seed=f"{run_id}:{ticket_id}"))

    @contextmanager
    def span(
        self, run_id: str, ticket_id: str, node: str, summary: dict[str, Any]
    ) -> Iterator[_LfSpan]:
        with self.lf.start_as_current_observation(
            name=node,
            as_type="span",
            trace_context={"trace_id": self.trace_id(run_id, ticket_id)},
            input=summary,
            metadata={"run_id": run_id, "ticket_id": ticket_id},
        ) as obs:
            span = _LfSpan(obs)
            yield span
            obs.update(output=span.output, level=span.level)  # type: ignore[arg-type]

    def flush(self) -> None:
        self.lf.flush()
