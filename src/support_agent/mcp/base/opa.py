"""Ask OPA before every tool call (D27; S5 build step 1).

Every server asks the single P10 default-deny decision. A 1 s timeout; if OPA
can't be reached or answers something unexpected, the call is denied (fail
closed).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

DECISION_PATH = "/v1/data/servewell/p10_default_deny"
TIMEOUT_SECONDS = 1.0


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str


class OpaClient:
    def __init__(self, base_url: str, *, timeout: float = TIMEOUT_SECONDS) -> None:
        self.url = base_url.rstrip("/") + DECISION_PATH
        self._http = httpx.AsyncClient(timeout=timeout)

    async def allow(self, policy_input: dict[str, Any]) -> Decision:
        try:
            response = await self._http.post(self.url, json={"input": policy_input})
            response.raise_for_status()
            result = response.json().get("result")
        except (httpx.HTTPError, ValueError):
            return Decision(False, "opa_unavailable")
        if not isinstance(result, dict):
            return Decision(False, "opa_no_decision")
        allowed = result.get("allow") is True
        return Decision(allowed, str(result.get("reason") or ("allowed" if allowed else "denied")))

    async def aclose(self) -> None:
        await self._http.aclose()
