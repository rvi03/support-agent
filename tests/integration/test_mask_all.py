"""CP4.2: masking all 256 train tickets leaves 0 hits for both safety-net
detectors, and every never-mask token found in the raw text survives. Plus the
independent hand-marked fixture (tests/fixtures/pii_marked.yaml, mock values
only): every marked span is removed and every other word is kept.

Needs `make up` and the seed (S3): reads the reference tables and
`tickets.source_staging` as `intake_rw`. Prints no ticket values on failure,
only ids and kinds.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
import yaml

from support_agent.intake.masker import Masker
from support_agent.intake.pipeline import process_ticket, ticket_texts
from support_agent.intake.reference import Reference, load_reference
from support_agent.intake.safety_net import PatternDetector, VaultExactDetector
from support_agent.intake.schema import MaskedTicket
from tests.integration.platform_env import load_env

pytestmark = pytest.mark.integration

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/pii_marked.yaml"
COLUMNS = (
    "ticket_id",
    "store_id",
    "store_name",
    "submitted_by",
    "contact_phone",
    "date_opened",
    "priority",
    "category",
    "subcategory",
    "subject",
    "description",
    "asset_id",
    "system_version",
    "tags",
    "escalation_flag",
    "related_tickets",
    "ticket_history",
)
_WORD = re.compile(r"[\w][\w.\-/:+@]*\w|\w")


@pytest.fixture(scope="module")
def data() -> Iterator[tuple[Reference, list[dict[str, Any]]]]:
    with psycopg.connect(load_env()["DATABASE_URL_INTAKE"]) as conn:
        reference = load_reference(conn)
        rows = conn.execute(
            f"SELECT {', '.join(COLUMNS)} FROM tickets.source_staging ORDER BY ticket_id"  # noqa: S608
        ).fetchall()
    raws = []
    for row in rows:
        raw = dict(zip(COLUMNS, row, strict=True))
        raw["date_opened"] = raw["date_opened"].isoformat()
        raws.append(raw)
    yield reference, raws


@pytest.fixture(scope="module")
def masker(data: tuple[Reference, list[dict[str, Any]]]) -> Masker:
    return Masker(data[0])


def _texts(ticket: MaskedTicket) -> list[str]:
    out = [ticket.subject, ticket.description]
    for h in ticket.ticket_history:
        out += [h.actor or "", h.note]
    return out


def test_all_256_masked_tickets_have_no_pii_hits(
    data: tuple[Reference, list[dict[str, Any]]], masker: Masker
) -> None:
    reference, raws = data
    assert len(raws) == 256
    pattern, vault = PatternDetector(reference), VaultExactDetector(reference)
    hits: list[str] = []
    for raw in raws:
        result = process_ticket(raw, masker)
        for text in ticket_texts(result.ticket):
            for h in pattern.detect(text):
                hits.append(f"{raw['ticket_id']} pattern {h.entity}")
        dump = result.ticket.model_dump_json()  # the exact match has no NER noise
        for h in vault.detect(dump, result.contact.values()):
            hits.append(f"{raw['ticket_id']} vault {h.entity}")
    assert hits == []


def test_never_mask_tokens_survive(
    data: tuple[Reference, list[dict[str, Any]]], masker: Masker
) -> None:
    reference, raws = data
    lost: list[str] = []
    checked = 0
    for raw in raws:
        result = process_ticket(raw, masker)
        raw_text = " ".join(
            [raw["subject"], raw["description"], *(h["note"] for h in raw["ticket_history"])]
        )
        masked = " ".join(_texts(result.ticket))
        for phrase in reference.phrases_in(raw_text):
            checked += 1
            if not re.search(
                r"(?<![\w-])" + re.escape(phrase) + r"(?![\w-])", masked, re.IGNORECASE
            ):
                lost.append(f"{raw['ticket_id']}: {phrase}")
    assert checked > 500  # brands, ids, codes, places really occur in the text
    assert lost == []


def _cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))
    return cases


def test_fixture_has_about_30_cases() -> None:
    cases = _cases()
    assert 25 <= len(cases) <= 40
    assert all(set(c) <= {"text", "pii", "submitter", "phone"} for c in cases)
    for c in cases:  # every marked span is really in its text
        assert all(p in c["text"] for p in c["pii"]), c["text"]


@pytest.mark.parametrize("case", _cases(), ids=lambda c: c["text"][:40])
def test_hand_marked_spans_are_masked_and_the_rest_kept(
    case: dict[str, Any], masker: Masker
) -> None:
    session = masker.session(case.get("submitter"), case.get("phone"))
    masked = session.mask_text(case["text"])
    for value in case["pii"]:
        assert value.casefold() not in masked.casefold(), f"not masked: {value}"
    rest = case["text"]
    for value in sorted(case["pii"], key=len, reverse=True):
        rest = rest.replace(value, " ")
    kept_words = [w for w in _WORD.findall(rest)]
    missing = [w for w in kept_words if w not in masked]
    assert missing == [], f"masked text lost unmarked words {missing}: {masked}"
