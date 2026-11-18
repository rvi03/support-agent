"""it-data MCP server against the running platform (S5: CP5.1, CP5.2, CP5.3).

Calls go through the agent-side client with a real Keycloak token, so each
call also passes the JWT check, the scope, OPA P7 and the audit write. The
results here are checked unmasked (pass-through guard): the guard is tested in
tests/unit/test_agent_tools.py.
"""

from __future__ import annotations

import asyncio
import subprocess
import uuid
from collections.abc import Iterator
from datetime import datetime, timedelta
from typing import Any

import httpx
import psycopg
import pytest

from support_agent.agent.tools import McpToolClient, TokenSource, ToolCallError
from support_agent.ingest.csv_clean import split_system_version
from support_agent.mcp.base.errors import ErrorCode
from support_agent.platform.mock_secrets import mock_client_secret
from tests.integration.platform_env import ROOT, load_env, superuser_url

pytestmark = pytest.mark.integration

ISSUER = "http://localhost:8080/realms/servewell"
URL = "http://localhost:8101/mcp"
COMPOSE = [
    "docker", "compose", "--project-name", "servewell", "--env-file", str(ROOT / ".env"),
    "-f", str(ROOT / "compose" / "compose.yaml"),
]  # fmt: skip
LEAKING_KEYS = {"status", "resolution_notes", "ticket_history"}


@pytest.fixture(scope="module")
def env() -> dict[str, str]:
    return load_env()


@pytest.fixture(scope="module")
def db(env: dict[str, str]) -> Iterator[psycopg.Connection[Any]]:
    with psycopg.connect(superuser_url(env), autocommit=True) as conn:
        yield conn


def reader(env: dict[str, str]) -> McpToolClient:
    tokens = TokenSource(ISSUER, "agent-reader", env["KEYCLOAK_SECRET_AGENT_READER"])
    return McpToolClient(URL, tokens, lambda data, _ticket: data)


def call(env: dict[str, str], tool: str, ticket: str | None = None, **args: Any) -> dict[str, Any]:
    clean = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in args.items()}
    return asyncio.run(reader(env).call(tool, clean, ticket_id=ticket))


def ticket(db: psycopg.Connection[Any], ticket_id: str) -> dict[str, Any]:
    cur = db.execute(
        "SELECT ticket_id, store_id, date_opened, asset_id, system_version, priority, category "
        "FROM tickets.source_tickets WHERE ticket_id = %s",
        (ticket_id,),
    )
    names = [c.name for c in cur.description or []]
    row = cur.fetchone()
    assert row, ticket_id
    return dict(zip(names, row, strict=True))


def last_audit_id(db: psycopg.Connection[Any]) -> int:
    return int(db.execute("SELECT coalesce(max(id), 0) FROM audit.events").fetchone()[0])  # type: ignore[index]


def audit_since(db: psycopg.Connection[Any], since: int) -> list[tuple[Any, ...]]:
    return db.execute(
        "SELECT actor, action, result, reason, ticket_id FROM audit.events "
        "WHERE id > %s AND step = 'mcp.it_data' ORDER BY id",
        (since,),
    ).fetchall()


# ---- CP5.1 known tickets ---------------------------------------------------------------


def test_warranty_is_as_of_date_opened(env: dict[str, str], db: psycopg.Connection[Any]) -> None:
    # INC-00060 is opened on its asset's last warranty day; INC-00114 three days after.
    inside, outside = ticket(db, "INC-00060"), ticket(db, "INC-00114")
    a = call(
        env, "get_asset", "INC-00060", asset_id=inside["asset_id"], as_of=inside["date_opened"]
    )
    b = call(
        env, "get_asset", "INC-00114", asset_id=outside["asset_id"], as_of=outside["date_opened"]
    )
    assert (a["status"], a["asset"]["in_warranty"], a["asset"]["warranty_days_left"]) == (
        "found",
        True,
        0,
    )
    assert (b["status"], b["asset"]["in_warranty"]) == ("found", False)
    # The same asset either side of its warranty_end.
    day_after = inside["date_opened"] + timedelta(days=1)
    c = call(env, "get_asset", asset_id=inside["asset_id"], as_of=day_after)
    assert c["asset"]["in_warranty"] is False


