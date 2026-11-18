"""Intake step 1: the input schema (design.md, Intake; S4 build step 1).

`TicketIn` accepts only the intake fields. `status` and `resolution_notes`
raise a validation error (the API turns it into 422); any other unknown field
is dropped and its name, never its value, is logged (X10). Empty or blank
optional strings become None, so a fresh ticket with gaps is accepted.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from support_agent.common.logging import get_logger

FORBIDDEN_FIELDS = frozenset({"status", "resolution_notes"})
CONTACT_FIELDS = ("submitted_by", "contact_phone")

SUBJECT_MAX = 300
DESCRIPTION_MAX = 8_000
HISTORY_MAX = 20
NOTE_MAX = 8_000
SHORT_MAX = 200
LIST_MAX = 50

_log = get_logger(__name__)

Required = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Short = Annotated[str, StringConstraints(strip_whitespace=True, max_length=SHORT_MAX)]


def _blank_to_none(value: Any) -> Any:
    if isinstance(value, str) and not value.strip():
        return None
    return value


class HistoryEntry(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    timestamp: str | None = Field(default=None, max_length=SHORT_MAX)
    actor: str | None = Field(default=None, max_length=SHORT_MAX)
    note: str = Field(default="", max_length=NOTE_MAX)


class TicketIn(BaseModel):
    """One incoming ticket, before masking. Holds the contact fields."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    ticket_id: Annotated[Required, StringConstraints(max_length=64)]
    store_id: Annotated[Required, StringConstraints(max_length=64)]
    date_opened: AwareDatetime
    subject: Annotated[Required, StringConstraints(max_length=SUBJECT_MAX)]
    description: Annotated[Required, StringConstraints(max_length=DESCRIPTION_MAX)]

    store_name: Short | None = None
    submitted_by: Short | None = None
    contact_phone: Short | None = None
    priority: Short | None = None
    category: Short | None = None
    subcategory: Short | None = None
    asset_id: Short | None = None
    system_version: Short | None = None
    tags: list[Short] = Field(default_factory=list, max_length=LIST_MAX)
    escalation_flag: bool | None = None
    related_tickets: list[Short] = Field(default_factory=list, max_length=LIST_MAX)
    ticket_history: list[HistoryEntry] = Field(default_factory=list, max_length=HISTORY_MAX)

    @model_validator(mode="before")
    @classmethod
    def _check_fields(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        forbidden = sorted(FORBIDDEN_FIELDS & data.keys())
        if forbidden:
            raise ValueError(f"forbidden fields: {', '.join(forbidden)}")
        unknown = sorted(set(data) - set(cls.model_fields))
        if unknown:
            _log.info(
                "intake_unknown_fields_dropped", ticket_id=data.get("ticket_id"), fields=unknown
            )
        return data

    @field_validator(
        "store_name",
        "submitted_by",
        "contact_phone",
        "priority",
        "category",
        "subcategory",
        "asset_id",
        "system_version",
        mode="before",
    )
    @classmethod
    def _blank_optional(cls, value: Any) -> Any:
        return _blank_to_none(value)

    @field_validator("tags", "related_tickets", "ticket_history", mode="before")
    @classmethod
    def _null_list(cls, value: Any) -> Any:
        return [] if value is None else value


class MaskedTicket(BaseModel):
    """The ticket the agent sees: no contact fields, masked text."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ticket_id: str
    store_id: str
    date_opened: AwareDatetime
    subject: str
    description: str
    store_name: str | None = None
    priority: str | None = None
    category: str | None = None
    subcategory: str | None = None
    asset_id: str | None = None
    system_version: str | None = None
    tags: list[str] = Field(default_factory=list)
    escalation_flag: bool | None = None
    related_tickets: list[str] = Field(default_factory=list)
    ticket_history: list[HistoryEntry] = Field(default_factory=list)
