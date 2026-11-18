"""Known names and the never-mask list, built from the data at startup (S4 step 4b, 4d).

- Known names: every submitter and every `L1 Agent - <name>` in the train
  tickets (`tickets.source_staging`), and every region manager (`data.stores`).
- Never-mask list: makes, models, systems and asset types (`data.assets`,
  `data.version_matrix`), store names, cities and neighbourhoods
  (`data.stores`), the ticket taxonomy (priority, category, subcategory, tags),
  fixed brands, store and asset ids, plus code and version patterns. A span
  made only of these is never masked.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Protocol

# Brands and systems named in tickets and the KB that the data tables don't list.
BRANDS = (
    "ServeWell",
    "Zomato",
    "Swiggy",
    "StarMC",
    "Cisco",
    "Cisco SG350",
    "Wi-Fi",
    "WiFi",
    "KitchenBridge",
    "Windows",
    "Epson",
    "UPI",
    "Paytm",
    "PhonePe",
    "Razorpay",
    "Pine Labs",
    "Ingenico",
    "Verifone",
    "Visa",
    "Mastercard",
    "RuPay",
    "Excel",
    "Outlook",
    "Teams",
    "Chrome",
    "Android",
    "TeamViewer",
    "AnyDesk",
)

# Domain words spaCy takes for names in the train tickets: tech terms and menu items.
TERMS = (
    "API",
    "POS",
    "KOT",
    "KDS",
    "Butter Masala",
    "Dal Makhani",
    "Paneer Tikka",
    "Biryani",
    "Freezing cylinder",
)

# Ids, error codes and versions: a span matching one of these is never masked.
ID_PATTERNS = (
    r"SW-\d{4}",  # store id
    r"INC-\d{5}",  # ticket id
    r"[A-Z]{2,6}-\d{4}(?:-[A-Z0-9]{1,4})+",  # asset id, e.g. POS-0023-T2
    r"[A-Z]{1,6}-?\d{2,6}[A-Z]?",  # error codes, models, e.g. E-402, ERR-4521, SG350
    r"v?\d+(?:\.\d+){1,3}[a-z]?",  # versions, IPs
    r"[A-Z]{2,}[0-9]{4,}",  # serials, e.g. FT962050
)
_ID_RE = re.compile("|".join(f"(?:{p})" for p in ID_PATTERNS))
_ACTOR_RE = re.compile(r"^L\d\s+Agent\s*-\s*(?P<name>\S.*)$")


def norm(text: str) -> str:
    return " ".join(text.split()).casefold()


def is_id_like(text: str) -> bool:
    return _ID_RE.fullmatch(text.strip()) is not None


@dataclass(frozen=True)
class Reference:
    known_names: frozenset[str]
    never_mask: frozenset[str]  # normalised phrases and their single words

    def is_never_mask(self, span: str) -> bool:
        """True if the span is a never-mask phrase or made only of never-mask words and ids."""
        key = norm(span.strip(" .,;:!?()[]'\""))
        if not key or key in self.never_mask or is_id_like(span.strip(" .,;:!?()[]'\"")):
            return True
        words = re.findall(r"[\w][\w.\-/]*", span)
        return bool(words) and all(norm(w) in self.never_mask or is_id_like(w) for w in words)

    def phrases_in(self, text: str) -> list[str]:
        """Never-mask phrases (2+ letters) that occur in `text` as whole words, as written."""
        found = []
        for phrase in self.never_mask:
            if len(phrase) < 2:
                continue
            m = re.search(r"(?<![\w-])" + re.escape(phrase) + r"(?![\w-])", text, re.IGNORECASE)
            if m:
                found.append(m.group(0))
        return found


def build_reference(
    known_names: Iterable[str], never_mask_phrases: Iterable[str], words_from: Iterable[str] = ()
) -> Reference:
    """`words_from`: phrases whose single words are also never-mask (makes, places)."""
    phrases = {norm(p) for p in [*never_mask_phrases, *BRANDS, *TERMS] if p and p.strip()}
    words = {norm(w) for p in words_from for w in p.split() if len(w) >= 2}
    names = frozenset(" ".join(n.split()) for n in known_names if n and n.strip())
    return Reference(known_names=names, never_mask=frozenset(phrases | words))


class _Connection(Protocol):
    def execute(self, query: Any, params: Any = ..., /) -> Any: ...


def load_reference(conn: _Connection) -> Reference:
    """Build the reference from Postgres as `intake_rw` (db/sql/006_intake.sql)."""
    stores = conn.execute(
        "SELECT store_id, store_name, city, neighborhood, region_manager FROM data.stores"
    ).fetchall()
    assets = conn.execute(
        "SELECT asset_id, asset_type, make, model, system_name FROM data.assets"
    ).fetchall()
    systems = [r[0] for r in conn.execute("SELECT system FROM data.version_matrix").fetchall()]
    staging = conn.execute(
        "SELECT submitted_by, ticket_history FROM tickets.source_staging"
    ).fetchall()
    # Ticket taxonomy (priority, category, subcategory, tags): never a name, e.g. "Down".
    taxonomy = [
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT v FROM tickets.source_staging, LATERAL ("
            " SELECT priority UNION ALL SELECT category UNION ALL SELECT subcategory"
            " UNION ALL SELECT jsonb_array_elements_text(tags)) AS t(v) WHERE v IS NOT NULL"
        ).fetchall()
    ]

    names: set[str] = {r[4] for r in stores}
    for submitter, history in staging:
        if submitter:
            names.add(submitter)
        for entry in history or []:
            m = _ACTOR_RE.match(str(entry.get("actor") or "").strip())
            if m:
                names.add(m.group("name"))

    places = [p for r in stores for p in (r[1], r[2], r[3])]
    devices = [p for r in assets for p in r[1:]] + systems
    ids = [r[0] for r in stores] + [r[0] for r in assets]
    return build_reference(
        names, [*places, *devices, *ids, *taxonomy], words_from=[*places, *devices]
    )