def test_sla_falls_back_to_general(env: dict[str, str], db: psycopg.Connection[Any]) -> None:
    t = ticket(db, "INC-00014")
    own = call(
        env, "get_sla", priority=t["priority"], category=t["category"], date_opened=t["date_opened"]
    )
    assert (own["status"], own["category_used"]) == ("found", t["category"])
    other = call(env, "get_sla", priority="P2", category="Facilities", date_opened=t["date_opened"])
    general = db.execute(
        "SELECT escalation_to_l2_minutes FROM data.sla_matrix "
        "WHERE priority = 'P2' AND category = 'General'"
    ).fetchone()
    assert (other["status"], other["category_used"]) == ("fallback_general", "General")
    escalate_by = other["escalate_by"].replace("Z", "+00:00")
    assert datetime.fromisoformat(escalate_by) - t["date_opened"] == timedelta(minutes=general[0])  # type: ignore[index]
    none = call(env, "get_sla", priority="P3", date_opened=t["date_opened"])
    assert none["status"] == "fallback_general"


def test_unknown_system(env: dict[str, str], db: psycopg.Connection[Any]) -> None:
    t = ticket(db, "INC-00014")
    system, version = split_system_version(t["system_version"])
    out = call(env, "get_known_bug", "INC-00014", system=system, version=version)
    assert out["status"] == "unknown_system"
    known = call(env, "get_known_bug", system="FoodTech POS", version="4.2.1")
    assert (known["status"], known["version"], known["patch_status"]) == ("found", "v4.2.1", "Yes")
    assert (
        call(env, "get_known_bug", system="FoodTech POS", version="v9.9")["status"]
        == "unknown_version"
    )


def test_asset_not_found(env: dict[str, str], db: psycopg.Connection[Any]) -> None:
    t = ticket(db, "INC-00011")
    out = call(env, "get_asset", "INC-00011", asset_id=t["asset_id"], as_of=t["date_opened"])
    assert out == {"status": "not_found", "asset": None}


def test_wrong_asset_type_is_returned_as_is(
    env: dict[str, str], db: psycopg.Connection[Any]
) -> None:
    # INC-00045 is a Soft Serve ticket on a router; Enrich flags the mismatch (S8).
    t = ticket(db, "INC-00045")
    out = call(env, "get_asset", "INC-00045", asset_id=t["asset_id"], as_of=t["date_opened"])
    assert out["asset"]["asset_type"] == "Network Router"
    assert t["category"] == "Soft Serve"


def test_store_has_no_contact_fields(env: dict[str, str]) -> None:
    out = call(env, "get_store", store_id="SW-0037")
    assert out["status"] == "found"
    assert set(out["store"]) == {"store_id", "store_name", "store_type", "city", "neighborhood"}
    assert call(env, "get_store", store_id="SW-9999")["status"] == "not_found"
    assets = call(env, "get_store_assets", store_id="SW-0037")
    assert assets["status"] == "found" and assets["assets"]


def test_every_call_is_audited(env: dict[str, str], db: psycopg.Connection[Any]) -> None:
    since = last_audit_id(db)
    call(env, "get_store", "INC-00014", store_id="SW-0037")
    with pytest.raises(ToolCallError):
        call(env, "get_store", "INC-00014", store_id="not-a-store")
    rows = audit_since(db, since)
    assert [(r[0], r[1], r[2], r[4]) for r in rows] == [
        ("agent-reader", "get_store", "found", "INC-00014"),
        ("agent-reader", "get_store", "invalid", "INC-00014"),
    ]


# ---- CP5.2 history never leaks ---------------------------------------------------------


def _keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in _keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in _keys(v)}
    return set()


def test_history_tools_over_all_256(env: dict[str, str], db: psycopg.Connection[Any]) -> None:
    rows = db.execute(
        "SELECT ticket_id, store_id, asset_id, date_opened, related_tickets "
        "FROM tickets.source_tickets ORDER BY ticket_id"
    ).fetchall()
    assert len(rows) == 256
    opened = {r[0]: r[3] for r in rows}
    client = reader(env)

    async def check_all() -> tuple[int, int]:
        returned = cited = 0
        for ticket_id, store_id, asset_id, before, related in rows:
            args = {"store_id": store_id, "before": before.isoformat(), "limit": 20}
            if asset_id:
                args["asset_id"] = asset_id
            recent = await client.call("get_recent_tickets", args, ticket_id=ticket_id)
            assert not (_keys(recent) - {"status"}) & LEAKING_KEYS
            assert not any("status" in t for t in recent["tickets"])
            for t in recent["tickets"]:
                assert opened[t["ticket_id"]] < before, (ticket_id, t["ticket_id"])
                assert t["store_id"] == store_id or t["asset_id"] == asset_id
                returned += 1
            own = await client.call(
                "get_ticket", {"ticket_id": ticket_id, "before": before.isoformat()}
            )
            assert own == {"status": "not_found", "ticket": None}
            for cited_id in related:
                got = await client.call(
                    "get_ticket", {"ticket_id": cited_id, "before": before.isoformat()}
                )
                assert not (_keys(got) - {"status"}) & LEAKING_KEYS
                earlier = cited_id in opened and opened[cited_id] < before
                assert got["status"] == ("found" if earlier else "not_found")
                cited += 1
        return returned, cited

    returned, cited = asyncio.run(check_all())
    assert returned > 0 and cited > 0


