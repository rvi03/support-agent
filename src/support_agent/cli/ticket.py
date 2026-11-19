"""`make ticket FILE=<ticket json> [AS=mock-store-<id>]` (S12 build step 8).

A thin client of the API, logged in as a scripted mock user (client credentials,
D52; no password grant). It posts the ticket through ordinary intake, polls
`GET /tickets/{id}` every 2 s, and on a pause either asks on the terminal or answers
from the file's `script`:

- a store reply or a Clarify answer as the store user;
- an approval as `mock-l2` (or `mock-vendor` for a vendor card), an L2 task as
  `mock-l2`; that second client's token is fetched on demand.

At the end it prints the outcome: route, priority, status, messages, actions, walk
steps and the audit summary. `OUTCOME_FILE` also writes the final ticket view as
JSON (the CP12.1 test compares it with the stored rows).

The file is either a plain ticket body, or `{"as", "ticket", "script", "expected"}`.
With `expected`, the run fails (exit 1) unless the route, the first walk step and
the final status match.
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from support_agent.platform.mock_secrets import mock_client_secret

POLL_S = 2.0
DONE = ("done", "failed")


class CliSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", frozen=True)

    api_url: str = "http://localhost:8000"
    keycloak_issuer: str
    keycloak_token_url: str | None = None
    mock_client_secret_key: SecretStr
    ticket_timeout_s: float = 900.0

    @property
    def token_url(self) -> str:
        return self.keycloak_token_url or self.keycloak_issuer + "/protocol/openid-connect/token"


@dataclass
class Session:
    """One mock user's token, fetched by client credentials and refreshed when old."""

    s: CliSettings
    client_id: str
    http: httpx.Client
    _token: str | None = None
    _expires: float = 0.0

    def token(self) -> str:
        if not self._token or time.time() >= self._expires:
            secret = mock_client_secret(self.s.mock_client_secret_key.get_secret_value(),
                                        self.client_id)  # fmt: skip
            r = self.http.post(self.s.token_url, data={
                "grant_type": "client_credentials", "client_id": self.client_id,
                "client_secret": secret,
            })  # fmt: skip
            r.raise_for_status()
            body = r.json()
            self._token = str(body["access_token"])
            self._expires = time.time() + max(float(body.get("expires_in", 60)) - 30, 5)
        return self._token

    def call(self, method: str, path: str, body: dict[str, Any] | None = None) -> httpx.Response:
        return self.http.request(method, self.s.api_url + path, json=body,
                                 headers={"Authorization": f"Bearer {self.token()}"})  # fmt: skip


@dataclass
class Script:
    """Scripted answers per pause kind; `ask` is used for anything not scripted."""

    raw: dict[str, Any] = field(default_factory=dict)
    answers: list[str] = field(default_factory=list)
    ask: Callable[[str], str] = input

    def store(self, view: dict[str, Any]) -> str:
        if self.answers:
            return self.answers.pop(0)
        ran = any(s.get("kind") == "action" for s in (view.get("walk") or {}).get("steps", []))
        key = "store_reply_after_action" if ran else "store_reply_before_action"
        if key in self.raw:
            return str(self.raw[key])
        if "answer" in self.raw and (view.get("pending") or {}).get("kind") == "answer":
            return str(self.raw["answer"])
        return self.ask("store reply> ")

    def decide(self, kind: str) -> str:
        if self.answers:
            return self.answers.pop(0)
        if kind in self.raw:
            return str(self.raw[kind])
        prompt = "approve | reject: <reason>" if kind == "approval" else "done | failed: <note>"
        return self.ask(f"{kind} ({prompt})> ")


def approval_body(kind: str, pending_id: str, answer: str) -> dict[str, Any]:
    head, _, rest = answer.partition(":")
    head, rest = head.strip().lower(), rest.strip()
    if kind == "approval":
        decision = "reject" if head.startswith("reject") else "approve"
        return {"pending_id": pending_id, "decision": decision, "reason": rest or None}
    decision = "failed" if head.startswith("fail") else "done"
    return {"pending_id": pending_id, "decision": decision, "result": rest or None}


def load(path: Path) -> tuple[str | None, dict[str, Any], dict[str, Any], dict[str, Any]]:
    data = json.loads(path.read_text())
    if "ticket" in data:
        return data.get("as"), data["ticket"], data.get("script", {}), data.get("expected", {})
    return None, data, {}, {}


