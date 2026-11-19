"""CP8.1: Enrich gives the right facts and flags on the edge-case tickets (S8, S8a).

S8a: Enrich flags only data comparisons (asset missing, unknown system, version
mismatch); E2/E3 (device not at the store, wrong asset type) are facts Triage
judges, so here the facts that let it judge are asserted.

Tune-half tickets only (D39). Every real E2/E3 ticket in the data is also E2,
so E3 alone and the version mismatch alone are synthetic tickets built from
the tune-half row INC-00017 (store SW-0116 holds every device type).
Calls go to the running it-data server as `agent-reader`; results pass
through unmasked (the guard is tested in test_agent_tools.py).
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest

from support_agent.agent.nodes.enrich import enrich
from support_agent.agent.state import Facts, Flag
from support_agent.agent.tools import ItDataClient, McpToolClient, TokenSource
from support_agent.intake.schema import MaskedTicket
from tests.integration.platform_env import load_env, superuser_url

pytestmark = pytest.mark.integration

ISSUER = "http://localhost:8080/realms/servewell"
URL = "http://localhost:8101/mcp"
COLUMNS = (
    "ticket_id, store_id, date_opened, subject, description, store_name, priority, category, "
    "subcategory, asset_id, system_version, tags, escalation_flag, related_tickets"
)


@pytest.fixture(scope="module")
def env() -> dict[str, str]:
    return load_env()


@pytest.fixture(scope="module")
def db(env: dict[str, str]) -> Iterator[psycopg.Connection[Any]]:
    with psycopg.connect(superuser_url(env), autocommit=True) as conn:
        yield conn


def masked(db: psycopg.Connection[Any], ticket_id: str) -> MaskedTicket:
    cur = db.execute(
        f"SELECT {COLUMNS} FROM tickets.source_tickets WHERE ticket_id = %s",  # noqa: S608
        (ticket_id,),
    )
    row = cur.fetchone()
    assert row, ticket_id
    data = dict(zip([c.name for c in cur.description or []], row, strict=True))
    return MaskedTicket(**{k: v for k, v in data.items() if v is not None})


def run(env: dict[str, str], ticket: MaskedTicket) -> Facts:
    tokens = TokenSource(ISSUER, "agent-reader", env["KEYCLOAK_SECRET_AGENT_READER"])
    client = McpToolClient(URL, tokens, lambda data, _ticket: data)
    return asyncio.run(enrich(ticket, ItDataClient(client, ticket_id=ticket.ticket_id)))


def test_e2_e3_soft_serve_at_store_without_machine(env: dict[str, str], db: Any) -> None:
    facts = run(env, masked(db, "INC-00053"))
    assert facts.flags == []
    assert facts.asset is not None and facts.asset.asset_type == "Network Router"
    assert "Soft Serve Machine" not in {a.asset_type for a in facts.store_assets}


def test_e3_alone_wrong_asset_at_store_with_the_device(env: dict[str, str], db: Any) -> None:
    clean = run(env, masked(db, "INC-00017"))
    assert clean.flags == []
    ticket = masked(db, "INC-00017").model_copy(
        update={"asset_id": "RTR-0116-01", "system_version": None}
    )
    facts = run(env, ticket)
    assert facts.flags == []
    assert facts.asset is not None and facts.asset.asset_type == "Network Router"
    assert "Soft Serve Machine" in {a.asset_type for a in facts.store_assets}


def test_e4_asset_not_found(env: dict[str, str], db: Any) -> None:
    facts = run(env, masked(db, "INC-00180"))
    assert facts.flags == [Flag.ASSET_NOT_FOUND]
    assert facts.asset is None and facts.known_bug_cmdb is None
    assert facts.known_bug_ticket is not None and facts.known_bug_ticket.status == "found"


def test_e5_unknown_system_with_a_real_asset(env: dict[str, str], db: Any) -> None:
    facts = run(env, masked(db, "INC-00014"))
    assert facts.flags == [Flag.UNKNOWN_SYSTEM, Flag.VERSION_MISMATCH]
    assert facts.known_bug_ticket is not None
    assert facts.known_bug_ticket.status == "unknown_system"
    assert facts.known_bug_ticket.system == "KitchenBridge"
    assert facts.asset is not None and facts.asset.system_version == "NetLink NL-3000 v2.2"
    assert facts.known_bug_cmdb is not None and facts.known_bug_cmdb.status == "found"


def test_version_mismatch_alone(env: dict[str, str], db: Any) -> None:
    ticket = masked(db, "INC-00017").model_copy(update={"system_version": "FrostyPro 800 v2.0"})
    facts = run(env, ticket)
    assert facts.flags == [Flag.VERSION_MISMATCH]
    assert facts.known_bug_cmdb is not None and facts.known_bug_cmdb.version == "v1.8"
    assert facts.known_bug_cmdb.known_bug  # the CMDB version has the known bug
    assert facts.known_bug_ticket is not None and facts.known_bug_ticket.version == "v2.0"
    assert facts.known_bug_ticket.known_bug is None


def test_facts_sla_and_history(env: dict[str, str], db: Any) -> None:
    ticket = masked(db, "INC-00017")
    facts = run(env, ticket)
    assert facts.store is not None and facts.store.store_id == "SW-0116"
    assert facts.priority_used == ticket.priority
    assert facts.sla.priority == ticket.priority
    assert facts.sla.escalate_by > ticket.date_opened
    assert facts.recent_tickets, "SW-0116 has earlier tickets"
    assert all(t.date_opened < ticket.date_opened for t in facts.recent_tickets)
