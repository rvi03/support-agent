"""CP8.2 quote check (D20, Codex S8): fakes are rejected, a real alternate runbook passes."""

from __future__ import annotations

import pytest

from support_agent.agent.grounding import verify_quote
from tests.unit.agent_fakes import document

pytestmark = pytest.mark.unit

DOC = "runbooks/printer-offline.md"
SEC = f"{DOC}#symptoms"
REAL = "Printer shows Offline status in ServeWell POS system"


def test_real_quote_passes_despite_markdown_and_case() -> None:
    check = verify_quote(DOC, SEC, "printer shows offline   STATUS in servewell", document())
    assert check.ok and check.reason == "verified"


@pytest.mark.parametrize(
    ("section", "quote", "reason"),
    [
        (SEC, "Printer shows a red light and beeps twice", "quote_not_in_section"),
        (f"{DOC}#overview", REAL, "section_not_in_runbook"),
        (SEC, "Printer shows", "quote_too_short"),
    ],
)
def test_fake_wrong_section_and_short_quotes_fail(section: str, quote: str, reason: str) -> None:
    check = verify_quote(DOC, section, quote, document())
    assert not check.ok and check.reason == reason


def test_excluded_or_unknown_document_fails() -> None:
    assert verify_quote(DOC, SEC, REAL, None).reason == "document_not_found"
    other = document("runbooks/printer-paper-jam.md")
    assert verify_quote(DOC, SEC, REAL, other).reason == "document_not_found"


def test_real_quote_from_another_device_family_fails() -> None:
    kiosk = document("runbooks/kiosk-frozen.md", family=["kiosk"])
    check = verify_quote(
        "runbooks/kiosk-frozen.md", "runbooks/kiosk-frozen.md#symptoms", REAL, kiosk,
        device_family="printer",
    )  # fmt: skip
    assert not check.ok and check.reason == "wrong_device_family"


def test_valid_alternate_runbook_of_the_same_family_passes() -> None:
    alt = "runbooks/pos-printer-integration.md"
    doc = document(alt, family=["pos", "printer"])
    assert verify_quote(alt, f"{alt}#symptoms", REAL, doc, device_family="printer").ok


def test_not_a_runbook_fails() -> None:
    faq = document("faq/printer-faq.md", doc_type="faq")
    assert verify_quote("faq/printer-faq.md", "faq/printer-faq.md#symptoms", REAL, faq).reason == (
        "not_a_runbook"
    )
