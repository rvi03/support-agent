"""Resolver turn and gate checks 1-4 (S11 build steps 2-3; D51, D54, D108).

The model reads the whole runbook and, per turn, submits one `ResolverTurn`:
next (an approved step id), fixed or stuck, with the words of the latest store
reply that chose it. Code never trusts it:

- 1 source: the step is an approved binding of this runbook whose span is still in
  the ticket's kb_rev, not done and not tried; the reply quote is really in the
  latest reply.
- 2 text: the store gets the binding's warnings and span, built by code; the
  model's own words never reach the store.
- 3 dispatch: the binding's audience decides store, IT action or L2 task; a guarded
  IT step becomes an L2 task (D51); prerequisites must be completed in this walk
  (a reported attempt does not count, D54); a conflict hands off.
- 4 scope: once the connection is known (a verified quote), a step written for
  the other connection is blocked; a device version the runbook does not cover
  allows generic steps only.

Evidence (D54): a history step counts as tried only on an affirmative past-tense
quote from the ticket; `fixed` needs an action result of fixed or a verified,
affirmative quote from the latest store reply.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from support_agent.agent.bindings import Binding, Bindings, in_document
from support_agent.agent.state import WalkState
from support_agent.common.text import normalize
from support_agent.mcp.knowledge.models import Document

# Negated, planned or asked: such a quote marks nothing done and proves no fix (D54).
_NOT_DONE = re.compile(
    r"(?i)(?:\bnot\b|n't\b|\bnever\b|\bno longer\b|\bwill\b|\bgoing to\b|\bplan(?:ning)? to\b|"
    r"\bshould i\b|\bcan i\b|\bshall i\b|\bdo i\b|\bwould\b|\btry to\b|\?)"
)
# A fix claim also fails on "still" ("still offline") and on failure words.
_NOT_FIXED = re.compile(r"(?i)\bstill\b|\bagain\b.*\b(?:fail|stuck|offline|frozen)|\bnothing\b")
MIN_EVIDENCE = 6  # characters of a reply quote, folded


class TriedClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    step_id: str
    quote: str = Field(description="The ticket's own words saying this step was done.")


class Judged(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str
    quote: str | None


class ResolverTurn(BaseModel):
    """One Resolver turn (strict JSON schema)."""

    model_config = ConfigDict(extra="forbid")
    decision: Literal["next", "fixed", "stuck"]
    step_id: str | None = Field(description="An id from approved_steps when decision is next.")
    reply_quote: str | None = Field(
        description="Words copied from the latest store reply or result that chose this."
    )
    tried: list[TriedClaim] = Field(
        description="First turn only: approved steps the ticket says were already done."
    )
    connection: Literal["usb", "network", "unknown"]
    connection_quote: str | None = Field(
        description="Words from the ticket or a store reply that show the connection."
    )
    version_covered: Literal["covered", "not_covered", "unclear"]
    version_quote: str | None = Field(
        description="Words from the Affected Systems section that decide coverage."
    )
    escalate_quote: str | None = Field(
        description="With stuck: the When to Escalate line that is met, copied, if any."
    )
    reason: str


@dataclass(frozen=True)
class Check:
    ok: bool
    check: int | None = None
    reason: str = ""
    handoff: bool = False  # True: no repair turn, hand off now


def passed() -> Check:
    return Check(True)


def affirmative(quote: str) -> bool:
    return _NOT_DONE.search(quote) is None


def says_fixed(quote: str) -> bool:
    return affirmative(quote) and _NOT_FIXED.search(quote) is None


def quote_in_text(quote: str | None, text: str | None) -> bool:
    if not quote or not text:
        return False
    q = normalize(quote)
    return len(q) >= MIN_EVIDENCE and q in normalize(text)


def usable(bindings: Bindings, doc: Document) -> dict[str, Binding]:
    """The approved steps of this runbook whose words are still in this revision."""
    return {b.id: b for b in bindings.for_runbook(doc.doc_id) if in_document(b, doc)}


def verify_tried(
    claims: list[TriedClaim], steps: dict[str, Binding], ticket_text: str
) -> tuple[list[tuple[str, str]], list[str]]:
    """(accepted (step_id, quote), rejected reasons). A step with a warning or safety line
    is never skipped on a claim: it is sent again with its warning (review m2)."""
    accepted: list[tuple[str, str]] = []
    rejected: list[str] = []
    for c in claims:
        b = steps.get(c.step_id)
        if b is None:
            rejected.append(f"{c.step_id}:unknown_step")
        elif not quote_in_text(c.quote, ticket_text):
            rejected.append(f"{c.step_id}:quote_not_in_ticket")
        elif not affirmative(c.quote):
            rejected.append(f"{c.step_id}:negated_or_planned")
        elif b.warnings:
            rejected.append(f"{c.step_id}:has_warning")
        elif all(c.step_id != s for s, _ in accepted):
            accepted.append((c.step_id, c.quote))
    return accepted, rejected


def check_fixed(turn: ResolverTurn, walk: WalkState) -> Check:
    """D54: an action result of fixed, or the latest reply's own affirmative words."""
    if walk.last_event == "action" and walk.last_outcome == "fixed":
        return passed()
    if walk.last_event != "store_reply":
        return Check(False, 1, "fixed_without_reply_or_fixed_result")
    if not quote_in_text(turn.reply_quote, walk.last_text):
        return Check(False, 1, "fixed_quote_not_in_latest_reply")
    if not says_fixed(turn.reply_quote or ""):
        return Check(False, 1, "fixed_quote_negated_or_planned")
    return passed()


def check_step(
    turn: ResolverTurn, walk: WalkState, steps: dict[str, Binding], *, has_action: set[str]
) -> tuple[Check, Binding | None]:
    """Gate checks 1-4 for a `next` turn. `has_action`: registry action ids that fit the
    ticket's device family."""
    b = steps.get(turn.step_id or "")
    # 1: an approved step of this runbook, in this kb_rev, not done, not tried.
    if b is None:
        return Check(False, 1, f"no_approved_step:{turn.step_id}"), None
    if b.id in walk.done_ids:
        return Check(False, 1, f"already_done:{b.id}"), b
    if any(t.step_id == b.id for t in walk.tried):
        return Check(False, 1, f"already_tried:{b.id}"), b
    if walk.last_event == "store_reply" and not quote_in_text(turn.reply_quote, walk.last_text):
        return Check(False, 1, "reply_quote_not_in_latest_reply"), b
    # 3: dispatch kind and prerequisites.
    if b.conflict:
        return Check(False, 3, f"conflict:{b.id}", handoff=True), b
    missing = [r for r in b.requires if r not in walk.done_ids]
    if missing:
        return Check(False, 3, f"prerequisite_not_done:{','.join(missing)}"), b
    if b.audience == "it" and b.action_id not in has_action:
        return Check(False, 3, f"action_not_for_device:{b.action_id}"), b
    # 4: scope.
    if walk.connection and b.scope not in ("any", walk.connection):
        return Check(False, 4, f"scope_{b.scope}_but_connection_{walk.connection}"), b
    if walk.generic_only and not b.generic:
        return Check(False, 4, f"version_not_covered_generic_only:{b.id}"), b
    return passed(), b


DispatchKind = Literal["send_store", "run_action", "l2_task"]


def dispatch_kind(b: Binding) -> tuple[DispatchKind, str | None]:
    """(kind, L2 reason). A guarded IT step is never approvable: an L2 task (D51)."""
    if b.audience == "store":
        return "send_store", None
    if b.audience == "it":
        return ("l2_task", "guard") if b.warnings else ("run_action", None)
    return "l2_task", b.l2_reason or "unmapped"