def show(view: dict[str, Any], out: Callable[[str], None] = print) -> None:
    o = view.get("outcome") or {}
    out(f"\n== {view['ticket_id']} (run {view.get('run_id')})")
    out(f"route: {view.get('route') or o.get('route') or '-'}; status: {view.get('status')}; "
        f"priority: {view.get('priority') or '-'}; handoff reason: "
        f"{o.get('handoff_reason') or '-'}")  # fmt: skip
    out(f"runbook: {view.get('runbook_id') or (view.get('walk') or {}).get('runbook_id') or '-'}; "
        f"LLM calls {o.get('llm_calls', 0)}, tokens {o.get('tokens', 0)}, "
        f"cost ${o.get('cost_usd', 0.0):.4f}")  # fmt: skip
    for m in view.get("messages", []):
        out(f"store message [{m['kind']}]: {m['text']}")
    for a in view.get("actions", []):
        out(f"IT action {a['action_id']} ({a['tier']}, {a['autonomy_state_at_run']}): "
            f"{a['outcome']}: {a['result']}")  # fmt: skip
    walk = view.get("walk") or {}
    if walk:
        out("walk: " + ", ".join(f"{s['step_id']} ({s['kind']}: {s['outcome']})"
                                 for s in walk.get("steps", [])))  # fmt: skip
    audit = view.get("audit_summary") or {}
    out(
        f"audit: {audit.get('events', 0)} events; "
        + ", ".join(f"{k} x{v}" for k, v in sorted((audit.get("by_step") or {}).items()))
    )


def check(view: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    fails = []
    route = view.get("route") or (view.get("outcome") or {}).get("route")
    if "route" in expected and route != expected["route"]:
        fails.append(f"route {route} != {expected['route']}")
    steps = (view.get("walk") or {}).get("steps") or []
    first = steps[0]["step_id"] if steps else None
    if "first_step_in" in expected and first not in expected["first_step_in"]:
        fails.append(f"first step {first} not in {expected['first_step_in']}")
    if "status" in expected and view.get("status") != expected["status"]:
        fails.append(f"status {view.get('status')} != {expected['status']}")
    return fails


def run(path: Path, as_client: str | None = None, *, answers: list[str] | None = None,
        settings: CliSettings | None = None, out: Callable[[str], None] = print,
        ask: Callable[[str], str] = input, http: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        ) -> tuple[dict[str, Any], list[str]]:  # fmt: skip
    s = settings or CliSettings()
    client = http or httpx.Client(timeout=30.0)
    file_as, body, raw_script, expected = load(path)
    who = as_client or file_as or "mock-store-sw-0003"
    store = Session(s, who, client)
    others: dict[str, Session] = {}
    script = Script(raw_script, list(answers or []), ask)

    r = store.call("POST", "/tickets", body)
    if r.status_code != 202:
        raise SystemExit(f"POST /tickets: {r.status_code} {r.text}")
    ticket_id = r.json()["ticket_id"]
    out(f"posted {ticket_id} as {who}")
    deadline = time.monotonic() + s.ticket_timeout_s
    answered: set[str] = set()
    while True:
        view = store.call("GET", f"/tickets/{ticket_id}").raise_for_status().json()
        pending = view.get("pending")
        if pending and pending["pending_id"] not in answered:
            kind, pid = pending["kind"], pending["pending_id"]
            if kind in ("store_reply", "answer"):
                last = view["messages"][-1]["text"] if view.get("messages") else "?"
                out(f"\n[paused: {kind}] {last}")
                text = script.store(view)
                out(f"store> {text}")
                resp = store.call("POST", f"/tickets/{ticket_id}/reply",
                                  {"pending_id": pid, "text": text})  # fmt: skip
            else:
                role = pending.get("approver_role") if kind == "approval" else "l2_engineer"
                cid = "mock-vendor" if role == "vendor_approver" else "mock-l2"
                it = others.setdefault(cid, Session(s, cid, client))
                card = (it.call("GET", f"/tickets/{ticket_id}").json().get("pending") or {}).get(
                    "approval"
                ) or {}
                out(f"\n[paused: {kind}] as {cid}: {card.get('action_id') or pending['step_id']} "
                    f"({card.get('tier') or '-'}) {card.get('step') or ''}")  # fmt: skip
                answer = script.decide(kind)
                out(f"{cid}> {answer}")
                resp = it.call("POST", f"/tickets/{ticket_id}/approve",
                               approval_body(kind, pid, answer))  # fmt: skip
            if resp.status_code != 202:
                raise SystemExit(f"{kind}: {resp.status_code} {resp.text}")
            answered.add(pid)
        elif not pending and view["api_status"] in DONE:
            break
        if time.monotonic() > deadline:
            raise SystemExit(f"{ticket_id}: no outcome after {s.ticket_timeout_s:.0f} s")
        sleep(POLL_S)
    show(view, out)
    fails = check(view, expected)
    for f in fails:
        out(f"FAIL: {f}")
    if expected and not fails:
        out("PASS: route, first step and status match the fixture")
    if os.environ.get("OUTCOME_FILE"):
        Path(os.environ["OUTCOME_FILE"]).write_text(json.dumps(view, indent=1, default=str))
    return view, fails


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args or len(args) > 2:
        raise SystemExit("usage: python -m support_agent.cli.ticket FILE [CLIENT_ID]")
    answers = [a for a in os.environ.get("ANSWERS", "").split("\n") if a.strip()]
    _, fails = run(Path(args[0]), args[1] if len(args) == 2 and args[1] else None,
                   answers=answers)  # fmt: skip
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
