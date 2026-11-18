"""Error codes in the KB's error tables (S6: the CP6.4 code test and the K4 pick rule).

A table counts when its header's first cell names a code or an error; a code is a
first-column cell with a digit (E02, E-1, E1001) or an underscore (ERR_TOKEN_EXPIRED).
"""

from __future__ import annotations

import re
from collections.abc import Mapping

_CODE_CELL = re.compile(r"^`?\**`?(?P<code>[A-Z][A-Z0-9]*(?:[-_][A-Za-z0-9]+)*)`?\**`?$")


def table_codes(docs: Mapping[str, str]) -> dict[str, set[str]]:
    """doc_id -> codes in the first column of its error tables."""
    found: dict[str, set[str]] = {}
    for doc_id, text in docs.items():
        header: str | None = None
        for line in text.splitlines():
            s = line.strip()
            if not s.startswith("|"):
                header = None
                continue
            cells = [c.strip() for c in s.strip("|").split("|")]
            if header is None:
                header = cells[0].lower()
                continue
            if set(cells[0]) <= set("-: ") or ("code" not in header and "error" not in header):
                continue
            m = _CODE_CELL.match(cells[0])
            if m and (any(ch.isdigit() for ch in m.group("code")) or "_" in m.group("code")):
                found.setdefault(doc_id, set()).add(m.group("code"))
    return found
