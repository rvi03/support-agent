"""CP3.2 row counts, CP3.3 no outcome fields and staging closed, CP3.4 idempotent seed.

Needs `make up`. CP3.4 runs the seed twice itself.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg import errors

from support_agent.ingest import seed
from tests.integration.platform_env import ROOT, load_env, superuser_url
from tests.integration.test_raw_upload import DATASET, _listed, _s3

pytestmark = pytest.mark.integration

CSV_TABLES = {
    "data.stores": "data/stores.csv",
    "data.assets": "data/assets.csv",
    "data.sla_matrix": "data/sla_matrix.csv",
    "data.version_matrix": "kb/system-specs/version-matrix.csv",
    "eval.ticket_index": "tickets/train_index.csv",
}
STAGING = "tickets.source_staging"
SOURCE = "tickets.source_tickets"


def _conn() -> psycopg.Connection[Any]:
    return psycopg.connect(superuser_url(load_env()))


def _count(conn: psycopg.Connection[Any], table: str) -> int:
    row = conn.execute(f"SELECT count(*) FROM {table}").fetchone()  # noqa: S608
    assert row is not None
    return int(row[0])


def _lines_minus_header(path: Path) -> int:
    return len(path.read_bytes().splitlines()) - 1


@pytest.mark.parametrize(("table", "source"), sorted(CSV_TABLES.items()))
def test_row_counts_match_the_csvs(table: str, source: str) -> None:
    with _conn() as conn:
        assert _count(conn, table) == _lines_minus_header(DATASET / source)


def test_ticket_and_label_counts() -> None:
    labels = json.loads((DATASET / "labels/train_labels.json").read_bytes())
    with _conn() as conn:
        assert _count(conn, STAGING) == len(list((DATASET / "tickets/train").glob("*.json")))
        assert _count(conn, "eval.labels") == len(labels) == 220
        assert _count(conn, "eval.split") == 256


def _columns(conn: psycopg.Connection[Any], table: str) -> set[str]:
    schema, name = table.split(".")
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = %s AND table_name = %s",
        (schema, name),
    ).fetchall()
    return {r[0] for r in rows}


def test_no_outcome_columns() -> None:
    with _conn() as conn:
        for table in (STAGING, SOURCE):
            cols = _columns(conn, table)
            assert cols, table
            assert not cols & {"status", "resolution_notes"}, table


def test_resolution_notes_text_appears_in_no_row() -> None:
    notes = {}
    for path in sorted((DATASET / "tickets/train").glob("*.json")):
        ticket = json.loads(path.read_bytes())
        if ticket["resolution_notes"]:
            notes[ticket["ticket_id"]] = ticket["resolution_notes"]
    assert len(notes) == 26  # the E1 tickets
    with _conn() as conn:
        for table in (STAGING, SOURCE):
            rows = dict(
                conn.execute(
                    f"SELECT ticket_id, t::text FROM {table} AS t"  # noqa: S608
                ).fetchall()
            )
            for tid, text in notes.items():
                assert text not in rows.get(tid, ""), (table, tid)


@pytest.mark.parametrize(
    "var", ["DATABASE_URL_IT_DATA", "DATABASE_URL_API", "DATABASE_URL_CHECKER"]
)
def test_reader_roles_are_denied_staging(var: str) -> None:
    with (
        psycopg.connect(load_env()[var]) as conn,
        pytest.raises(errors.InsufficientPrivilege),
    ):
        conn.execute(f"SELECT 1 FROM {STAGING} LIMIT 1")  # noqa: S608


@pytest.mark.parametrize(
    "var", ["DATABASE_URL_IT_DATA", "DATABASE_URL_AGENT", "DATABASE_URL_INTAKE"]
)
@pytest.mark.parametrize("table", ["eval.labels", "eval.ticket_index", "eval.split"])
def test_agent_roles_cannot_read_eval(var: str, table: str) -> None:
    with (
        psycopg.connect(load_env()[var]) as conn,
        pytest.raises(errors.InsufficientPrivilege),
    ):
        conn.execute(f"SELECT 1 FROM {table} LIMIT 1")  # noqa: S608


def _state() -> tuple[dict[str, str], list[tuple[str, str, int, str]]]:
    sums: dict[str, str] = {}
    with _conn() as conn:
        for table, (pk, _) in {**seed.TABLES, "data.raw_files": (("path",), ())}.items():
            order = ", ".join(f"t.{c}" for c in pk)
            row = conn.execute(
                f"SELECT md5(coalesce(string_agg(t::text, '|' ORDER BY {order}), '')) "  # noqa: S608
                f"FROM {table} AS t"
            ).fetchone()
            assert row is not None
            sums[table] = row[0]
    s3 = _s3()
    objects = []
    for key in sorted(_listed(s3)):
        head = s3.head_object(Bucket="servewell", Key=key)
        objects.append((key, head["ETag"], head["ContentLength"], head["LastModified"].isoformat()))
    return sums, objects


def _run_seed() -> None:
    result = subprocess.run(
        ["uv", "run", "python", "-m", "support_agent.ingest.seed"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=600,
    )
    assert result.returncode == 0, result.stderr
    assert "0 uploaded, 311 same" in result.stdout, result.stdout


def test_seed_twice_gives_the_same_state() -> None:
    _run_seed()
    first = _state()
    _run_seed()
    assert _state() == first