# ---- CP5.3 refused and audited ---------------------------------------------------------


def _token(client_id: str, secret: str) -> str:
    response = httpx.post(
        f"{ISSUER}/protocol/openid-connect/token",
        data={"grant_type": "client_credentials", "client_id": client_id, "client_secret": secret},
        timeout=10,
    )
    response.raise_for_status()
    return str(response.json()["access_token"])


def _post(token: str | None) -> int:
    headers = {"content-type": "application/json", "accept": "application/json, text/event-stream"}
    if token:
        headers["authorization"] = f"Bearer {token}"
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    return httpx.post(URL, json=body, headers=headers, timeout=10).status_code


def test_refused_tokens_are_audited(env: dict[str, str], db: psycopg.Connection[Any]) -> None:
    actor = _token("agent-actor", env["KEYCLOAK_SECRET_AGENT_ACTOR"])  # itsm audience and scopes
    l2 = _token("mock-l2", mock_client_secret(env["MOCK_CLIENT_SECRET_KEY"], "mock-l2"))
    reader_token = _token("agent-reader", env["KEYCLOAK_SECRET_AGENT_READER"])
    tampered = reader_token[:-4] + ("AAAA" if not reader_token.endswith("AAAA") else "BBBB")
    cases = [
        (None, "no_token"),
        (actor, "wrong_audience"),
        (l2, "wrong_audience"),
        (tampered, "invalid_token"),
    ]
    for token, reason in cases:
        since = last_audit_id(db)
        assert _post(token) == 401, reason
        rows = audit_since(db, since)
        assert [(r[1], r[2], r[3]) for r in rows] == [("auth", "denied", reason)], reason
    # Expired, missing scope with the right audience and an audience of `knowledge`
    # can't be issued by this realm: tests/unit/test_mcp_base.py signs those.


def test_opa_down_fails_closed(env: dict[str, str], db: psycopg.Connection[Any]) -> None:
    subprocess.run([*COMPOSE, "stop", "opa"], check=True, capture_output=True)
    try:
        since = last_audit_id(db)
        with pytest.raises(ToolCallError) as err:
            call(env, "get_store", f"INC-OPA-{uuid.uuid4().hex[:6]}", store_id="SW-0037")
        assert (err.value.code, err.value.reason) == (ErrorCode.DENIED, "opa:opa_unavailable")
        rows = audit_since(db, since)
        assert [(r[0], r[1], r[2], r[3]) for r in rows] == [
            ("agent-reader", "get_store", "denied", "opa:opa_unavailable")
        ]
    finally:
        subprocess.run([*COMPOSE, "up", "-d", "--wait", "opa"], check=True, capture_output=True)
    assert call(env, "get_store", store_id="SW-0037")["status"] == "found"


# ---- agent-side guard over real results ------------------------------------------------


def test_real_guard_passes_every_result_unchanged(
    env: dict[str, str], db: psycopg.Connection[Any]
) -> None:
    """Every it-data result for the 256 tickets goes through the real masker and
    safety net: nothing is blocked, typed fields stay intact, and each result still
    parses into its model (Presidio read `not_found` as a name before the fix)."""
    from support_agent.agent.tools import ItDataClient, ResultGuard
    from support_agent.intake.masker import Masker
    from support_agent.intake.reference import load_reference
    from support_agent.intake.safety_net import SafetyNet

    with psycopg.connect(env["DATABASE_URL_INTAKE"]) as conn:
        reference = load_reference(conn)
    blocked: list[Any] = []
    guard = ResultGuard(Masker(reference), SafetyNet(reference, blocked.append, actor="test"))
    tokens = TokenSource(ISSUER, "agent-reader", env["KEYCLOAK_SECRET_AGENT_READER"])
    client = McpToolClient(URL, tokens, guard)
    rows = db.execute(
        "SELECT ticket_id, store_id, asset_id, date_opened FROM tickets.source_tickets"
    ).fetchall()

    async def run() -> int:
        n = 0
        for ticket_id, store_id, asset_id, opened in rows:
            it = ItDataClient(client, ticket_id=ticket_id)
            store = await it.get_store(store_id)
            recent = await it.get_recent_tickets(opened, store_id=store_id, asset_id=asset_id)
            assert store.status == "found" and recent.status in ("found", "none")
            n += 2
            if asset_id:
                asset = await it.get_asset(asset_id, opened)
                assert asset.status in ("found", "not_found")
                n += 1
        return n

    assert asyncio.run(run()) > 512
    assert blocked == []
