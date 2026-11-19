"""S8: agent_actor builds its masker reference and reads nothing more (009_agent.sql, D92)."""

from __future__ import annotations

import psycopg
import pytest

from support_agent.intake.reference import load_agent_reference
from tests.integration.platform_env import load_env

pytestmark = pytest.mark.integration


def _agent() -> psycopg.Connection[tuple[object, ...]]:
    return psycopg.connect(load_env()["DATABASE_URL_AGENT"], autocommit=True)


def test_agent_reference_loads_places_devices_and_ids() -> None:
    with _agent() as conn:
        ref = load_agent_reference(conn)
    assert ref.known_names == frozenset()
    assert ref.is_never_mask("SW-0001") and ref.is_never_mask("Soft Serve")


@pytest.mark.parametrize(
    "query",
    [
        "SELECT region_manager FROM data.stores",
        "SELECT support_phone FROM data.stores",
        "SELECT submitted_by FROM tickets.source_staging",
        "SELECT * FROM data.sla_matrix",
    ],
)
def test_agent_cannot_read_contacts_or_staging(query: str) -> None:
    with _agent() as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute(query)
