"""`process_ticket(raw)` and `process_reply(ticket_id, text)` (S4 approach; design.md, Intake).

Steps in the fixed order of design.md:
 1 schema (allowed fields only; `status` and `resolution_notes` rejected)
 2 contact fields out (the caller writes them to `pii.vault`)
 3 drop leaking System history lines
 4 mask PII (actor pattern, exact contact and known names, Presidio, never-mask list)
 5 safety-net scan of the masked ticket (PIIBlocked: the caller hands off)
 6 moderation of the store's own text (subject and description, or the reply)

Nothing here touches a database; the caller writes the vault row with
`vault.write_vault(conn, ticket_id, result.contact, result.mask_map)`. Steps 5
and 6 run only when a `SafetyNet` and a `Moderator` are passed (the seed hook
masks without moderation; the API and the agent pass both).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from support_agent.intake.leak_lines import drop_leak_lines
from support_agent.intake.masker import Masker
from support_agent.intake.moderation import Moderation, ModerationBudget, Moderator
from support_agent.intake.safety_net import Channel, SafetyNet, register_contact
from support_agent.intake.schema import DESCRIPTION_MAX, MaskedTicket, TicketIn
from support_agent.intake.vault import Contact, split_contact


@dataclass(frozen=True)
class IntakeResult:
    ticket: MaskedTicket
    contact: Contact
    mask_map: dict[str, str]
    moderation: Moderation | None = None
    dropped_lines: int = 0


@dataclass(frozen=True)
class ReplyResult:
    ticket_id: str
    text: str  # masked
    mask_map: dict[str, str]  # the ticket's map, with any new tokens
    moderation: Moderation | None = None


def ticket_texts(ticket: MaskedTicket) -> list[str]:
    """Every text field of the masked ticket, one string each. The safety net scans
    them one by one: spaCy run over a JSON dump finds "names" across field punctuation."""
    texts = [
        ticket.subject,
        ticket.description,
        *(v for v in (ticket.store_name, ticket.category, ticket.subcategory) if v),
        *ticket.tags,
    ]
    for h in ticket.ticket_history:
        texts += [h.actor or "", h.note]
    return [t for t in texts if t]


def store_text(ticket: MaskedTicket) -> str:
    """What the store wrote itself: the text moderation checks."""
    return f"{ticket.subject}\n\n{ticket.description}"


def _moderate(
    text: str, ticket_id: str, moderator: Moderator | None, budget: ModerationBudget | None
) -> Moderation | None:
    if moderator is None:
        return None
    if budget is None:
        raise ValueError("a moderator needs the ticket's moderation budget")
    return moderator.moderate(text, ticket_id, budget)


def process_ticket(
    raw: Mapping[str, Any],
    masker: Masker,
    *,
    safety_net: SafetyNet | None = None,
    moderator: Moderator | None = None,
    budget: ModerationBudget | None = None,
) -> IntakeResult:
    ticket = TicketIn.model_validate(dict(raw))  # 1
    fields, contact = split_contact(ticket)  # 2
    history = drop_leak_lines(ticket.ticket_id, list(ticket.ticket_history))  # 3
    session = masker.session(contact.full_name, contact.phone)  # 4
    fields["subject"] = session.mask_text(ticket.subject)
    fields["description"] = session.mask_text(ticket.description)
    fields["ticket_history"] = session.mask_history(history)
    masked = MaskedTicket.model_validate(fields)
    if safety_net is not None:  # 5
        register_contact(ticket.ticket_id, contact)
        for text in ticket_texts(masked):
            safety_net.scan(text, ticket.ticket_id, Channel.PROMPT)
    moderation = _moderate(store_text(masked), ticket.ticket_id, moderator, budget)  # 6
    return IntakeResult(
        ticket=masked,
        contact=contact,
        mask_map=dict(session.mask_map),
        moderation=moderation,
        dropped_lines=len(ticket.ticket_history) - len(history),
    )


def process_reply(
    ticket_id: str,
    text: str,
    masker: Masker,
    mask_map: Mapping[str, str],
    *,
    safety_net: SafetyNet | None = None,
    moderator: Moderator | None = None,
    budget: ModerationBudget | None = None,
) -> ReplyResult:
    """A store reply: masked with the ticket's own tokens, scanned, then moderated.

    `mask_map` is the ticket's stored map (vault, read as `agent_actor`); the
    contact values must already be registered (`register_contact` or
    `reload_contact`) for the safety net's exact match.
    """
    text = text.strip()
    if not text:
        raise ValueError("empty reply")
    if len(text) > DESCRIPTION_MAX:
        raise ValueError(f"reply longer than {DESCRIPTION_MAX} characters")
    session = masker.session(None, mask_map=dict(mask_map))
    masked = session.mask_text(text)
    if safety_net is not None:
        safety_net.scan(masked, ticket_id, Channel.PROMPT)
    moderation = _moderate(masked, ticket_id, moderator, budget)
    return ReplyResult(ticket_id, masked, dict(session.mask_map), moderation)
