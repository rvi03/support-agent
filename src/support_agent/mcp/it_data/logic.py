"""Warranty, SLA and version rules, computed in code, never by the LLM (design.md).

Clock rule (S5 risk): every date comes from the ticket (`as_of`, `date_opened`),
never from "now".
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

GENERAL = "General"


def warranty(as_of: datetime, warranty_expiry: date) -> tuple[date, bool, int]:
    """In warranty while `as_of <= warranty_expiry`, on the calendar date of `as_of`
    in its own offset; the expiry day itself is still covered."""
    day = as_of.date()
    return day, day <= warranty_expiry, (warranty_expiry - day).days


def sla_deadlines(
    date_opened: datetime, first_response: int, escalation: int, resolution: int
) -> tuple[datetime, datetime, datetime]:
    """Wall-clock deadlines from `date_opened` (the SLA matrix is in plain minutes)."""
    return (
        date_opened + timedelta(minutes=first_response),
        date_opened + timedelta(minutes=escalation),
        date_opened + timedelta(minutes=resolution),
    )


def norm(text: str) -> str:
    return " ".join(text.split()).casefold()


def version_key(version: str) -> str:
    """`v4.2.1`, `V4.2.1` and `4.2.1` are the same version."""
    v = norm(version)
    return v[1:] if v.startswith("v") and v[1:2].isdigit() else v
