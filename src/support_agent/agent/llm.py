"""Agent-side chat client for the LiteLLM router (S8; design.md, LLM).

- Every call names an alias (`agent`), never a model (D62).
- `TicketBudget` counts LLM calls and tokens per ticket (reasoning tokens are
  billed as output and count too, D65); a call past either limit raises
  `BudgetExceeded` before it is sent.
- Transport faults, 429 and 5xx are retried with backoff; still failing raises
  `LlmUnavailable` (the graph hands off with `llm_unavailable`).
"""

from __future__ import annotations

import asyncio
import copy
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

RETRIES = 2
BACKOFF_S = 1.0
TIMEOUT_S = 120.0


class LlmUnavailable(RuntimeError):  # noqa: N818 - the design's name
    pass


class BudgetExceeded(RuntimeError):  # noqa: N818 - the design's name
    pass


class InvalidOutput(RuntimeError):  # noqa: N818 - the design's name
    pass


@dataclass
class TicketBudget:
    max_calls: int
    max_tokens: int
    calls: int = 0
    tokens: int = 0
    latency_s: float = 0.0
    cost_usd: float = 0.0  # LiteLLM's x-litellm-response-cost per call (K14)

    def check(self) -> None:
        if self.calls >= self.max_calls:
            raise BudgetExceeded(f"llm calls {self.calls} >= {self.max_calls}")
        if self.tokens >= self.max_tokens:
            raise BudgetExceeded(f"tokens {self.tokens} >= {self.max_tokens}")


@dataclass
class Reply:
    message: dict[str, Any]
    usage: dict[str, Any] = field(default_factory=dict)
    cost_usd: float = 0.0
    model: str | None = None


def strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """A Pydantic JSON schema made fit for strict structured output: no titles,
    defaults or numeric bounds (Pydantic re-checks them), every object closed
    with all its properties required."""
    out = copy.deepcopy(schema)

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key in ("title", "default", "minimum", "maximum", "minLength", "maxLength"):
                node.pop(key, None)
            if node.get("type") == "object" and "properties" in node:
                node["additionalProperties"] = False
                node["required"] = list(node["properties"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(out)
    return out


class ChatClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        model: str = "agent",
        transport: httpx.AsyncBaseTransport | None = None,
        retries: int = RETRIES,
        backoff: float = BACKOFF_S,
    ) -> None:
        self.model, self.retries, self.backoff = model, retries, backoff
        self._http = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=TIMEOUT_S,
            transport=transport,
        )

    async def complete(
        self,
        messages: list[dict[str, Any]],
        budget: TicketBudget,
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        reasoning_effort: str = "minimal",
        response_format: dict[str, Any] | None = None,
    ) -> Reply:
        budget.check()
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "reasoning_effort": reasoning_effort,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = tool_choice or "required"
        if metadata:
            body["metadata"] = metadata
        if response_format:
            body["response_format"] = response_format
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            started = time.monotonic()
            try:
                response = await self._http.post("/v1/chat/completions", json=body)
                if response.status_code == 429 or response.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        f"http {response.status_code}", request=response.request, response=response
                    )
                response.raise_for_status()
                data = response.json()
                message = data["choices"][0]["message"]
            except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
                last = exc
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500:
                    if exc.response.status_code != 429:
                        break
                if attempt < self.retries:
                    await asyncio.sleep(self.backoff * 2**attempt)
                continue
            finally:
                budget.latency_s += time.monotonic() - started
            usage = data.get("usage") or {}
            try:
                cost = float(response.headers.get("x-litellm-response-cost") or 0.0)
            except ValueError:
                cost = 0.0
            budget.calls += 1
            budget.tokens += int(usage.get("total_tokens") or 0)
            budget.cost_usd += cost
            return Reply(message=message, usage=usage, cost_usd=cost, model=data.get("model"))
        raise LlmUnavailable(f"{type(last).__name__}: {last}") from last

    async def structured[M: BaseModel](
        self,
        system: str,
        data: str,
        model: type[M],
        budget: TicketBudget,
        *,
        name: str,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[M, Reply]:
        """One call with a strict JSON schema; an invalid reply raises `InvalidOutput`."""
        reply = await self.complete(
            [{"role": "system", "content": system}, {"role": "user", "content": data}],
            budget,
            metadata=metadata,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": name,
                    "schema": strict_schema(model.model_json_schema()),
                    "strict": True,
                },
            },
        )
        try:
            return model.model_validate_json(reply.message.get("content") or ""), reply
        except ValidationError as exc:
            raise InvalidOutput(str(exc.errors(include_url=False))[:500]) from exc

    async def aclose(self) -> None:
        await self._http.aclose()
