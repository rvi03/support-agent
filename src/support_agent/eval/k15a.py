"""K15a (D41, CP10.6): every L2 note has the escalation SOP's mandatory fields.

Independent of the agent (D42): this module reads only the stored note text
(`Label: value` lines) and imports no agent, gate or itsm code, so a bug in the
agent's own checklist check cannot grade itself. The rules come from the SOP's
Required Information Checklist (kb/sop/escalation-procedure.md):

- required: a real value; never `unavailable: ...` and never a placeholder.
- may be unavailable: a real value, or `unavailable: <a real reason>`.
- conditional: required when its condition holds (SOP trigger when the reason is
  `sop_trigger`, conflicts when the reason is `conflict`, warranty when the
  asset id is a real id).
- the contact is `on file (vault)` only (D43): never a name or a phone, and it
  satisfies the contact field and nothing else.

Covered SOP items: ticket id, asset id and type, store, contact, exact error,
first occurrence, frequency, steps with outcomes, KB consulted, devices and users
affected, business impact, workaround. Not applicable in the POC (no channel
for them in the ticket data): screenshots, revenue estimate, the store's
preferred channel and availability.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

CONTACT = "on file (vault)"
UNAVAILABLE = "unavailable:"

REQUIRED = (
    "Ticket ID",
    "Executive summary",
    "Store",
    "Asset type",
    "Store contact",
    "First occurrence",
    "Business impact",
    "Priority and overrides",
    "Escalation reason",
    "Escalated at",
)
MAY_BE_UNAVAILABLE = (
    "Asset ID",
    "Error code or message",
    "Frequency",
    "Steps tried and outcome",
    "KB resources consulted",
    "Devices affected",
    "Users affected",
    "Workaround",
    "Version coverage gap",
)
SOP_TRIGGER, CONFLICTS, WARRANTY = (
    "SOP trigger and evidence",
    "Document conflicts",
    "Warranty",
)
LABELS = (*REQUIRED, *MAY_BE_UNAVAILABLE, SOP_TRIGGER, CONFLICTS, WARRANTY)

_PLACEHOLDER = re.compile(
    r"(?i)^\s*(?:|-+|n/?a|none|null|tbd|todo|unknown|not known|not available|\?+|\[.*\]|"
    r"<.*>|x+)\s*$"
)
# A phone as stores write it: +91 optional, then 10 digits as 5-5, 3-3-4 or one run.
# Dates and times (2025-11-22 10:28) do not match.
_PHONE = re.compile(
    r"(?<![\d-])(?:\+?91[\s-]?)?(?:\d{5}[\s-]?\d{5}|\d{3}[\s-]?\d{3}[\s-]?\d{4})(?![\d-])"
)


@dataclass
class Result:
    ok: bool
    problems: list[str] = field(default_factory=list)


def parse(note: str) -> dict[str, str]:
    """`Label: value` lines; a value may run on over following lines."""
    fields: dict[str, str] = {}
    current: str | None = None
    for line in note.splitlines():
        label, sep, value = line.partition(":")
        if sep and label.strip() in LABELS:
            current = label.strip()
            fields[current] = value.strip()
        elif current:
            fields[current] += " " + line.strip()
    return fields


def _real(value: str | None) -> bool:
    return value is not None and not _PLACEHOLDER.match(value) and len(value.strip()) >= 2


def _unavailable(value: str) -> bool:
    return value.lower().startswith(UNAVAILABLE)


def check(note: str) -> Result:
    f = parse(note)
    out: list[str] = []
    for label in REQUIRED:
        value = f.get(label)
        if value is None:
            out.append(f"{label}: missing")
        elif _unavailable(value) or not _real(value):
            out.append(f"{label}: not a real value")
    for label in MAY_BE_UNAVAILABLE:
        value = f.get(label)
        if value is None:
            out.append(f"{label}: missing")
        elif _unavailable(value):
            if not _real(value[len(UNAVAILABLE) :]):
                out.append(f"{label}: unavailable without a reason")
        elif not _real(value):
            out.append(f"{label}: placeholder")
    contact = f.get("Store contact")
    if contact is not None and contact != CONTACT:
        out.append("Store contact: not 'on file (vault)'")
    for label, value in f.items():
        if label != "Store contact" and value.strip().lower() == CONTACT:
            out.append(f"{label}: holds only the contact marker")
        if _PHONE.search(value) and label not in ("Ticket ID", "Escalated at", "First occurrence"):
            out.append(f"{label}: holds a phone number")
    reason = f.get("Escalation reason", "")
    if reason.startswith("sop_trigger") and not _real(f.get(SOP_TRIGGER)):
        out.append(f"{SOP_TRIGGER}: required for an SOP-trigger escalation")
    if reason.startswith("conflict") and not _real(f.get(CONFLICTS)):
        out.append(f"{CONFLICTS}: required for a conflict escalation")
    asset_id = f.get("Asset ID", "")
    if asset_id and not _unavailable(asset_id) and not _real(f.get(WARRANTY)):
        out.append(f"{WARRANTY}: required when the asset is known")
    return Result(ok=not out, problems=out)
