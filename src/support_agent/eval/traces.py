"""Read a ticket run's Langfuse trace back (CP10.3 PII scan, CP10.5 K14 first look).

Langfuse v4 serves observations at `/api/public/v2/observations` (the v1 trace
endpoints are gone); the trace id is the one the agent derives from
`run_id:ticket_id` (agent/observe.py). Ingestion is asynchronous, so `observations`
waits until a span with the wanted name has landed.
"""

from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from langfuse import Langfuse

FIELDS = "core,basic,io,metadata,usage"


class TraceMissingError(RuntimeError):
    pass


@dataclass(frozen=True)
class LangfuseReader:
    host: str
    public_key: str
    secret_key: str

    def _get(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        auth = base64.b64encode(f"{self.public_key}:{self.secret_key}".encode()).decode()
        url = f"{self.host.rstrip('/')}{path}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"Authorization": f"Basic {auth}"})  # noqa: S310
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310 - local Langfuse
            data: dict[str, Any] = json.loads(resp.read())
        return data

    def observations(
        self, run_id: str, ticket_id: str, *, wait_for: str | None = None, timeout_s: float = 90
    ) -> list[dict[str, Any]]:
        trace_id = Langfuse.create_trace_id(seed=f"{run_id}:{ticket_id}")
        deadline = time.monotonic() + timeout_s
        while True:
            rows: list[dict[str, Any]] = []
            cursor: str | None = None
            while True:
                params = {"traceId": trace_id, "fields": FIELDS, "limit": "100"}
                if cursor:
                    params["cursor"] = cursor
                page = self._get("/api/public/v2/observations", params)
                rows += page.get("data", [])
                cursor = (page.get("meta") or {}).get("cursor")
                if not cursor:
                    break
            if rows and (wait_for is None or any(r.get("name") == wait_for for r in rows)):
                return rows
            if time.monotonic() > deadline:
                raise TraceMissingError(f"trace {trace_id} has no {wait_for or 'observation'}")
            time.sleep(3)
