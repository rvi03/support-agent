"""Index steps 2-5: truncation, secret redaction, PII masking, missing links (S6 step 1).

Each step is a pure function from text to text plus its findings; `index.py`
runs them in order: truncation -> redact -> mask -> links -> tables.
No secret value is ever returned in a finding, only its rule id (D11).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass

SECRET = "[SECRET]"  # noqa: S105 - the redaction marker, not a password

# ---- step 2: truncation (A23) ----------------------------------------------------------

# The 4 files known to be cut mid-sentence (assumptions.md A23).
KNOWN_TRUNCATED = frozenset(
    {
        "system-specs/foodtech-pos.md",
        "runbooks/network-router-offline.md",
        "runbooks/pos-startup-failure.md",
        "runbooks/soft-serve-error-codes.md",
    }
)
RUNBOOK_SECTIONS = (
    "Overview",
    "Affected Systems",
    "Symptoms",
    "Immediate Steps",
    "L1 Diagnosis Steps",
    "L1 Resolution",
    "When to Escalate",
    "Information to Collect",
    "Related Runbooks",
    "Revision History",
)
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+\.)(?:\s|$)")
_META_LINE = re.compile(r"^\s*(?:[-*+]\s+)?\*\*[^*]+:?\*\*:?\s")
_END_OK = re.compile(r"""[.!?:;)\]_*`"'|]\s*$""")


def ends_mid_sentence(text: str) -> bool:
    """The last non-empty line is cut: a bare list marker, a list item or a sentence
    without closing punctuation. Table rows and `**Key:** value` lines are complete."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return True
    last = lines[-1].rstrip()
    if last.lstrip().startswith("|") or _META_LINE.match(last):
        return False
    if _LIST_ITEM.match(last) and len(last.strip()) <= 2:
        return True
    return _END_OK.search(last) is None


def missing_sections(text: str) -> list[str]:
    """Runbook template sections (rag-design.md 6.1) with no heading in the text."""
    headings = " | ".join(m.group(1) for m in re.finditer(r"^#{1,4}\s+(.+)$", text, re.M))
    return [s for s in RUNBOOK_SECTIONS if s.lower() not in headings.lower()]


def truncation(doc_id: str, doc_type: str, text: str) -> tuple[bool, str]:
    """(truncated, why). A known file, or the rule for new files: it ends mid-sentence."""
    if doc_id in KNOWN_TRUNCATED:
        return True, "known (A23)"
    if ends_mid_sentence(text):
        return True, "ends mid-sentence"
    return False, ""


# ---- step 3: secrets (A24) -------------------------------------------------------------


@dataclass(frozen=True)
class Redaction:
    rule_id: str
    start: int  # offset in the text the rule ran on; mapped to the final text later


# (a) known values (A24), matched as whole tokens. Rule ids name the value's kind, never it.
KNOWN_SECRETS: tuple[tuple[str, str], ...] = (
    ("known.admin_epson", r"`?admin`?\s*/\s*`?epson`?"),
    ("known.guest_guest", r"guest\s*/\s*guest"),
    ("known.netlink_password", r"NetLink@123"),
    ("known.test_card", r"4111[\s-]?1111[\s-]?1111[\s-]?1111"),
    ("known.pin", r"7890|7392|8800|9988|1234|0000"),
)
# (b) keyword context: PIN / password / passcode / CVV, a short gap, a separator, a value
# holding a digit or symbol ("PIN: 7890", "default PIN is `0000`", "CVV: 123").
_KEYWORD = re.compile(
    r"(?i)\b(?:pin|password|passcode|passwd|pwd|cvv)\b[^\n|.]{0,30}?"
    r"(?:[:=]|\bis\b(?:\s+usually)?|\|)\s*[*`\s]*"
    r"(?P<value>(?=[^\s*`|,;()]*[\d@#$%!^&])[^\s*`|,;()]{3,})"
)
# (c) card numbers: 13-19 digits with optional spaces or dashes, Luhn-valid.
_CARD = re.compile(r"(?<![\w-])\d(?:[\s-]?\d){12,18}(?![\w-])")
REDACTION_RULES_VERSION = "redact-v1"


def luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def _secret_spans(text: str) -> list[tuple[int, int, str]]:
    spans: list[tuple[int, int, str]] = []
    for rule_id, pattern in KNOWN_SECRETS:
        for m in re.finditer(r"(?<![\w@.\-/])(?:" + pattern + r")(?![\w@\-/]|\.\d)", text):
            spans.append((m.start(), m.end(), rule_id))
    for m in _KEYWORD.finditer(text):
        spans.append((m.start("value"), m.end("value"), "context.keyword_value"))
    for m in _CARD.finditer(text):
        digits = re.sub(r"\D", "", m.group(0))
        if luhn_ok(digits):
            spans.append((m.start(), m.end(), "luhn.card"))
    # Overlaps: keep the earliest, then the longest.
    spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))
    kept: list[tuple[int, int, str]] = []
    for span in spans:
        if not kept or span[0] >= kept[-1][1]:
            kept.append(span)
    return kept


def redact(text: str) -> tuple[str, list[Redaction]]:
    """Replace every secret with `[SECRET]`; return the rule ids, never the values."""
    if SECRET in text:
        raise ValueError("source text already holds the [SECRET] marker")
    out: list[str] = []
    found: list[Redaction] = []
    pos = 0
    for start, end, rule_id in _secret_spans(text):
        out.append(text[pos:start])
        found.append(Redaction(rule_id, start))
        out.append(SECRET)
        pos = end
    out.append(text[pos:])
    return "".join(out), found


# ---- step 4: PII (A25, D10) ------------------------------------------------------------

# Business contacts are kept (people.md): ServeWell and vendor domains, helplines.
BUSINESS_DOMAINS = (
    "servewell.in",
    "servewell.local",
    "servewell.internal",
    "servewell-hospitality.local",
    "foodtechpos.com",
    "orbittech.com",
    "epsonindia.co.in",
    "starmicronics.com",
    "netlink-networks.com",
    "creamtech.com",
    "frostypro-global.com",
)
BUSINESS_PHONES = (
    "+91-124-4183500",
    "+1-408-555-0199",
    "+1-800-FROSTY-1",
    "1-800-SERVEWELL",
    "1-800-EMERGENCY",
    "1-800-ZOMATO-1",
    "+91-XXXX-XXXX-XXX",
)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def business_contacts(text: str) -> list[str]:
    """Emails on a business domain and the known helplines found in the text."""
    emails = [
        m.group(0)
        for m in _EMAIL.finditer(text)
        if m.group(0).lower().split("@", 1)[1] in BUSINESS_DOMAINS
    ]
    phones = [p for p in BUSINESS_PHONES if p.lower() in text.lower()]
    return list(dict.fromkeys(emails + phones))


# KB text is technical Title Case ("Thermal Paper", "Webhook Delivery"), where the
# ticket masker's cue rule and plain spaCy PERSON see hundreds of names. So the KB
# keeps the S4 Presidio analyzer with stricter rules (D75):
# - PERSON: score >= 0.85, 2-3 capitalised words, none of which occurs in lowercase
#   anywhere in the KB (a word used in lowercase is a common word, not a name);
# - PHONE: phone-shaped (not an IP address or a baud range) and not a helpline;
# - EMAIL: any address not on a business domain.
# Masks carry no number (`[PERSON]`, `[PHONE]`, `[EMAIL]`): nothing maps them back.
PERSON_MIN_SCORE = 0.85
_PHONE_SHAPE = re.compile(
    r"^(?:\+?\d{1,3}[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}$"
    r"|^(?:\+?91[\s-]?|0)?[6-9]\d{4}[\s-]?\d{5}$"
)
_NAME_WORD = re.compile(r"[A-Z][a-z]+")
MASK_RULES_VERSION = "kb-mask-v1"


def lowercase_vocabulary(texts: Iterable[str]) -> frozenset[str]:
    return frozenset(w for t in texts for w in re.findall(r"\b[a-z][a-z]+\b", t))


Analyze = Callable[[str], list[tuple[int, int, str, float]]]


def presidio_analyze(text: str) -> list[tuple[int, int, str, float]]:
    from support_agent.intake.masker import analyzer

    results = analyzer().analyze(
        text=text, language="en", entities=["PERSON", "PHONE_NUMBER", "IN_PHONE", "EMAIL_ADDRESS"]
    )
    return [(r.start, r.end, r.entity_type, r.score) for r in results]


