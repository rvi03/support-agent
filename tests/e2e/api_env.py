"""Helpers for tests against the running API (`make up`, S12).

Real mock-user tokens (client credentials, D52), never stubs. `API_URL` overrides
the API address (default http://localhost:8000).
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from functools import cache
from pathlib import Path
from typing import Any

import httpx
import psycopg

from support_agent.platform.mock_secrets import mock_client_secret
from tests.integration.platform_env import ROOT, load_env, superuser_url

API_URL = os.environ.get("API_URL", "http://localhost:8000")
TOKEN_URL = "http://localhost:8080/realms/servewell/protocol/openid-connect/token"  # noqa: S105


@cache
def token(client_id: str) -> str:
    env = load_env()
    if client_id.startswith("mock-"):
        secret = mock_client_secret(env["MOCK_CLIENT_SECRET_KEY"], client_id)
    else:
        secret = env[f"KEYCLOAK_SECRET_{client_id.upper().replace('-', '_')}"]
    r = httpx.post(TOKEN_URL, data={"grant_type": "client_credentials", "client_id": client_id,
                                    "client_secret": secret})  # fmt: skip
    r.raise_for_status()
    return str(r.json()["access_token"])


@dataclass
class As:
    client_id: str | None  # None: no token

    def call(self, method: str, path: str, body: Any = None, **kw: Any) -> httpx.Response:
        headers = {"Authorization": f"Bearer {token(self.client_id)}"} if self.client_id else {}
        headers |= kw.pop("headers", {})
        return httpx.request(method, API_URL + path, json=body, headers=headers, timeout=30, **kw)


def wait_for(get: Callable[[], dict[str, Any]], until: Callable[[dict[str, Any]], bool],
             timeout: float = 300.0) -> dict[str, Any]:  # fmt: skip
    deadline = time.monotonic() + timeout
    while True:
        view = get()
        if until(view):
            return view
        if time.monotonic() > deadline:
            raise AssertionError(f"timed out; last view: {json.dumps(view, default=str)[:800]}")
        time.sleep(2)


def db() -> psycopg.Connection[Any]:
    return psycopg.connect(superuser_url(load_env()), autocommit=True)


def denials(since: datetime, *, action: str, status: int, actor: str | None = None,
            ticket_id: str | None = None) -> list[tuple[Any, ...]]:  # fmt: skip
    """The API's denial audit events since `since`."""
    q = ("SELECT actor, action, reason, payload FROM audit.events WHERE step = 'api' "
         "AND result = 'denied' AND ts >= %s AND action = %s "
         "AND (payload->>'status')::int = %s")  # fmt: skip
    params: list[Any] = [since, action, status]
    if actor:
        q += " AND actor = %s"
        params.append(actor)
    if ticket_id:
        q += " AND ticket_id = %s"
        params.append(ticket_id)
    with db() as conn:
        return list(conn.execute(q, params).fetchall())


def tune_ticket_ids() -> list[str]:
    split = json.loads((ROOT / "eval" / "split.json").read_text())
    return list(split["tune"]["labelled"])


def fixture(name: str) -> dict[str, Any]:
    return dict(json.loads((ROOT / "tests" / "fixtures" / name).read_text()))


def api_up() -> bool:
    try:
        return httpx.get(API_URL + "/health", timeout=3).status_code == 200
    except httpx.HTTPError:
        return False


__all__ = ["API_URL", "As", "Path", "api_up", "db", "denials", "fixture", "token",
           "tune_ticket_ids", "wait_for"]  # fmt: skip
