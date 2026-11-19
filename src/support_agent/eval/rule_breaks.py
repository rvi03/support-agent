"""S14 build step 8: OPA rule-break suite against the live API (D27, D132, CP14.5).

`make rule-breaks` creates one printer ticket as `mock-store-sw-0003`, waits for
its first pause, then sends calls that every rule must refuse; each must get its
expected status AND leave a `denied` audit event with a reason (pass = denied and
logged). The itsm-actions side (run_fix and approval rules) is covered by
tests/integration/test_itsm.py and `make opa-test`, which `make eval-suites` runs.
Writes eval/reports/rule_breaks.md.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import psycopg

from support_agent.cli.ticket import CliSettings
from support_agent.common.config import CheckerSettings, get_settings
from support_agent.common.db import dsn
from support_agent.eval.runner import Api, Token
from support_agent.platform.mock_secrets import mock_client_secret

ROOT = Path(__file__).resolve().parents[3]
REPORT = ROOT / "eval" / "reports" / "rule_breaks.md"
STORE, OTHER = "mock-store-sw-0003", "mock-store-sw-0007"
TICKET = {
    "category": "Printers", "priority": "P3", "asset_id": "PRN-0003-P1",
    "subject": "Rule-break probe: receipt printer offline",
    "description": "The receipt printer shows Offline on the POS since opening; nothing prints.",
}  # fmt: skip


@dataclass
class Probe:
    name: str
    who: str | None  # None = no token
    method: str
    path: str
    body: dict[str, Any] | None
    expect: tuple[int, ...]
    audit_action: str | None  # the denied event expected on this ticket


def probes(tid: str, pid: str) -> list[Probe]:
    t = f"/tickets/{tid}"
    big = {"pending_id": pid, "text": "x" * 70_000}
    return [
        Probe("P1 other store reads the ticket", OTHER, "GET", t, None, (404,), "api.get_ticket"),
        Probe("P1 other store replies", OTHER, "POST", f"{t}/reply",
              {"pending_id": pid, "text": "hi"}, (404,), "api.reply"),
        Probe("P3 store user approves", STORE, "POST", f"{t}/approve",
              {"pending_id": pid, "decision": "approve"}, (403,), "api.approve"),
        Probe("P2 L2 replies as the store", "mock-l2", "POST", f"{t}/reply",
              {"pending_id": pid, "text": "fixed"}, (403, 404), "api.reply"),
        Probe("P4 vendor approves a store pause", "mock-vendor", "POST", f"{t}/approve",
              {"pending_id": pid, "decision": "approve"}, (403, 404, 409), "api.approve"),
        Probe("P2 L1 approves", "mock-l1", "POST", f"{t}/approve",
              {"pending_id": pid, "decision": "approve"}, (403, 404, 409), "api.approve"),
        Probe("D53 stale pending id", STORE, "POST", f"{t}/reply",
              {"pending_id": str(uuid.uuid4()), "text": "done"}, (409,), "api.reply"),
        Probe("D52 store sends replay fields", STORE, "POST", "/tickets",
              {**TICKET, "source_ticket_id": "INC-99999"}, (422,), None),
        Probe("401 no token", None, "GET", t, None, (401,), None),
        Probe("413 oversized reply", STORE, "POST", f"{t}/reply", big, (413, 422), None),
    ]  # fmt: skip


async def call(api: Api, p: Probe) -> int:
    if p.who is None:
        r = await api.http.request(p.method, api.base + p.path, json=p.body)
    else:
        r = await api.call(p.who, p.method, p.path, p.body)
    return r.status_code


async def run() -> int:
    cli = CliSettings()
    key = cli.mock_client_secret_key.get_secret_value()
    async with httpx.AsyncClient(timeout=60.0) as http:
        api = Api(http, cli.api_url, {
            c: Token(http, cli.token_url, c, mock_client_secret(key, c))
            for c in (STORE, OTHER, "mock-l2", "mock-vendor", "mock-l1")
        })  # fmt: skip
        r = await api.call(STORE, "POST", "/tickets", TICKET)
        r.raise_for_status()
        tid = r.json()["ticket_id"]
        pid = None
        for _ in range(150):
            v = (await api.call(STORE, "GET", f"/tickets/{tid}")).json()
            if v.get("pending"):
                pid = v["pending"]["pending_id"]
                break
            if v.get("api_status") in ("done", "failed"):
                break
            await asyncio.sleep(2)
        if pid is None:
            raise SystemExit(f"{tid} never paused; route {v.get('route')}")
        results = [(p, await call(api, p)) for p in probes(tid, pid)]
    checker = get_settings(CheckerSettings)
    with psycopg.connect(dsn(checker.database_url_checker, checker.db_host)) as conn:
        denied = conn.execute(
            "SELECT action, reason FROM audit.events WHERE ticket_id = %s AND step = 'api' "
            "AND result = 'denied'",
            (tid,),
        ).fetchall()
    actions = [a for a, _ in denied]
    lines = ["# OPA rule-break suite (API)", "",
             f"Probe ticket `{tid}` (paused at `{pid}`); pass = expected status and, for a "
             "rule on the ticket, a `denied` audit event.", "",
             "| Probe | Status | Expected | Audited | Result |",
             "|---|---|---|---|---|"]  # fmt: skip
    fails = 0
    for p, status in results:
        audited = p.audit_action is None or p.audit_action in actions
        if p.audit_action in actions:
            actions.remove(p.audit_action)
        ok = status in p.expect and audited
        fails += not ok
        mark = "n/a" if not p.audit_action else ("yes" if audited else "**no**")
        lines.append(f"| {p.name} | {status} | {p.expect} | {mark} | "
                     f"{'pass' if ok else '**fail**'} |")  # fmt: skip
    lines += [
        "",
        f"**{len(results) - fails} of {len(results)} pass.**",
        "",
        "itsm-actions rules (run_fix binding, approvals, autonomy, closed ticket, "
        "deadline) are in tests/integration/test_itsm.py; policies in `make opa-test`.",
    ]
    REPORT.write_text("\n".join(lines) + "\n")
    print(f"{len(results) - fails}/{len(results)} pass -> eval/reports/rule_breaks.md")
    return 1 if fails else 0


def main(argv: list[str]) -> int:
    return asyncio.run(run())


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
