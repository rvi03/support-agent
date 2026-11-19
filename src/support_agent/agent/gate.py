"""Evaluator gate, checks 5-8 (S10 build step 8; agent-architecture.md, 7).

Every output passes `Gate.check(output, state)` before it is used:

- 5 no PII: both safety-net detectors (pattern and this ticket's vault values).
  Store text is checked before the contact is filled, on channel `store_draft`,
  which is not vault-exempt. For LLM text, a pattern PERSON hit made only of words
  from the model's own input is not new PII (KB headings such as "Immediate
  Steps" read as names; D111); an invented name still blocks.
- 6 no `[SECRET]`, no secret pattern (PIN or password with a value, default
  credentials such as `admin/xxxx`), and no destructive instruction in text for
  the store.
- 7 every KB document and section named exists in the ticket's `kb_rev`.
- 8 (review M5, D50) Redirect and Clarify send only the rendered template of the
  approved key; every store message carries its `kind`.

A block returns `GateResult(ok=False, check, reason)`; the caller audits it and
hands off (a blocked L2 note uses the code-built fallback note). Checks 1-4
(Resolver steps) are in `agent/walk.py` (S11): they decide which approved runbook
span may be dispatched, before any text exists; the walk's store messages then pass
5-8 here like every other output.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

from support_agent.intake.safety_net import Channel, PIIBlocked, SafetyNet

OutputKind = Literal["l2_note", "l1_pack", "store_message", "comment"]

SECRET_MARK = "[SECRET]"  # noqa: S105 - the KB redaction marker, not a password
# A PIN, password, passcode or OTP given a value ("PIN: 4821", "password is abc123").
_SECRET_KV = re.compile(
    r"(?i)\b(?:pin|password|passcode|passwd|pwd|otp)\b\s*(?:is|=|:)\s*[\"']?"
    r"(?P<v>[A-Za-z0-9@#$%^&*!._-]{3,})"
)
# Default credentials written as user/password ("admin/epson").
_CREDS = re.compile(r"(?i)\b(?:admin|root|supervisor|service)\s*/\s*[A-Za-z0-9@#$%^&*!]{3,}")
# Words after "password is" that are not a value.
_NOT_VALUE = frozenset(
    "reset required expired incorrect wrong changed needed missing locked not the a an "
    "being still also only".split()
)
# Instructions store staff must never get (second layer behind the walk rules).
_DESTRUCTIVE = re.compile(
    r"(?i)\b(?:factory[ -]reset|format (?:the )?(?:disk|drive|terminal)|wipe|delete (?:all|the)|"
    r"void all|drop table|rm -rf|reinstall (?:the )?(?:os|operating system|firmware)|"
    r"flash (?:the )?firmware|edit (?:the )?registry|regedit)\b"
)
# KB ids as the index names them: <folder>/<name>.md and optional #section.
_KB_REF = re.compile(
    r"\b(?P<doc>(?:runbooks|sop|faq|system-specs)/[a-z0-9][a-z0-9-]*\.md)(?:#(?P<sec>[a-z0-9][a-z0-9~_-]*))?"
)

# Business contacts may appear (D10): ServeWell's own addresses (Billing, L2, on-call).
BUSINESS_DOMAINS = ("servewell.in",)

ChannelFor: dict[str, Channel] = {
    "l2_note": Channel.L2_NOTE,
    "l1_pack": Channel.COMMENT,
    "comment": Channel.COMMENT,
    "store_message": Channel.STORE_DRAFT,
}


@dataclass(frozen=True)
class GateOutput:
    kind: OutputKind
    text: str
    # Store messages: the D50 kind and, for redirect/clarify, the approved key.
    message_kind: str | None = None
    template_key: str | None = None
    # The model's input data, for check 5 (a name made of input words is not new PII).
    source: str | None = None


@dataclass(frozen=True)
class GateResult:
    ok: bool
    check: int | None = None  # the check that blocked (5-8)
    reason: str | None = None

    @staticmethod
    def passed() -> GateResult:
        return GateResult(ok=True)


# (doc_id, section_id or None) -> exists in the ticket's kb_rev
KbExists = Callable[[str, str | None], Awaitable[bool]]
# (message kind, key) -> the approved rendered template (before the name is filled)
Template = Callable[[str, str], str | None]


def secret_hit(text: str) -> str | None:
    if SECRET_MARK in text:
        return "secret_marker"
    if any(m["v"].casefold() not in _NOT_VALUE for m in _SECRET_KV.finditer(text)):
        return "secret_pattern"
    if _CREDS.search(text):
        return "secret_pattern"
    return None


def kb_refs(text: str) -> list[tuple[str, str | None]]:
    """Every KB document (and section) the text names, in order, without repeats."""
    seen: list[tuple[str, str | None]] = []
    for m in _KB_REF.finditer(text):
        ref = (m["doc"], f"{m['doc']}#{m['sec']}" if m["sec"] else None)
        if ref not in seen:
            seen.append(ref)
    return seen


@dataclass
class Gate:
    safety_net: SafetyNet
    kb_exists: KbExists
    template: Template
    template_words: str = ""

    async def check(self, output: GateOutput, ticket_id: str) -> GateResult:
        # 8: store messages carry a kind; redirect and clarify are the template only.
        if output.kind == "store_message":
            # Code templates only (D50): a name hit made of template words is our text.
            known = self.template_words + ("\n" + output.source if output.source else "")
            output = GateOutput(output.kind, output.text, output.message_kind,
                                output.template_key, known)  # fmt: skip
            if not output.message_kind:
                return GateResult(False, 8, "store_message_without_kind")
            if output.message_kind in ("redirect", "clarify"):
                want = self.template(output.message_kind, output.template_key or "")
                if want is None:
                    return GateResult(False, 8, "no_approved_template")
                if output.text != want:
                    return GateResult(False, 8, "not_the_approved_template")
        # 5: PII, both detectors.
        try:
            self.safety_net.scan(
                output.text,
                ticket_id,
                ChannelFor[output.kind],
                known_words=output.source,
                business_domains=BUSINESS_DOMAINS,
            )
        except PIIBlocked as exc:
            kinds = ",".join(sorted({f"{h.detector}:{h.entity}" for h in exc.hits}))
            return GateResult(False, 5, f"pii:{kinds}")
        # 6: secrets, and destructive instructions in store text.
        hit = secret_hit(output.text)
        if hit:
            return GateResult(False, 6, hit)
        if output.kind == "store_message" and _DESTRUCTIVE.search(output.text):
            return GateResult(False, 6, "destructive_instruction")
        # 7: every KB id named exists in the ticket's kb_rev.
        for doc, section in kb_refs(output.text):
            if not await self.kb_exists(doc, section):
                return GateResult(False, 7, f"unknown_kb_ref:{section or doc}")
        return GateResult.passed()
