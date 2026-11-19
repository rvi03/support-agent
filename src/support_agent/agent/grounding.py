"""Quote check (S8 build step 4, D20): code decides whether Triage's runbook is
grounded, never the model.

A citation passes only if:
1. the document was found in the current `kb_rev` for this run (an excluded or
   unknown document comes back `not_found` from the knowledge server);
2. it is a runbook and the cited section belongs to it;
3. when Enrich established the device, the runbook's `device_family` includes
   that device's family (Codex S8: a real quote can come from the wrong family);
4. the quote, whitespace and case folded, is at least 20 characters and a
   substring of that section's own text.

Reused by the S10 gate check 7 and by S11.
"""

from __future__ import annotations

from dataclasses import dataclass

from support_agent.common.text import MIN_QUOTE, normalize
from support_agent.mcp.knowledge.models import Document

FAMILY_OF_ASSET: dict[str, str] = {
    "POS Terminal": "pos",
    "Receipt Printer": "printer",
    "Network Router": "network",
    "Soft Serve Machine": "soft_serve",
    "Self-Order Kiosk": "kiosk",
}

__all__ = ["FAMILY_OF_ASSET", "MIN_QUOTE", "QuoteCheck", "normalize", "verify_quote"]


@dataclass(frozen=True)
class QuoteCheck:
    ok: bool
    reason: str  # "verified" or why it failed


def verify_quote(
    runbook_id: str,
    section_id: str,
    quote: str,
    document: Document | None,
    *,
    device_family: str | None = None,
) -> QuoteCheck:
    if document is None or document.doc_id != runbook_id:
        return QuoteCheck(False, "document_not_found")
    if document.doc_type != "runbook":
        return QuoteCheck(False, "not_a_runbook")
    section = next((s for s in document.sections if s.section_id == section_id), None)
    if section is None:
        return QuoteCheck(False, "section_not_in_runbook")
    if device_family and device_family not in document.device_family:
        return QuoteCheck(False, "wrong_device_family")
    wanted = normalize(quote)
    if len(wanted) < MIN_QUOTE:
        return QuoteCheck(False, "quote_too_short")
    if section.masked_text is None:
        return QuoteCheck(False, "section_text_missing")
    if wanted not in normalize(section.masked_text):
        return QuoteCheck(False, "quote_not_in_section")
    return QuoteCheck(True, "verified")
