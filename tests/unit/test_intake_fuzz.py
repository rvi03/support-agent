"""CP4.5: a Hypothesis fuzz over ticket shapes (optional fields dropped, extra
fields, non-ASCII, empty optional strings, over-long fields). An independent
oracle states the schema rules; accept or reject must match it exactly.
Mock values only."""

from __future__ import annotations

from typing import Any

import pytest
from hypothesis import HealthCheck, event, given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from support_agent.intake.schema import (
    DESCRIPTION_MAX,
    FORBIDDEN_FIELDS,
    HISTORY_MAX,
    SUBJECT_MAX,
    TicketIn,
)

pytestmark = pytest.mark.unit

REQUIRED = ("ticket_id", "store_id", "date_opened", "subject", "description")
OPTIONAL_STR = (
    "store_name",
    "submitted_by",
    "contact_phone",
    "priority",
    "category",
    "subcategory",
    "asset_id",
    "system_version",
)
SPECIAL = "—₹°→ éü日本"  # non-ASCII the stores type

text = st.text(alphabet=st.characters(codec="utf-8") | st.sampled_from(SPECIAL), max_size=40)
short_text = st.one_of(st.just(""), st.just("   "), text)
history_entry = st.fixed_dictionaries(
    {"note": text}, optional={"timestamp": short_text, "actor": short_text}
)
extra_names = st.text(alphabet="abcdefghijklmnopqrstuvwxyz_", min_size=3, max_size=12).filter(
    lambda k: k not in TicketIn.model_fields and k not in FORBIDDEN_FIELDS
)


FAULTS = (
    "drop_required",
    "blank_required",
    "long_subject",
    "long_description",
    "naive_date",
    "bad_date",
    "long_history",
    "long_optional",
    "forbidden",
)
VALID_DATES = ("2026-04-04T10:01:00+05:30", "2026-04-04T10:01:00Z")


@st.composite
def tickets(draw: st.DrawFn) -> dict[str, Any]:
    """A valid ticket of random shape; about 1 in 2 gets one fault from FAULTS."""
    raw: dict[str, Any] = {
        "ticket_id": draw(st.sampled_from(["INC-90010", " INC-90011 ", "INC-9001→"])),
        "store_id": draw(st.sampled_from(["SW-9999", "SW-9998 "])),
        "date_opened": draw(st.sampled_from(VALID_DATES)),
        "subject": "Mock " + draw(text),
        "description": draw(st.sampled_from(["Mock ", "d" * (DESCRIPTION_MAX - 20)])) + draw(text),
    }
    for name in OPTIONAL_STR:
        if draw(st.booleans()):
            raw[name] = draw(st.one_of(short_text, st.none()))
    if draw(st.booleans()):
        raw["tags"] = draw(st.one_of(st.none(), st.lists(text, max_size=4)))
    if draw(st.booleans()):
        raw["escalation_flag"] = draw(st.sampled_from([True, False, None]))
    if draw(st.booleans()):
        raw["ticket_history"] = draw(
            st.one_of(st.none(), st.lists(history_entry, max_size=HISTORY_MAX))
        )
    for name in draw(st.lists(extra_names, max_size=3)):
        raw[name] = draw(text)

    fault = draw(st.sampled_from((None,) * len(FAULTS) + FAULTS))
    if fault == "drop_required":
        del raw[draw(st.sampled_from(REQUIRED))]
    elif fault == "blank_required":
        raw[draw(st.sampled_from(["ticket_id", "store_id", "subject", "description"]))] = draw(
            st.sampled_from(["", "   ", "\n\t"])
        )
    elif fault == "long_subject":
        raw["subject"] = "s" * draw(st.integers(SUBJECT_MAX - 1, SUBJECT_MAX + 2))
    elif fault == "long_description":
        raw["description"] = "d" * draw(st.integers(DESCRIPTION_MAX - 1, DESCRIPTION_MAX + 2))
    elif fault == "naive_date":
        raw["date_opened"] = "2026-04-04T10:01:00"
    elif fault == "bad_date":
        raw["date_opened"] = draw(st.sampled_from(["x", "", "2026-13-40T10:00:00Z"]))
    elif fault == "long_history":
        raw["ticket_history"] = [{"note": "Mock note"}] * draw(
            st.integers(HISTORY_MAX - 1, HISTORY_MAX + 2)
        )
    elif fault == "long_optional":
        raw[draw(st.sampled_from(OPTIONAL_STR))] = "o" * draw(st.integers(199, 202))
    elif fault == "forbidden":
        raw[draw(st.sampled_from(sorted(FORBIDDEN_FIELDS)))] = draw(st.one_of(text, st.none()))
    return raw


# Unicode White_Space, as Pydantic strips it; Python's str.strip also strips \x1c-\x1f.
WHITE_SPACE = (
    "\t\n\x0b\x0c\r \x85\xa0\u1680"
    + "".join(map(chr, range(0x2000, 0x200B)))
    + ("\u2028\u2029\u202f\u205f\u3000")
)


def _strip(value: str) -> str:
    return value.strip(WHITE_SPACE)


def oracle(raw: dict[str, Any]) -> bool:
    """The schema rules, written independently of the model."""
    if FORBIDDEN_FIELDS & raw.keys():
        return False
    if any(name not in raw for name in REQUIRED):
        return False
    for name in ("ticket_id", "store_id", "subject", "description"):
        if not _strip(raw[name]):
            return False
    if len(_strip(raw["ticket_id"])) > 64 or len(_strip(raw["store_id"])) > 64:
        return False
    if len(_strip(raw["subject"])) > SUBJECT_MAX:
        return False
    if len(_strip(raw["description"])) > DESCRIPTION_MAX:
        return False
    if raw["date_opened"] not in VALID_DATES:
        return False  # a timezone is required
    for name in OPTIONAL_STR:
        value = raw.get(name)
        if isinstance(value, str) and len(_strip(value)) > 200:
            return False
    if len(raw.get("ticket_history") or []) > HISTORY_MAX:
        return False
    return True


@settings(max_examples=400, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(tickets())
def test_accept_or_reject_matches_the_schema_rules(raw: dict[str, Any]) -> None:
    try:
        ticket = TicketIn.model_validate(raw)
    except ValidationError:
        event("rejected")
        assert oracle(raw) is False, "rejected a valid ticket"
        return
    event("accepted")
    assert oracle(raw) is True, "accepted an invalid ticket"
    dumped = ticket.model_dump()
    assert set(dumped) == set(TicketIn.model_fields)  # extra fields dropped
    for name in OPTIONAL_STR:  # empty or blank optional strings become None
        value = raw.get(name)
        if isinstance(value, str) and not value.strip():  # the schema uses str.strip here
            assert dumped[name] is None
    assert ticket.subject == _strip(raw["subject"])  # non-ASCII kept as typed
