"""it-data rules in code (S5): warranty as of the ticket, SLA deadlines, version match,
and the history model that cannot carry status or resolution_notes (CP5.2)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from support_agent.mcp.it_data import logic
from support_agent.mcp.it_data.models import GetRecentTicketsIn, GetSlaIn, TicketSummary

pytestmark = pytest.mark.unit


def test_warranty_covers_the_expiry_day_and_not_the_next() -> None:
    expiry = date(2026, 1, 4)
    assert logic.warranty(datetime(2026, 1, 4, 23, 59, tzinfo=UTC), expiry) == (expiry, True, 0)
    assert logic.warranty(datetime(2026, 1, 5, 0, 0, tzinfo=UTC), expiry)[1:] == (False, -1)


def test_warranty_uses_the_date_in_the_given_offset() -> None:
    ist = timezone(timedelta(hours=5, minutes=30))
    # 2026-01-04 20:00 UTC is already 2026-01-05 in IST.
    as_of = datetime(2026, 1, 5, 1, 30, tzinfo=ist)
    assert logic.warranty(as_of, date(2026, 1, 4))[1] is False


def test_sla_deadlines_add_minutes_to_date_opened() -> None:
    opened = datetime(2026, 2, 22, 5, 53, tzinfo=UTC)
    first, escalate, resolve = logic.sla_deadlines(opened, 15, 90, 240)
    assert (first - opened, escalate - opened, resolve - opened) == (
        timedelta(minutes=15),
        timedelta(minutes=90),
        timedelta(hours=4),
    )


@pytest.mark.parametrize(
    ("a", "b"), [("v4.2.1", "4.2.1"), ("V4.2.1", "v4.2.1"), ("15.2.1", "15.2.1")]
)
def test_version_spellings_match(a: str, b: str) -> None:
    assert logic.version_key(a) == logic.version_key(b)


def test_versions_differ() -> None:
    assert logic.version_key("v4.2.1") != logic.version_key("v4.2.10")


def test_naive_dates_are_rejected() -> None:
    with pytest.raises(ValidationError):
        GetSlaIn(priority="P1", category="POS", date_opened=datetime(2026, 1, 1))  # noqa: DTZ001


def test_recent_tickets_needs_a_store_or_an_asset() -> None:
    with pytest.raises(ValidationError):
        GetRecentTicketsIn(before=datetime(2026, 1, 1, tzinfo=UTC))


@pytest.mark.parametrize("field", ["status", "resolution_notes", "ticket_history"])
def test_ticket_summary_cannot_carry_leaking_fields(field: str) -> None:
    row = {
        "ticket_id": "INC-T1",
        "store_id": "SW-0001",
        "store_name": None,
        "date_opened": datetime(2026, 1, 1, tzinfo=UTC),
        "priority": "P3",
        "category": "POS",
        "subcategory": None,
        "subject": "s",
        "description": "d",
        "asset_id": None,
        "system_version": None,
        "tags": [],
        "escalation_flag": None,
        "related_tickets": [],
    }
    TicketSummary(**row)
    with pytest.raises(ValidationError):
        TicketSummary(**row, **{field: "x"})
