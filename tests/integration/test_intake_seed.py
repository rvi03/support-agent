"""S4 build step 7 (D59): after `make seed`, tickets.source_tickets holds the
256 masked train tickets and no contact value of any of them; every vault row
exists; INC-00298 has no chaos line; a rerun adds no vault row.

Needs `make up` and `make seed`. Prints ids and kinds, never values.
"""

from __future__ import annotations

import re
from typing import Any

import psycopg
import pytest

from support_agent.intake.seed import seed_masked
from tests.integration.platform_env import load_env, superuser_url

pytestmark = pytest.mark.integration


def _su() -> psycopg.Connection[Any]:
    return psycopg.connect(superuser_url(load_env()))


def test_source_tickets_are_masked_and_complete() -> None:
    with _su() as su:
        rows = su.execute(
            "SELECT t.ticket_id, t::text, v.full_name, v.phone FROM tickets.source_tickets t"
            " JOIN pii.vault v USING (ticket_id)"
        ).fetchall()
        staged = su.execute("SELECT count(*) FROM tickets.source_staging").fetchone()
        columns = {
            r[0]
            for r in su.execute(
                "SELECT column_name FROM information_schema.columns"
                " WHERE table_schema = 'tickets' AND table_name = 'source_tickets'"
            ).fetchall()
        }
    assert staged is not None and len(rows) == staged[0] == 256
    assert not {"submitted_by", "contact_phone", "status", "resolution_notes"} & columns
    leaks = []
    for ticket_id, text, name, phone in rows:
        for part in [name, *[p for p in (name or "").split() if len(p) >= 3]]:
            if part and re.search(r"(?<![\w-])" + re.escape(part) + r"(?![\w-])", text, re.I):
                leaks.append(f"{ticket_id} name")
        digits = re.sub(r"\D", "", phone or "")[-10:]
        if digits and digits in re.sub(r"[\s().+-]", "", text):
            leaks.append(f"{ticket_id} phone")
    assert leaks == []


def test_chaos_line_is_gone_from_inc_00298() -> None:
    with _su() as su:
        row = su.execute(
            "SELECT ticket_history::text FROM tickets.source_tickets WHERE ticket_id = 'INC-00298'"
        ).fetchone()
    assert row is not None and "chaos" not in row[0].lower()


def test_rerun_adds_no_vault_row() -> None:
    url = load_env()["DATABASE_URL_INTAKE"]
    with psycopg.connect(url) as conn, psycopg.connect(url, autocommit=True) as audit_conn:
        counts = seed_masked(conn, audit_conn)
    assert counts == {"tickets": 256, "vault_new": 0, "dropped_lines": 1}
