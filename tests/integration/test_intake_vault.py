"""CP4.1: for 20 real tickets the vault row holds the contact, and the masked
ticket's JSON dump holds neither value (name, any name part of 3+ letters, or
the phone's last 10 digits with any separators).

Needs `make up`. Writes as `intake_rw` under test-only ticket ids, reads back
as the superuser (intake_rw can only INSERT), then deletes its rows.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest

from support_agent.intake.masker import Masker
from support_agent.intake.pipeline import process_ticket
from support_agent.intake.vault import write_vault
from tests.integration.platform_env import load_env, superuser_url
from tests.integration.test_raw_upload import DATASET

pytestmark = pytest.mark.integration

PREFIX = "CP41-"


def _tickets() -> list[dict[str, Any]]:
    files = sorted((DATASET / "tickets/train").glob("*.json"))
    raws = [json.loads(f.read_bytes()) for f in files]
    for raw in raws:  # the seed strips them first (S4 build step 1)
        raw.pop("status", None)
        raw.pop("resolution_notes", None)
    # Every ticket whose own text names its submitter, then the first others up to 20.
    named = [
        r
        for r in raws
        if _leaks(
            json.dumps(r["ticket_history"]) + r["subject"] + r["description"], r["submitted_by"], ""
        )
    ]
    rest = [r for r in raws if r not in named]
    return (named + rest)[:20]


def _leaks(text: str, name: str, phone: str) -> list[str]:
    hits = []
    for part in [name, *[p for p in name.split() if len(p) >= 3]]:
        if re.search(r"\b" + re.escape(part) + r"\b", text, re.IGNORECASE):
            hits.append("name")
    last10 = re.sub(r"\D", "", phone)[-10:]
    if last10 and re.search(r"(?<!\d)" + r"[\s()+-]*".join(last10) + r"(?!\d)", text):
        hits.append("phone")
    return hits


@pytest.fixture
def conns() -> Iterator[tuple[psycopg.Connection[Any], psycopg.Connection[Any]]]:
    env = load_env()
    with (
        psycopg.connect(env["DATABASE_URL_INTAKE"]) as intake,
        psycopg.connect(superuser_url(env)) as su,
    ):
        su.execute("DELETE FROM pii.vault WHERE ticket_id LIKE %s", (PREFIX + "%",))
        su.commit()
        yield intake, su
        su.execute("DELETE FROM pii.vault WHERE ticket_id LIKE %s", (PREFIX + "%",))
        su.commit()


def test_dataset_path_exists() -> None:
    assert isinstance(DATASET, Path) and (DATASET / "tickets/train").is_dir()


def test_contact_goes_to_vault_and_never_into_masked_ticket(
    conns: tuple[psycopg.Connection[Any], psycopg.Connection[Any]],
) -> None:
    intake, su = conns
    raws = _tickets()
    assert len(raws) == 20
    masker = Masker()
    for raw in raws:
        result = process_ticket(raw, masker)
        dump = result.ticket.model_dump_json()
        assert _leaks(dump, raw["submitted_by"], raw["contact_phone"]) == [], raw["ticket_id"]
        assert write_vault(intake, PREFIX + raw["ticket_id"], result.contact, result.mask_map)
        # A second write leaves the row as it was.
        assert not write_vault(intake, PREFIX + raw["ticket_id"], result.contact, {})
    intake.commit()

    rows = su.execute(
        "SELECT ticket_id, full_name, phone, mask_map FROM pii.vault WHERE ticket_id LIKE %s",
        (PREFIX + "%",),
    ).fetchall()
    by_id = {r[0][len(PREFIX) :]: r for r in rows}
    assert set(by_id) == {r["ticket_id"] for r in raws}
    for raw in raws:
        _, name, phone, mask_map = by_id[raw["ticket_id"]]
        assert (name, phone) == (raw["submitted_by"], raw["contact_phone"])
        assert mask_map["[PERSON_1]"] == raw["submitted_by"]


def test_intake_role_cannot_read_the_vault() -> None:
    with psycopg.connect(load_env()["DATABASE_URL_INTAKE"]) as intake:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            intake.execute("SELECT full_name FROM pii.vault LIMIT 1")
