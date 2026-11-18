"""Index steps 2-5 (S6): truncation, secret redaction, PII masking, missing links."""

from __future__ import annotations

import pytest

from support_agent.kb import clean
from tests.kb_data import kb_files

pytestmark = pytest.mark.unit


# ---- truncation ---------------------------------------------------------------------


def test_rule_finds_exactly_the_four_known_truncated_files() -> None:
    by_rule = {d for d, t in kb_files().items() if clean.ends_mid_sentence(t)}
    assert by_rule == clean.KNOWN_TRUNCATED


@pytest.mark.parametrize(
    ("tail", "cut"),
    [
        ("Restart the app.", False),
        ("| 1.0 | 2024-06-01 | Initial version |", False),
        ("**Next Review:** 2025-12-15", False),
        ("_For other issues raise a ticket._", False),
        ("3. Check Windows Event", True),
        ("  - Any recent maintenance notifications from", True),
        ("-", True),
    ],
)
def test_ends_mid_sentence(tail: str, cut: bool) -> None:
    assert clean.ends_mid_sentence(f"# T\n\nSome text.\n{tail}\n") is cut


def test_new_file_is_flagged_by_the_rule() -> None:
    assert clean.truncation("runbooks/new.md", "runbook", "# T\n\n1. Open the") == (
        True,
        "ends mid-sentence",
    )


# ---- secrets ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "rule"),
    [
        ("Enter the default PIN: **8800** (or yours)", "known.pin"),
        ("Access Admin Panel (Settings > Admin, PIN: 7890)", "known.pin"),
        ("default PIN is usually `0000` or `1234`", "known.pin"),
        ("| **Password** | NetLink@123 | change it |", "known.netlink_password"),
        ("Default credentials: `admin` / `epson` (change)", "known.admin_epson"),
        ("Log in with L1 support credentials (guest/guest or as configured)", "known.guest_guest"),
        ("test card (Card #: 4111111111111111, expiry: 12/25)", "known.test_card"),
        ("Router password: Tr4v3l!x (rotate)", "context.keyword_value"),
        ("pay with 4012 8888 8888 1881 now", "luhn.card"),
    ],
)
def test_redacts_and_reports_only_the_rule(text: str, rule: str) -> None:
    out, found = clean.redact(text)
    assert clean.SECRET in out
    assert rule in [f.rule_id for f in found]
    assert all("8800" not in f.rule_id and "NetLink@123" not in f.rule_id for f in found)


@pytest.mark.parametrize(
    "text",
    [
        "password: check credential vault",
        "5 failed password attempts lock the account",
        "serial SC300-2023-00001 through SC300-2024-06999",
        "IP 192.168.1.1, ext. 5500, 10000 transactions",
        "card 4111 1111 1111 1112 fails Luhn",
    ],
)
def test_leaves_non_secrets(text: str) -> None:
    assert clean.redact(text) == (text, [])


def test_every_a24_value_is_redacted_in_the_real_kb() -> None:
    a24 = ["7890", "7392", "8800", "9988", "NetLink@123", "guest/guest", "4111111111111111"]
    for doc_id, text in kb_files().items():
        out, _ = clean.redact(text)
        for value in a24:
            assert value not in out, (doc_id, "A24 value left")
        assert "`admin` / `epson`" not in out
        assert "PIN: `0000`" not in out and "PIN**   | `0000`" not in out


def test_marker_in_source_is_refused() -> None:
    with pytest.raises(ValueError):
        clean.redact("already [SECRET] here")


# ---- PII ------------------------------------------------------------------------------


def _fake_analyze(spans: list[tuple[str, str, float]]) -> clean.Analyze:
    def analyze(text: str) -> list[tuple[int, int, str, float]]:
        out = []
        for value, entity, score in spans:
            i = text.find(value)
            if i >= 0:
                out.append((i, i + len(value), entity, score))
        return out

    return analyze


def test_mask_keeps_title_case_terms_and_business_contacts() -> None:
    text = (
        "Call Testa Mockwell on +91-90000-00001. Check the Thermal Paper. "
        "Mail it-l2@servewell.in or someone@example.invalid; Epson +91-124-4183500. "
        "Baud 9600-115200 at 192.168.1.100."
    )
    vocab = clean.lowercase_vocabulary(["thermal paper is loaded"])
    analyze = _fake_analyze(
        [
            ("Testa Mockwell", "PERSON", 0.9),
            ("Thermal Paper", "PERSON", 0.9),
            ("+91-90000-00001", "PHONE_NUMBER", 0.7),
            ("+91-124-4183500", "PHONE_NUMBER", 0.7),
            ("9600-115200", "IN_PHONE", 0.9),
            ("192.168.1.100", "PHONE_NUMBER", 0.5),
            ("it-l2@servewell.in", "EMAIL_ADDRESS", 1.0),
        ]
    )
    out, counts = clean.mask(text, vocab, analyze)
    assert "[PERSON]" in out and "Testa" not in out
    assert "Thermal Paper" in out
    assert "[PHONE]" in out and "+91-90000-00001" not in out
    assert "+91-124-4183500" in out and "9600-115200" in out and "192.168.1.100" in out
    assert "it-l2@servewell.in" in out and "someone@example.invalid" not in out
    assert counts == {"PERSON": 1, "PHONE": 1, "EMAIL": 1}


def test_low_score_or_single_word_person_is_kept() -> None:
    analyze = _fake_analyze([("Testa Mockwell", "PERSON", 0.6), ("Splunk", "PERSON", 0.95)])
    out, counts = clean.mask("Testa Mockwell uses Splunk", frozenset(), analyze)
    assert counts == {} and out == "Testa Mockwell uses Splunk"


# ---- links ----------------------------------------------------------------------------


def test_links_keep_existing_and_mark_missing() -> None:
    text = (
        "- `Printer-Paper-Jam.md`\n- [Admin PIN Reset](Admin-Panel-Reset.md)\n"
        "- see printer-offline.md\n- `Printer-Paper-Jam.md` again\n"
    )
    out = clean.links(text, ["runbooks/printer-offline.md"])
    assert out.missing == ["Admin-Panel-Reset.md", "Printer-Paper-Jam.md"]
    assert out.related == ["runbooks/printer-offline.md"]
    assert "[missing doc: Admin-Panel-Reset.md]" in out.text
    assert out.text.count("[missing doc: Printer-Paper-Jam.md]") == 2
    assert "printer-offline.md" in out.text


def test_real_kb_has_178_missing_links_in_30_runbooks() -> None:
    files = kb_files()
    pairs = {(d, n) for d, t in files.items() for n in clean.links(t, files).missing}
    assert len(pairs) == 178
    assert len({d for d, _ in pairs}) == 30
    assert all(d.startswith("runbooks/") for d, _ in pairs)


def test_table_padding_is_stripped() -> None:
    text = "| Code     | Meaning      |\n| -------- | ------------ |\n| E02      | Too warm     |\n"
    assert clean.strip_table_padding(text) == (
        "| Code | Meaning |\n|---|---|\n| E02 | Too warm |\n"
    )
