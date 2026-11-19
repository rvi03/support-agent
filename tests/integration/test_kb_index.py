"""CP6.1: `make index` on the real KB reports redactions, 178 missing links, the 4
truncated documents; no A24 secret is in any `kb` table. S8a: no conflict register
or hand-written metadata list."""

from __future__ import annotations

import re
import subprocess
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest

from support_agent.kb import clean
from tests.integration.platform_env import ROOT, load_env, superuser_url

pytestmark = pytest.mark.integration

A24 = [
    r"7890", r"7392", r"8800", r"9988", r"1234", r"0000", r"NetLink@123",
    r"guest\s*/\s*guest", r"`?admin`?\s*/\s*`?epson`?", r"4111[\s-]?1111[\s-]?1111[\s-]?1111",
]  # fmt: skip
A24_RE = re.compile(r"(?<![\w@.\-/])(?:" + "|".join(A24) + r")(?![\w@\-/]|\.\d)", re.I)
TEXT_TYPES = ("text", "jsonb", "ARRAY", "character varying")


@pytest.fixture(scope="module")
def indexed() -> str:
    result = subprocess.run(
        ["make", "index", "ARGS=--force"], cwd=ROOT, capture_output=True, text=True, timeout=600
    )
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-2000:]
    return result.stdout


@pytest.fixture(scope="module")
def db(indexed: str) -> Iterator[psycopg.Connection[Any]]:
    with psycopg.connect(superuser_url(load_env()), autocommit=True) as conn:
        yield conn


def _report(db: psycopg.Connection[Any]) -> dict[str, Any]:
    row = db.execute("SELECT report FROM kb.revisions WHERE is_current").fetchone()
    assert row
    return dict(row[0])


def test_report_lists_redactions_gaps_and_truncation(
    indexed: str, db: psycopg.Connection[Any]
) -> None:
    report = _report(db)
    assert report["redactions_total"] > 0
    assert report["missing_links"] == 178 and report["docs_with_missing_links"] == 30
    assert set(report["truncated"]) == clean.KNOWN_TRUNCATED
    assert "conflicts" not in report and "metadata_mismatches" not in report
    for line in ("Redactions:", "Missing links: 178", "Truncated documents: 4"):
        assert line in indexed
    assert (ROOT / "eval/reports/index_report.md").read_text().startswith("# KB index report")


def test_tables_hold_the_report_rows(db: psycopg.Connection[Any]) -> None:
    rev = _report(db)["kb_rev"]
    gaps = dict(db.execute("SELECT kind, count(*) FROM kb.gaps GROUP BY kind").fetchall())
    assert gaps["missing_link"] == 178 and gaps["truncated"] == 4
    truncated = {r[0] for r in db.execute("SELECT doc_id FROM kb.documents WHERE truncated")}
    assert truncated == clean.KNOWN_TRUNCATED
    assert set(gaps) == {"missing_link", "truncated"}
    assert db.execute(
        "SELECT to_regclass('kb.conflicts'), to_regclass('kb.runbook_steps')"
    ).fetchone() == (None, None)
    redactions = db.execute(
        "SELECT count(*), count(section_id) FROM kb.redactions WHERE kb_rev = %s", (rev,)
    ).fetchone()
    assert redactions and redactions[0] > 0 and redactions[0] == redactions[1]
    assert db.execute("SELECT count(DISTINCT kb_rev) FROM kb.sections").fetchone() == (1,)


def _text_columns(db: psycopg.Connection[Any], schema: str) -> list[tuple[str, str]]:
    return db.execute(
        "SELECT table_name, column_name FROM information_schema.columns "
        "WHERE table_schema = %s AND data_type = ANY(%s) ORDER BY 1, 2",
        (schema, list(TEXT_TYPES)),
    ).fetchall()


@pytest.mark.parametrize("schema", ["kb", "kb_staging"])
def test_no_a24_secret_in_any_kb_text_column(db: psycopg.Connection[Any], schema: str) -> None:
    columns = _text_columns(db, schema)
    assert len(columns) > 20
    hits = []
    for table, column in columns:
        for (value,) in db.execute(
            f'SELECT "{column}"::text FROM {schema}."{table}" WHERE "{column}" IS NOT NULL'  # noqa: S608
        ):
            if A24_RE.search(value):
                hits.append((table, column, "A24"))
            _, found = clean.redact(value.replace(clean.SECRET, "[S]"))
            hits += [(table, column, f.rule_id) for f in found]
    assert hits == []


def test_published_kb_is_read_only_to_the_indexer() -> None:
    env = load_env()
    with psycopg.connect(env["DATABASE_URL_KB_INDEX"]) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("DELETE FROM kb.gaps")
    with psycopg.connect(env["DATABASE_URL_KNOWLEDGE"]) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("SELECT 1 FROM kb_staging.sections LIMIT 1")
