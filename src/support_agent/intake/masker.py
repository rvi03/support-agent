"""Intake step 4: mask PII in the ticket text (design.md, Intake; S4 build step 4).

Order: (a) the history actor pattern `L1 Agent - <name>`, (b) exact replace
of the known names, (c) Presidio (spaCy `en_core_web_lg`) for PERSON,
PHONE_NUMBER, EMAIL_ADDRESS and CREDIT_CARD plus an Indian-phone recognizer,
(d) the never-mask list: a Presidio span made only of never-mask words and
ids is kept, and never-mask words at a span's edges are trimmed off.

Each ticket gets one `MaskSession`, so `[PERSON_1]` keeps its meaning across
the subject, description and history; the submitter is always registered
first. The session's mask map (token -> real value) is saved in the vault.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from functools import cache
from typing import TYPE_CHECKING

from support_agent.intake.reference import Reference, build_reference, is_id_like, norm
from support_agent.intake.schema import HistoryEntry

if TYPE_CHECKING:
    from presidio_analyzer import AnalyzerEngine

NAME_PART_MIN = 3
SPACY_MODEL = "en_core_web_lg"
ENTITIES = ("PERSON", "PHONE_NUMBER", "EMAIL_ADDRESS", "CREDIT_CARD", "IN_PHONE")
KIND = {
    "PERSON": "PERSON",
    "PHONE_NUMBER": "PHONE",
    "IN_PHONE": "PHONE",
    "EMAIL_ADDRESS": "EMAIL",
    "CREDIT_CARD": "CARD",
}
# Presidio's generic phone recognizer is noisy on ids and times; below this it is ignored.
MIN_SCORE = {"PHONE_NUMBER": 0.4, "PERSON": 0.6}
# Indian mobile (+91 / 91 / 0 prefix optional, 10 digits from 6-9) and landline (0XX-XXXXXXXX).
IN_PHONE_REGEX = (
    r"(?<![\w+])(?:(?:\+?91[\s-]?|0)?[6-9](?:[\s-]?\d){9}"
    r"|0\d{2,4}[\s-]\d{6,8})(?!\w)"
)
_TOKEN_RE = re.compile(r"\[(?:PERSON|PHONE|EMAIL|CARD)_\d+\]")
_ACTOR_RE = re.compile(r"^(?P<role>L\d\s+Agent\s*-\s*)(?P<name>\S.*)$")
_EDGE_WORD = re.compile(r"[\w][\w.\-/]*")
_TOKEN_PARTS = re.compile(r"\[(?P<kind>PERSON|PHONE|EMAIL|CARD)_(?P<n>\d+)\]")
EMAIL_REGEX = r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"
_EMAIL_RE = re.compile(EMAIL_REGEX)

# Cue rule: spaCy often tags unfamiliar Indian names as ORGANIZATION, and masking
# every ORGANIZATION would mask tech terms (USB, DHCP, SSID). So a run of 1-3
# capitalised words is a PERSON when a person cue sits right before or after it.
_NAME = r"(?P<name>[A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,}){0,2})"
_CUE_BEFORE = (
    r"(?i:\b(?:mr|mrs|ms|dr|shri|smt)\.?|\bcontact:?|\bask for|\bspoke (?:to|with)|\bby"
    r"|\bcashier|\bmanager|\bshift lead|\brider|\btechnician|\bnamed|\bcall)"
)
_CUE_AFTER = (
    r"(?:'s\b|\s*\(|(?i:\s+(?:says|said|called|reported|checked|restarted|approved|knows"
    r"|visited|is waiting|from|at the|here)\b))"
)
_CUE_RES = (
    re.compile(_CUE_BEFORE + r"\s+" + _NAME),
    re.compile(r"(?<![\w-])" + _NAME + _CUE_AFTER),
)
# Capitalised words that are never a name on their own.
NOT_NAMES = frozenset(
    """mr mrs ms dr shri smt the this that store printer please kitchen manager customer order
    payment pending network
    team support hardware technical engineering backend systems level active diagnostic barcode
    terminal counter front shift lead cashier rider vendor staff agent issue error ticket today
    yesterday morning evening monday tuesday wednesday thursday friday saturday sunday january
    february march april may june july august september october november december also still
    restart reboot router screen display device system update version""".split()
)


def phone_regex(phone: str) -> re.Pattern[str] | None:
    """A phone by its last 10 digits with any separators and prefix (D43)."""
    digits = re.sub(r"\D", "", phone)
    if len(digits) < 10:
        return None
    sep = r"[\s().+-]*"
    return re.compile(r"(?<![\w+])(?:\+?\d{1,3}" + sep + r")?" + sep.join(digits[-10:]) + r"(?!\d)")


@cache
def analyzer() -> AnalyzerEngine:
    """One Presidio analyzer per process (loads spaCy once, about 1.5 s)."""
    from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer
    from presidio_analyzer.nlp_engine import NlpEngineProvider

    provider = NlpEngineProvider(
        nlp_configuration={
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": "en", "model_name": SPACY_MODEL}],
        }
    )
    engine = AnalyzerEngine(nlp_engine=provider.create_engine(), supported_languages=["en"])
    engine.registry.add_recognizer(
        PatternRecognizer(
            supported_entity="IN_PHONE",
            patterns=[Pattern("in_phone", IN_PHONE_REGEX, 0.9)],
            supported_language="en",
        )
    )
    return engine


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    entity: str


def find_pii(text: str, reference: Reference) -> list[Span]:
    """Presidio spans after the never-mask list, merged, in text order. Tokens are skipped."""
    if not text.strip():
        return []
    found = [
        (r.start, r.end, r.entity_type)
        for r in analyzer().analyze(text=text, language="en", entities=list(ENTITIES))
        if r.score >= MIN_SCORE.get(r.entity_type, 0.0)
    ]
    found += [(m.start(), m.end(), "EMAIL_ADDRESS") for m in _EMAIL_RE.finditer(text)]
    found += cue_persons(text)
    spans: list[Span] = []
    for start, end, entity in found:
        if entity == "PERSON" and reference.is_never_mask(text[start:end]):
            continue  # a whole never-mask phrase such as "Zomato Down" (before edge trimming)
        if entity == "PERSON":
            start, end = _trim_never_mask(text, start, end, reference)
            if start >= end:
                continue
        piece = text[start:end]
        if _TOKEN_RE.search(piece):
            continue
        if entity == "PERSON" and reference.is_never_mask(piece):
            continue
        if entity == "PHONE_NUMBER" and (len(re.sub(r"\D", "", piece)) < 10 or is_id_like(piece)):
            continue
        spans.append(Span(start, end, KIND[entity]))
    return _merge(spans)


def cue_persons(text: str) -> list[tuple[int, int, str]]:
    """PERSON spans from the cue rule; common capitalised words are trimmed off the edges."""
    out = []
    for regex in _CUE_RES:
        for m in regex.finditer(text):
            words = list(re.finditer(r"\S+", m.group("name")))
            while words and words[0].group(0).casefold() in NOT_NAMES:
                words.pop(0)
            while words and words[-1].group(0).casefold() in NOT_NAMES:
                words.pop()
            if words:
                base = m.start("name")
                out.append((base + words[0].start(), base + words[-1].end(), "PERSON"))
    return out


def _trim_never_mask(text: str, start: int, end: int, reference: Reference) -> tuple[int, int]:
    words = list(_EDGE_WORD.finditer(text, start, end))
    while words and reference.is_never_mask(words[0].group(0)):
        words.pop(0)
    while words and reference.is_never_mask(words[-1].group(0)):
        words.pop()
    if not words:
        return start, start
    return words[0].start(), words[-1].end()


def _merge(spans: list[Span]) -> list[Span]:
    """Drop spans inside a longer one; on overlap keep the earlier, longer span."""
    out: list[Span] = []
    for s in sorted(spans, key=lambda s: (s.start, -(s.end - s.start))):
        if out and s.start < out[-1].end:
            if s.end > out[-1].end and s.entity == out[-1].entity:
                out[-1] = Span(out[-1].start, s.end, s.entity)
            continue
        out.append(s)
    return out


def _name_regex(name: str) -> str:
    return r"(?<![\w-])" + r"\s+".join(re.escape(w) for w in name.split()) + r"(?![\w-])"


def _value_key(kind: str, value: str) -> str:
    if kind == "PHONE":
        return "PHONE:" + re.sub(r"\D", "", value)[-10:]
    return f"{kind}:{norm(value)}"


@dataclass
class MaskSession:
    """Masks one ticket; holds its stable token map."""

    reference: Reference
    use_presidio: bool = True
    mask_map: dict[str, str] = field(default_factory=dict)
    _token_of: dict[str, str] = field(default_factory=dict)  # value key -> token
    _count: dict[str, int] = field(default_factory=dict)
    _pattern: re.Pattern[str] | None = None
    _names: set[str] = field(default_factory=set)  # normalised names for step (b)
    _phones: list[tuple[re.Pattern[str], str]] = field(default_factory=list)  # (regex, token)

    def add_value(self, kind: str, value: str) -> str:
        value = " ".join(value.split())
        key = _value_key(kind, value)
        token = self._token_of.get(key)
        if token is None:
            n = self._count.get(kind, 0) + 1
            self._count[kind] = n
            token = f"[{kind}_{n}]"
            self.mask_map[token] = value
            self._token_of[key] = token
        return token

    def add_phone(self, phone: str) -> str | None:
        """This ticket's own phone: replaced exactly in step (b), whatever its separators."""
        regex = phone_regex(phone)
        if regex is None:
            return None
        token = self.add_value("PHONE", phone)
        self._phones.append((regex, token))
        return token

    def preload(self, mask_map: dict[str, str]) -> None:
        """Start from a stored mask map (a store reply), so every token keeps its meaning.
        Person names come back with their parts; phones with their exact match."""
        for token, value in sorted(mask_map.items(), key=lambda kv: _token_order(kv[0])):
            m = _TOKEN_PARTS.fullmatch(token)
            if m is None:
                continue
            kind, n = m.group("kind"), int(m.group("n"))
            self.mask_map[token] = value
            self._token_of[_value_key(kind, value)] = token
            self._count[kind] = max(self._count.get(kind, 0), n)
            if kind == "PERSON":
                self.add_person(value, with_parts=True)
            elif kind == "PHONE" and (regex := phone_regex(value)) is not None:
                self._phones.append((regex, token))

    def add_person(self, name: str, *, with_parts: bool = False) -> str:
        """Token for `name`; with_parts also maps each name part of 3+ letters to it,
        except parts on the never-mask list (D43)."""
        token = self.add_value("PERSON", name)
        new = {norm(name)}
        if with_parts:
            for part in name.split():
                key = _value_key("PERSON", part)
                if (
                    len(part) >= NAME_PART_MIN
                    and key not in self._token_of
                    and not self.reference.is_never_mask(part)
                ):
                    self._token_of[key] = token
                    new.add(norm(part))
        if not new <= self._names:
            self._names |= new
            self._pattern = None
        return token

    def _compiled(self) -> re.Pattern[str] | None:
        if self._pattern is None:
            names = self._names | {norm(n) for n in self.reference.known_names}
            if not names:
                return None
            ordered = sorted(names, key=len, reverse=True)  # full names before parts
            self._pattern = re.compile("|".join(_name_regex(n) for n in ordered), re.IGNORECASE)
        return self._pattern

    def mask_known(self, text: str) -> str:
        """Step (b): exact replace of this ticket's phone, known names and this ticket's names."""
        if not text:
            return text
        for regex, token in self._phones:
            text = regex.sub(token, text)
        pattern = self._compiled()
        if pattern is None:
            return text
        return pattern.sub(lambda m: self.add_person(m.group(0)), text)

    def mask_text(self, text: str) -> str:
        """Steps (b), (c), (d) on one text."""
        text = self.mask_known(text)
        if not self.use_presidio or not text:
            return text
        spans = find_pii(text, self.reference)
        for s in reversed(spans):
            value = text[s.start : s.end]
            token = (
                self.add_person(value) if s.entity == "PERSON" else self.add_value(s.entity, value)
            )
            text = text[: s.start] + token + text[s.end :]
        return text

    def mask_actor(self, actor: str | None) -> str | None:
        """Step (a) on a history actor; any other actor text gets steps (b)-(d)."""
        if actor is None:
            return None
        m = _ACTOR_RE.match(actor.strip())
        if m is None:
            return self.mask_text(actor)
        return m.group("role") + self.add_person(m.group("name"))

    def mask_history(self, history: Iterable[HistoryEntry]) -> list[HistoryEntry]:
        return [
            HistoryEntry(
                timestamp=h.timestamp,
                actor=self.mask_actor(h.actor),
                note=self.mask_text(h.note),
            )
            for h in history
        ]


def _token_order(token: str) -> tuple[str, int]:
    m = _TOKEN_PARTS.fullmatch(token)
    return (m.group("kind"), int(m.group("n"))) if m else ("", 0)


class Masker:
    """Built once at startup with the reference from the data."""

    def __init__(self, reference: Reference | None = None, *, use_presidio: bool = True) -> None:
        self.reference = reference or build_reference((), ())
        self.use_presidio = use_presidio

    def session(
        self,
        submitter: str | None,
        phone: str | None = None,
        *,
        mask_map: dict[str, str] | None = None,
    ) -> MaskSession:
        """A new ticket's session (submitter first, so it is `[PERSON_1]`), or a reply's
        session from the ticket's stored mask map."""
        session = MaskSession(reference=self.reference, use_presidio=self.use_presidio)
        if mask_map:
            session.preload(mask_map)
        if submitter:
            session.add_person(submitter, with_parts=True)
        if phone:
            session.add_phone(phone)
        return session

    def mask_tool_result(self, text: str) -> str:
        """The same masking for a tool result that carries names (S5, e.g. `region_manager`)."""
        return self.session(None).mask_text(text)
