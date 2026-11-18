"""CP4.1 pure parts: the schema keeps the contact out of the masked ticket."""

from __future__ import annotations

from typing import Any

import pytest

from support_agent.intake.masker import Masker
from support_agent.intake.pipeline import process_ticket
from support_agent.intake.reference import build_reference
from support_agent.intake.schema import TicketIn
from support_agent.intake.vault import Contact, split_contact

pytestmark = pytest.mark.unit


def _raw(**extra: Any) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "ticket_id": "INC-90001",
        "store_id": "SW-0001",
        "store_name": "ServeWell - Banjara Hills",
        "submitted_by": "Testa Mockwell",
        "contact_phone": "+91-90000-00001",
        "date_opened": "2026-04-04T10:01:00+05:30",
        "subject": "Printer offline at counter 2",
        "description": "Testa here. The KOT printer shows offline. Call mockwell on 90000 00001.",
        "ticket_history": [
            {
                "timestamp": "2026-04-04T10:05",
                "actor": "L1 Agent - Fixtura Testkar",
                "note": "Asked Testa to restart",
            },
        ],
    }
    raw.update(extra)
    return raw


def test_split_contact_removes_both_fields() -> None:
    fields, contact = split_contact(TicketIn.model_validate(_raw()))
    assert "submitted_by" not in fields and "contact_phone" not in fields
    assert contact == Contact(full_name="Testa Mockwell", phone="+91-90000-00001")
    assert "Testa" not in repr(contact)


def test_masked_ticket_holds_neither_contact_value() -> None:
    result = process_ticket(_raw(), Masker())
    dump = result.ticket.model_dump_json()
    assert "testa" not in dump.lower() and "mockwell" not in dump.lower()
    assert result.ticket.description.startswith("[PERSON_1] here.")
    assert "[PERSON_1] on" in result.ticket.description
    assert result.ticket.ticket_history[0].actor == "L1 Agent - [PERSON_2]"
    assert result.ticket.ticket_history[0].note == "Asked [PERSON_1] to restart"
    assert result.mask_map == {
        "[PERSON_1]": "Testa Mockwell",
        "[PERSON_2]": "Fixtura Testkar",
        "[PHONE_1]": "+91-90000-00001",
    }
    assert result.contact.values() == ["Testa Mockwell", "+91-90000-00001"]


def test_known_names_are_replaced_with_their_own_token() -> None:
    raw = _raw(description="Region manager Regiona Mocklead approved it. Testa Mockwell waiting.")
    result = process_ticket(raw, Masker(build_reference(["Regiona  Mocklead"], ())))
    assert result.ticket.description == "Region manager [PERSON_2] approved it. [PERSON_1] waiting."
    assert result.mask_map["[PERSON_2]"] == "Regiona Mocklead"


def test_no_submitter_still_masks_known_names() -> None:
    result = process_ticket(
        _raw(submitted_by=None, contact_phone=""), Masker(build_reference(["Fixtura Testkar"], ()))
    )
    assert result.contact == Contact(full_name=None, phone=None)
    actor = result.ticket.ticket_history[0].actor
    assert actor is not None and actor.startswith("L1 Agent - [PERSON_")
    assert result.mask_map[actor.removeprefix("L1 Agent - ")] == "Fixtura Testkar"
