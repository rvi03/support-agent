"""Safety net prompt scan: fixed instructions are not NER-scanned, the data is,
and the vault exact match covers the whole prompt (D43). Mock values only."""

from __future__ import annotations

import pytest

from support_agent.common.audit import AuditEvent
from support_agent.common.pii_filter import clear_exact_values
from support_agent.intake.moderation import SYSTEM_PROMPT
from support_agent.intake.reference import build_reference
from support_agent.intake.safety_net import PIIBlocked, SafetyNet, register_contact
from support_agent.intake.vault import Contact

pytestmark = pytest.mark.unit

REFERENCE = build_reference((), ("KOT",))
TICKET = "INC-90050"


@pytest.fixture
def net() -> tuple[SafetyNet, list[AuditEvent]]:
    events: list[AuditEvent] = []
    register_contact(TICKET, Contact(full_name="Testa Mockwell", phone="+91-90000-00051"))
    yield SafetyNet(REFERENCE, events.append, actor="intake"), events
    clear_exact_values(TICKET)


def test_fixed_instructions_alone_pass(net: tuple[SafetyNet, list[AuditEvent]]) -> None:
    safety_net, events = net
    assert safety_net.scan_prompt(SYSTEM_PROMPT, "KOT printer offline.", TICKET) == []
    assert events == []


@pytest.mark.parametrize(
    "data",
    [
        "Call Mockesh Fakewani about the KOT printer.",  # a name only the pattern finds
        "My number is 90000 00052, printer offline.",  # a phone only the pattern finds
        "testa says the printer is offline",  # the vault name part
        "reach me at 9000000051",  # the vault phone
    ],
)
def test_pii_in_the_data_blocks(net: tuple[SafetyNet, list[AuditEvent]], data: str) -> None:
    safety_net, events = net
    with pytest.raises(PIIBlocked):
        safety_net.scan_prompt(SYSTEM_PROMPT, data, TICKET)
    assert events and all(e.action == "pii_blocked" for e in events)


def test_vault_value_in_the_fixed_part_still_blocks(
    net: tuple[SafetyNet, list[AuditEvent]],
) -> None:
    safety_net, _ = net
    with pytest.raises(PIIBlocked):
        safety_net.scan_prompt("Write to Testa Mockwell.", "printer offline", TICKET)
