"""Intake step 3: drop history lines that name the trick (S4 build step 3).

A history entry whose actor is `System` and whose note matches
`chaos[ _]type|trick ticket` is dropped (dataset: 1 line, INC-00298). Every
other line is kept. The drop is logged with the ticket id only.
"""

from __future__ import annotations

import re

from support_agent.common.logging import get_logger
from support_agent.intake.schema import HistoryEntry

_LEAK_RE = re.compile(r"chaos[ _]type|trick ticket", re.IGNORECASE)
_log = get_logger(__name__)


def is_leak(entry: HistoryEntry) -> bool:
    return (entry.actor or "").strip().casefold() == "system" and bool(_LEAK_RE.search(entry.note))


def drop_leak_lines(ticket_id: str, history: list[HistoryEntry]) -> list[HistoryEntry]:
    kept = [h for h in history if not is_leak(h)]
    if len(kept) != len(history):
        _log.info("intake_leak_lines_dropped", ticket_id=ticket_id, count=len(history) - len(kept))
    return kept
