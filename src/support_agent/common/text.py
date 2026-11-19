"""Quote checks shared by the agent and the itsm-actions server (D20, S8a).

A quote is "in" a text when, with markdown emphasis, case and whitespace folded,
it is at least MIN_QUOTE characters and a substring of that text. This is how
code proves a runbook, a step or an action really comes from the KB, at any
scale and without parsing documents.
"""

from __future__ import annotations

import re

MIN_QUOTE = 20

_MARKUP = re.compile(r"[*_`>#|]+")


def normalize(text: str) -> str:
    return " ".join(_MARKUP.sub(" ", text).split()).casefold()


def quote_in(quote: str, text: str) -> bool:
    wanted = normalize(quote)
    return len(wanted) >= MIN_QUOTE and wanted in normalize(text)
