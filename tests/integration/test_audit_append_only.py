"""CP2.2: audit.events is append-only for every role; the role grants hold (Codex S2).

Connects as each service role with its own DATABASE_URL_* from .env.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import psycopg
import pytest
from psycopg import errors

from support_agent.platform.dbinit import URL_ROLES
from tests.integration.platform_env import load_env, superuser_url

pytestmark = pytest.mark.integration

AUDIT_WRITERS = {"intake_rw", "it_data_ro", "knowledge_ro", "itsm_rw", "agent_actor", "api_rw"}
NO_AUDIT_WRITE = {"eval_ro", "checker_ro", "ingest_rw", "kb_index_rw"}
PII_READERS = {"agent_actor", "checker_ro"}
AGENT_ROLES = {"intake_rw", "it_data_ro", "knowledge_ro", "itsm_rw", "agent_actor", "api_rw"}
DENIED = (errors.InsufficientPrivilege, errors.RaiseException)


def _url(role: str) -> str:
    return load_env()[URL_ROLES[role]]


def _connect(url: str) -> psycopg.Connection:
    return psycopg.connect(url, autocommit=True, connect_timeout=5)


@pytest.fixture(scope="module")
def su() -> Iterator[psycopg.Connection]:
    with _connect(superuser_url(load_env())) as conn:
        yield conn


@pytest.fixture(scope="module")
def event_id(su: psycopg.Connection) -> int:
    row = su.execute(
        "INSERT INTO audit.events (step, actor, action, result) "
        "VALUES ('test', 'postgres', 'cp2.2 probe', 'ok') RETURNING id"
    ).fetchone()
    assert row
    return int(row[0])


def _insert(conn: psycopg.Connection, role: str) -> None:
    conn.execute(
        "INSERT INTO audit.events (run_id, ticket_id, step, actor, action, result) "
        "VALUES (%s, 'INC-TEST', 'test', %s, 'cp2.2 insert', 'ok')",
        (uuid.uuid4(), role),
    )


@pytest.mark.parametrize("role", sorted(AUDIT_WRITERS))
def test_writer_roles_can_insert(role: str) -> None:
    with _connect(_url(role)) as conn:
        _insert(conn, role)


@pytest.mark.parametrize("role", sorted(NO_AUDIT_WRITE))
def test_read_only_roles_cannot_insert(role: str) -> None:
    with _connect(_url(role)) as conn, pytest.raises(DENIED):
        _insert(conn, role)


def test_langfuse_role_cannot_even_connect() -> None:
    url = f"postgresql://langfuse:{load_env()['LANGFUSE_DB_PASSWORD']}@localhost:5432/servewell"
    with pytest.raises(psycopg.OperationalError, match="permission denied"):
        _connect(url)


@pytest.mark.parametrize("role", [*sorted(URL_ROLES), "postgres"])
@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE audit.events SET result = 'changed' WHERE id = %s",
        "DELETE FROM audit.events WHERE id = %s",
        "TRUNCATE audit.events",
    ],
    ids=["update", "delete", "truncate"],
)
def test_update_delete_truncate_refused_for_every_role(
    role: str, statement: str, event_id: int, su: psycopg.Connection
) -> None:
    url = superuser_url(load_env()) if role == "postgres" else _url(role)
    params = (event_id,) if "%s" in statement else None
    with _connect(url) as conn, pytest.raises(DENIED):
        conn.execute(statement, params)
    row = su.execute("SELECT result FROM audit.events WHERE id = %s", (event_id,)).fetchone()
    assert row == ("ok",)


@pytest.mark.parametrize("role", sorted(URL_ROLES))
def test_only_agent_actor_and_checker_read_pii(role: str) -> None:
    with _connect(_url(role)) as conn:
        if role in PII_READERS:
            conn.execute("SELECT count(*) FROM pii.vault").fetchone()
        else:
            with pytest.raises(errors.InsufficientPrivilege):
                conn.execute("SELECT count(*) FROM pii.vault")


@pytest.fixture(scope="module")
def eval_probe(su: psycopg.Connection) -> Iterator[str]:
    # A new table picks up the schema's default privileges, as later tables will.
    su.execute("CREATE TABLE IF NOT EXISTS eval.cp22_probe (id int)")
    yield "eval.cp22_probe"
    su.execute("DROP TABLE eval.cp22_probe")


@pytest.mark.parametrize("role", sorted(AGENT_ROLES))
def test_no_agent_role_reads_eval(role: str, eval_probe: str) -> None:
    with _connect(_url(role)) as conn, pytest.raises(errors.InsufficientPrivilege):
        conn.execute(f"SELECT * FROM {eval_probe}")  # noqa: S608 - fixed test table name


def test_eval_role_reads_eval(eval_probe: str) -> None:
    with _connect(_url("eval_ro")) as conn:
        conn.execute(f"SELECT * FROM {eval_probe}")  # noqa: S608 - fixed test table name


def test_copy_source_contact_only_by_intake(su: psycopg.Connection) -> None:
    source, target = f"INC-SRC-{uuid.uuid4().hex[:8]}", f"INC-NEW-{uuid.uuid4().hex[:8]}"
    su.execute(
        "INSERT INTO pii.vault (ticket_id, full_name, phone) VALUES (%s, 'Test Name', '+91-0')",
        (source,),
    )
    try:
        with _connect(_url("api_rw")) as conn, pytest.raises(errors.InsufficientPrivilege):
            conn.execute("SELECT pii.copy_source_contact(%s, %s)", (source, target))
        with _connect(_url("intake_rw")) as conn:
            conn.execute("SELECT pii.copy_source_contact(%s, %s)", (source, target))
            # intake can add the row but still cannot read the vault.
            with pytest.raises(errors.InsufficientPrivilege):
                conn.execute("SELECT * FROM pii.vault")
        row = su.execute(
            "SELECT full_name, phone FROM pii.vault WHERE ticket_id = %s", (target,)
        ).fetchone()
        assert row == ("Test Name", "+91-0")
        with _connect(_url("intake_rw")) as conn, pytest.raises(errors.NoDataFound):
            conn.execute("SELECT pii.copy_source_contact('INC-NONE', 'INC-X')")
    finally:
        su.execute("DELETE FROM pii.vault WHERE ticket_id IN (%s, %s)", (source, target))
