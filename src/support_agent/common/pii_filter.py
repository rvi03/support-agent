"""Last-line PII filter for every log sink (design.md, Logging; review M2).

Intake masks PII before anything is logged (S4). This filter is the safety net
behind it: it removes phone, email and actor-name patterns, plus the exact
values registered for live tickets (D43), from every string in a log event.
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Iterable, Mapping, MutableMapping
from typing import Any

PHONE_MASK = "[PHONE]"
EMAIL_MASK = "[EMAIL]"
PERSON_MASK = "[PERSON]"
EXACT_MASK = "[REDACTED]"

DEFAULT_TTL_SECONDS = 24 * 60 * 60

# Indian mobile: optional +91 / 91 / 0 prefix, then 10 digits starting 6-9,
# with optional single spaces or dashes between digits. Bounded so longer digit
# runs (ids, timestamps) and alphanumeric tokens are not touched.
_PHONE_RE = re.compile(r"(?<![\w+])(?:\+?91[\s-]?|0)?[6-9](?:[\s-]?\d){9}(?!\w)")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# Ticket history actor: "L1 Agent - Fixtura Testkar" -> "L1 Agent - [PERSON]".
_ACTOR_RE = re.compile(r"\b(L\d\s+Agent\s*-\s*)[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2}")
# A registered value made only of digits and phone punctuation is a phone.
_PHONE_VALUE_RE = re.compile(r"[\d\s()+-]+")


class _ExactValues:
    """Process-wide registry of exact values to strip, keyed by ticket_id.

    Every registered value is stripped from every event, whichever ticket the
    event names, so a log line without a ticket_id is covered too.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[str, tuple[frozenset[str], float]] = {}
        self._pattern: re.Pattern[str] | None = None

    def register(self, ticket_id: str, values: Iterable[str], ttl_seconds: float) -> None:
        cleaned = frozenset(v.strip() for v in values if v and v.strip())
        with self._lock:
            self._entries[ticket_id] = (cleaned, time.monotonic() + ttl_seconds)
            self._pattern = None

    def clear(self, ticket_id: str) -> None:
        with self._lock:
            if self._entries.pop(ticket_id, None) is not None:
                self._pattern = None

    def pattern(self) -> re.Pattern[str] | None:
        with self._lock:
            now = time.monotonic()
            expired = [tid for tid, (_, until) in self._entries.items() if until <= now]
            for tid in expired:
                del self._entries[tid]
            if expired:
                self._pattern = None
            if self._pattern is None and self._entries:
                parts = {_value_regex(v) for values, _ in self._entries.values() for v in values}
                parts.discard("")
                if parts:
                    # Longest first, so a full name wins over one of its parts.
                    ordered = sorted(parts, key=len, reverse=True)
                    self._pattern = re.compile("|".join(ordered), re.IGNORECASE)
            return self._pattern


def _value_regex(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    if _PHONE_VALUE_RE.fullmatch(value) and len(digits) >= 10:
        # A phone: match its last 10 digits with any separators and prefix.
        last10 = digits[-10:]
        return r"(?<!\d)(?:\+?\d{1,3}[\s-]?)?" + r"[\s-]?".join(last10) + r"(?!\d)"
    words = value.split()
    if not words:
        return ""
    return r"\b" + r"\s+".join(re.escape(w) for w in words) + r"\b"


_REGISTRY = _ExactValues()


def register_exact_values(
    ticket_id: str, values: Iterable[str], ttl_seconds: float = DEFAULT_TTL_SECONDS
) -> None:
    """Strip these exact values (names, phones) from all logs until cleared or expired."""
    _REGISTRY.register(ticket_id, values, ttl_seconds)


def clear_exact_values(ticket_id: str) -> None:
    _REGISTRY.clear(ticket_id)


def scrub_text(text: str) -> str:
    """Remove registered exact values, then actor names, emails and phones."""
    exact = _REGISTRY.pattern()
    if exact is not None:
        text = exact.sub(EXACT_MASK, text)
    text = _ACTOR_RE.sub(lambda m: m.group(1) + PERSON_MASK, text)
    text = _EMAIL_RE.sub(EMAIL_MASK, text)
    return _PHONE_RE.sub(PHONE_MASK, text)


def _scrub(value: Any) -> Any:
    if isinstance(value, str):
        return scrub_text(value)
    if isinstance(value, Mapping):
        return {k: _scrub(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [_scrub(v) for v in value]
    if isinstance(value, int | float | bool) or value is None:
        return value
    # Anything else is logged by its text form, so scrub that.
    return scrub_text(str(value))


def pii_filter_processor(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """structlog processor; must run last, right before rendering."""
    for key in list(event_dict):
        if key.startswith("_"):
            continue  # structlog internals (record, from_structlog)
        event_dict[key] = _scrub(event_dict[key])
    return event_dict
