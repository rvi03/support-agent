"""Store message templates (S10 build steps 6, 7, 9; D50, D108).

The LLM writes no text for the store. Every store message is one of these fixed
templates, chosen by a key and filled by code from facts. `{name}` is the only
placeholder for the real contact: it stays in the draft the gate checks and is
filled inside the reply sender after the gate (review M3).

- Redirect: one message per approved destination key; code owns the contacts.
- Clarify: one question per missing-fact key.
- Status: what happens next (L2, L1 engineer, a person, a refusal).
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from support_agent.agent.state import MissingFact, RedirectKey

STORE_TZ = ZoneInfo("Asia/Kolkata")
GREETING = "Hi {name},"

REDIRECTS: dict[RedirectKey, str] = {
    "hr": (
        "this desk handles store IT systems only. For staff, payroll, attendance or "
        "other HR matters, please contact your area HR team through your store manager."
    ),
    "billing": (
        "invoices, subscriptions and licences are handled by the Billing team, not IT "
        "support. Please email Billing@servewell.in with your store ID and the details."
    ),
    "isp": (
        "the internet line itself is managed by your internet service provider. Please "
        "call your ISP's support line (the number is on your router label or ISP bill). "
        "If store devices still cannot connect after the line is restored, reply here."
    ),
    "card_processor": (
        "card processing and payment gateway accounts are handled by your card processor. "
        "Please call their merchant support line (on your card terminal or merchant "
        "agreement). If a ServeWell device still fails after that, reply here."
    ),
}

QUESTIONS: dict[MissingFact, str] = {
    "device": (
        "which device has the problem (for example POS terminal, receipt printer, router, "
        "kiosk or soft-serve machine), and its ID if you can see it?"
    ),
    "error_message": "what exact message or error code does the screen show?",
    "symptom": "what exactly happens when you try to use it?",
    "scope": (
        "is it only one device, or are other devices in the store (other terminals, Wi-Fi, "
        "printers) affected too?"
    ),
    "when_started": "when did this start, and has it happened before?",
}


def when(at: datetime | None) -> str:
    if at is None:
        return "as soon as possible"
    return "by " + at.astimezone(STORE_TZ).strftime("%H:%M IST on %d %b")


def redirect(key: str) -> str | None:
    text = REDIRECTS.get(key)  # type: ignore[call-overload]
    return f"{GREETING} {text}" if text else None


def clarify(key: str) -> str | None:
    text = QUESTIONS.get(key)  # type: ignore[call-overload]
    return f"{GREETING} to help us fix this, {text}" if text else None


def template(kind: str, key: str) -> str | None:
    """The approved draft for a redirect or clarify key (gate check 8)."""
    if kind == "redirect":
        return redirect(key)
    if kind == "clarify":
        return clarify(key)
    return None


def status_l2(ticket_id: str, priority: str, by: datetime | None) -> str:
    return (
        f"{GREETING} your ticket {ticket_id} is now with our L2 support team (priority "
        f"{priority}). They will contact you {when(by)}."
    )


def status_human(ticket_id: str, by: datetime | None) -> str:
    return (
        f"{GREETING} your ticket {ticket_id} needs a support engineer to review it. "
        f"They will contact you {when(by)}."
    )


def status_l1(ticket_id: str, by: datetime | None) -> str:
    return f"{GREETING} an L1 engineer will contact you about ticket {ticket_id} {when(by)}."


def person_will_contact(ticket_id: str) -> str:
    return f"{GREETING} a person from our team will contact you about ticket {ticket_id}."


def refusal(ticket_id: str) -> str:
    return (
        f"{GREETING} we cannot share PINs, passwords or codes, or skip a safety step or "
        f"approval. An engineer will review ticket {ticket_id} and contact you."
    )


# ---- Resolver walk (S11): the framing lines are code templates; the step itself is
# the runbook's own words from an approved binding (D50).


def step_framing(ticket_id: str) -> str:
    return (
        f"{GREETING} for ticket {ticket_id}, please do the next step below and reply with "
        "what you see (for example the lights, the screen message or whether it prints)."
    )


def waiting_approval(ticket_id: str) -> str:
    return (
        f"{GREETING} the next step on ticket {ticket_id} is a remote IT action that needs IT "
        "approval first. We will update you as soon as it is decided."
    )


def waiting_l2(ticket_id: str) -> str:
    return (
        f"{GREETING} an L2 engineer will do the next step on ticket {ticket_id} remotely. "
        "We will update you when it is done."
    )


def walk_summary(ticket_id: str, lines: list[str]) -> str:
    """The fixed summary: which steps and actions were done and what came back."""
    done = "\n".join(f"{n}. {line}" for n, line in enumerate(lines, 1)) or "1. (no steps)"
    return (
        f"{GREETING} ticket {ticket_id} is resolved. What was done:\n{done}\n"
        "If the problem comes back, reply here and we will reopen it."
    )


def fill(draft: str, name: str | None) -> str:
    """Put the real first name back (reply sender only, after the gate)."""
    first = (name or "").split()[0] if name and name.split() else ""
    return draft.replace("{name}", first) if first else draft.replace(" {name},", ",")


def catalogue() -> str:
    """Every fixed word of every template: a name-detector hit made only of these words
    is our own text, not personal data (gate check 5)."""
    import inspect
    import sys

    module = sys.modules[__name__]
    parts = [*REDIRECTS.values(), *QUESTIONS.values(), GREETING]
    for fn in (status_l2, status_human, status_l1, person_will_contact, refusal, step_framing,
               waiting_approval, waiting_l2, walk_summary):  # fmt: skip
        parts.append(inspect.getsource(fn))
    del module
    return "\n".join(parts)
