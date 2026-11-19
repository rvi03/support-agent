"""Safety net: scan text before every model call and every write (D43; S4 step 5).

Two independent detectors:
- `PatternDetector`: Presidio (PERSON, PHONE, EMAIL, CARD) and the phone regexes,
  after the never-mask list. Mask tokens such as `[PERSON_1]` are not hits.
- `VaultExactDetector`: this ticket's vault values: the full name, each name
  part of 3+ letters as a whole word (case-insensitive, minus the never-mask
  list), and the phone by its last 10 digits with any separators.

`scan(text, ticket_id, channel)` raises `PIIBlocked` on any hit, after writing
one `pii_blocked` audit event per hit (channel and detector, never the
value); the caller hands off. `store_message` is exempt from the vault
detector only, because the final reply to the store carries its real name.

The vault values come from the process registry that the log filter also
uses: intake registers them at ticket start (`register_contact`), and the
agent reloads them as `agent_actor` on a resume in a fresh process
(`reload_contact`), into the registry only, never into graph state.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from support_agent.common.audit import AuditEvent
from support_agent.common.pii_filter import register_exact_values, registered_values
from support_agent.intake.masker import IN_PHONE_REGEX, find_pii
from support_agent.intake.reference import Reference
from support_agent.intake.vault import Contact

NAME_PART_MIN = 3
_PHONE_RE = re.compile(IN_PHONE_REGEX)
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE_VALUE_RE = re.compile(r"[\d\s()+-]+")


class Channel(StrEnum):
    PROMPT = "prompt"
    LOG = "log"
    TRACE = "trace"
    AUDIT = "audit"
    COMMENT = "comment"
    L2_NOTE = "l2_note"
    STORE_MESSAGE = "store_message"
    # A store message before the contact is filled (S10 gate check 5): not exempt.
    STORE_DRAFT = "store_draft"


VAULT_EXEMPT = frozenset({Channel.STORE_MESSAGE})


@dataclass(frozen=True)
class Hit:
    detector: str  # "pattern" | "vault_exact"
    entity: str  # PERSON, PHONE, EMAIL, CARD
    start: int
    end: int


class PIIBlocked(RuntimeError):  # noqa: N818 - the name the design uses
    """PII found; the text was not sent or written. Holds no values."""

    def __init__(self, ticket_id: str | None, channel: Channel, hits: list[Hit]) -> None:
        kinds = sorted({f"{h.detector}:{h.entity}" for h in hits})
        super().__init__(f"PII blocked on {channel} for {ticket_id}: {', '.join(kinds)}")
        self.ticket_id, self.channel, self.hits = ticket_id, channel, hits


class PatternDetector:
    def __init__(self, reference: Reference) -> None:
        self.reference = reference

    def detect(self, text: str) -> list[Hit]:
        hits = [Hit("pattern", s.entity, s.start, s.end) for s in find_pii(text, self.reference)]
        for regex, entity in ((_PHONE_RE, "PHONE"), (_EMAIL_RE, "EMAIL")):
            for m in regex.finditer(text):
                if not any(h.start <= m.start() < h.end for h in hits):
                    hits.append(Hit("pattern", entity, m.start(), m.end()))
        return hits


def _is_phone(value: str) -> bool:
    return bool(_PHONE_VALUE_RE.fullmatch(value)) and len(re.sub(r"\D", "", value)) >= 10


class VaultExactDetector:
    def __init__(self, reference: Reference) -> None:
        self.reference = reference

    def patterns(self, values: Iterable[str]) -> list[tuple[str, re.Pattern[str]]]:
        out: list[tuple[str, re.Pattern[str]]] = []
        for value in values:
            if _is_phone(value):
                last10 = re.sub(r"\D", "", value)[-10:]
                sep = r"[\s().+-]*"
                out.append(("PHONE", re.compile(r"(?<!\d)" + sep.join(last10) + r"(?!\d)")))
                continue
            words = value.split()
            if not words:
                continue
            full = r"(?<![\w-])" + r"\s+".join(re.escape(w) for w in words) + r"(?![\w-])"
            out.append(("PERSON", re.compile(full, re.IGNORECASE)))
            for part in words:
                if len(part) >= NAME_PART_MIN and not self.reference.is_never_mask(part):
                    regex = r"(?<![\w-])" + re.escape(part) + r"(?![\w-])"
                    out.append(("PERSON", re.compile(regex, re.IGNORECASE)))
        return out

    def detect(self, text: str, values: Iterable[str]) -> list[Hit]:
        return [
            Hit("vault_exact", entity, m.start(), m.end())
            for entity, regex in self.patterns(values)
            for m in regex.finditer(text)
        ]


class _Connection(Protocol):
    def execute(self, query: Any, params: Any = ..., /) -> Any: ...


AuditWriter = Callable[[AuditEvent], object]


class SafetyNet:
    def __init__(
        self,
        reference: Reference,
        audit: AuditWriter,
        *,
        actor: str,
        pattern: PatternDetector | None = None,
        vault: VaultExactDetector | None = None,
    ) -> None:
        self.audit, self.actor = audit, actor
        self.pattern = pattern or PatternDetector(reference)
        self.vault = vault or VaultExactDetector(reference)

    def find(self, text: str, ticket_id: str | None, channel: Channel) -> list[Hit]:
        hits = self.pattern.detect(text)
        if ticket_id is not None and channel not in VAULT_EXEMPT:
            hits += self.vault.detect(text, registered_values(ticket_id))
        return hits

    def scan(
        self,
        text: str,
        ticket_id: str | None,
        channel: Channel | str,
        *,
        known_words: str | None = None,
        business_domains: tuple[str, ...] = (),
    ) -> list[Hit]:
        """Return [] if clean; otherwise audit each hit and raise PIIBlocked.

        `known_words` (S10 gate check 5): the input a model wrote this text from. A
        pattern PERSON hit whose every word occurs in that input is not new PII (the
        input was checked where it came in); a name the model invents still blocks,
        and the vault exact match always applies. `business_domains`: email addresses
        on these domains are business contacts (D10), not personal data."""
        channel = Channel(channel)
        hits = self.find(text, ticket_id, channel)
        if business_domains:
            hits = [
                h
                for h in hits
                if not (
                    h.entity == "EMAIL"
                    and text[h.start : h.end]
                    .lower()
                    .endswith(tuple("@" + d for d in business_domains))
                )
            ]
        if known_words is not None:
            known = {w.casefold() for w in re.findall(r"[\w'-]+", known_words)}
            hits = [
                h
                for h in hits
                if not (
                    h.detector == "pattern"
                    and h.entity == "PERSON"
                    and all(
                        w.casefold() in known for w in re.findall(r"[\w'-]+", text[h.start : h.end])
                    )
                )
            ]
        return self._block(hits, ticket_id, channel)

    def scan_vault(self, text: str, ticket_id: str | None, channel: Channel | str) -> list[Hit]:
        """Vault exact match only (D43), for sanitized KB text: the pattern detector reads
        Title Case KB terms ("Thermal Paper") as names (D75)."""
        channel = Channel(channel)
        if ticket_id is None:
            return []
        return self._block(
            self.vault.detect(text, registered_values(ticket_id)), ticket_id, channel
        )

    def scan_token(self, text: str, ticket_id: str | None, channel: Channel | str) -> list[Hit]:
        """A machine token (one word with a digit or `_`: ids, dates, enum values) gets the
        phone and email regexes and the vault exact match, not the name model: Presidio
        reads `not_found` as a person (D73)."""
        channel = Channel(channel)
        hits = [
            Hit("pattern", entity, m.start(), m.end())
            for regex, entity in ((_PHONE_RE, "PHONE"), (_EMAIL_RE, "EMAIL"))
            for m in regex.finditer(text)
        ]
        if ticket_id is not None and channel not in VAULT_EXEMPT:
            hits += self.vault.detect(text, registered_values(ticket_id))
        return self._block(hits, ticket_id, channel)

    def scan_prompt(self, fixed: str, data: str, ticket_id: str | None) -> list[Hit]:
        """A model prompt = fixed instructions from the code + variable data (ticket text,
        replies, tool results). The pattern detector scans the data only: spaCy run over
        the fixed instructions finds "names" such as "Labels". The vault exact match
        scans the whole prompt."""
        hits = self.pattern.detect(data)
        if ticket_id is not None:
            hits += self.vault.detect(fixed + "\n" + data, registered_values(ticket_id))
        return self._block(hits, ticket_id, Channel.PROMPT)

    def _block(self, hits: list[Hit], ticket_id: str | None, channel: Channel) -> list[Hit]:
        if not hits:
            return []
        for detector, entity in sorted({(h.detector, h.entity) for h in hits}):
            self.audit(
                AuditEvent(
                    step="safety_net",
                    actor=self.actor,
                    action="pii_blocked",
                    result="blocked",
                    ticket_id=ticket_id,
                    reason=f"{detector} detector found {entity}",
                    payload={"channel": str(channel), "detector": detector, "entity": entity},
                )
            )
        raise PIIBlocked(ticket_id, channel, hits)


def register_contact(ticket_id: str, contact: Contact) -> None:
    """At ticket start: the log filter and the vault detector use these values."""
    register_exact_values(ticket_id, contact.values())


def reload_contact(conn: _Connection, ticket_id: str) -> bool:
    """On a resume in a fresh process, as `agent_actor` (P9): registry only, never state."""
    row = conn.execute(
        "SELECT full_name, phone FROM pii.vault WHERE ticket_id = %s", (ticket_id,)
    ).fetchone()
    if row is None:
        return False
    register_contact(ticket_id, Contact(full_name=row[0], phone=row[1]))
    return True