def pii_spans(
    text: str, vocabulary: frozenset[str], analyze: Analyze = presidio_analyze
) -> list[tuple[int, int, str]]:
    keep = {c.lower() for c in business_contacts(text)}
    spans: list[tuple[int, int, str]] = []
    for start, end, entity, score in analyze(text):
        value = text[start:end]
        if entity == "PERSON":
            words = value.split()
            if (
                score >= PERSON_MIN_SCORE
                and 2 <= len(words) <= 3
                and all(_NAME_WORD.fullmatch(w) for w in words)
                and not any(w.lower() in vocabulary for w in words)
            ):
                spans.append((start, end, "PERSON"))
        elif entity in ("PHONE_NUMBER", "IN_PHONE"):
            if _PHONE_SHAPE.match(value.strip()) and value.lower() not in keep:
                spans.append((start, end, "PHONE"))
        elif entity == "EMAIL_ADDRESS" and value.lower() not in keep:
            spans.append((start, end, "EMAIL"))
    for m in _EMAIL.finditer(text):
        if m.group(0).lower() not in keep:
            spans.append((m.start(), m.end(), "EMAIL"))
    spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))
    merged: list[tuple[int, int, str]] = []
    for span in spans:
        if not merged or span[0] >= merged[-1][1]:
            merged.append(span)
    return merged


def mask(
    text: str, vocabulary: frozenset[str], analyze: Analyze = presidio_analyze
) -> tuple[str, dict[str, int]]:
    """Mask personal data; returns counts by kind, never the values."""
    counts: dict[str, int] = {}
    for start, end, kind in reversed(pii_spans(text, vocabulary, analyze)):
        text = text[:start] + f"[{kind}]" + text[end:]
        counts[kind] = counts.get(kind, 0) + 1
    return text, counts


# ---- step 5: missing links (A11) -------------------------------------------------------

_MD_LINK = re.compile(r"\[(?P<label>[^\]]*)\]\((?P<target>[^)\s]+\.md)\)")
_MD_NAME = re.compile(r"`?(?<![\w/.-])(?P<name>[A-Za-z0-9][A-Za-z0-9_.\-]*\.md)\b`?")


@dataclass(frozen=True)
class Links:
    text: str
    missing: list[str]  # distinct names not in the KB, in order
    related: list[str]  # doc ids of existing documents linked to


def links(text: str, known: Iterable[str]) -> Links:
    """`name.md` references: an existing KB file is kept as `related`; any other one
    becomes `[missing doc: <name>]` and a KB gap. Markdown links collapse to that form."""
    by_name = {k.rsplit("/", 1)[-1].lower(): k for k in known}
    missing: list[str] = []
    related: list[str] = []

    def target(name: str) -> str | None:
        return by_name.get(name.rsplit("/", 1)[-1].lower())

    def md_link(m: re.Match[str]) -> str:
        name = m.group("target").rsplit("/", 1)[-1]
        doc = target(name)
        if doc:
            related.append(doc)
            return m.group(0)
        missing.append(name)
        return f"[missing doc: {name}]"

    text = _MD_LINK.sub(md_link, text)

    def bare(m: re.Match[str]) -> str:
        if text[max(0, m.start() - 14) : m.start()].endswith("[missing doc: "):
            return m.group(0)
        name = m.group("name")
        doc = target(name)
        if doc:
            related.append(doc)
            return m.group(0)
        missing.append(name)
        return f"[missing doc: {name}]"

    text = _MD_NAME.sub(bare, text)
    return Links(text, list(dict.fromkeys(missing)), list(dict.fromkeys(related)))


# ---- table padding (D13 step 0) --------------------------------------------------------

_DASH_ROW = re.compile(r"^\|(?:\s*:?-{3,}:?\s*\|)+\s*$")


def strip_table_padding(text: str) -> str:
    """Padded markdown tables cost hundreds of tokens; cells keep one space each side."""
    out = []
    for line in text.splitlines():
        if line.lstrip().startswith("|"):
            if _DASH_ROW.match(line.strip()):
                cells = line.strip().strip("|").split("|")
                line = "|" + "|".join("---" for _ in cells) + "|"
            else:
                cells = line.strip().strip("|").split("|")
                line = "| " + " | ".join(c.strip() for c in cells) + " |"
        out.append(line)
    return "\n".join(out) + ("\n" if text.endswith("\n") else "")
