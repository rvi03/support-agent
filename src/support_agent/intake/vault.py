"""Intake step 2: contact fields go to `pii.vault` (design.md, pii.vault; S4 build step 2).

`split_contact` removes `submitted_by` and `contact_phone` from the ticket;
from then on only the vault holds them. `write_vault` adds the ticket's row as
`intake_rw`, which may only INSERT (db/sql/004_pii.sql); `agent_actor` alone
reads it back (P9). A row that already exists is left as it is, so a re-run
of the seed changes nothing. The insert names no conflict target: Postgres
needs SELECT for one, and the only unique key is `ticket_id` anyway.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from psycopg.types.json import Jsonb

from support_agent.intake.schema import CONTACT_FIELDS, TicketIn


@dataclass(frozen=True)
class Contact:
    full_name: str | None
    phone: str | None

    def values(self) -> list[str]:
        """The exact values the log filter and the safety net look for (D43)."""
        return [v for v in (self.full_name, self.phone) if v]

    def __repr__(self) -> str:  # never print the values
        return "Contact(<hidden>)"


class _Connection(Protocol):
    def execute(self, query: Any, params: Any = ..., /) -> Any: ...


def split_contact(ticket: TicketIn) -> tuple[dict[str, Any], Contact]:
    """The ticket's fields without the contact fields, and the contact."""
    fields = ticket.model_dump(exclude=set(CONTACT_FIELDS))
    return fields, Contact(full_name=ticket.submitted_by, phone=ticket.contact_phone)


_INSERT = """
    INSERT INTO pii.vault (ticket_id, full_name, phone, mask_map)
    VALUES (%s, %s, %s, %s)
    ON CONFLICT DO NOTHING
"""


def write_vault(
    conn: _Connection, ticket_id: str, contact: Contact, mask_map: Mapping[str, str]
) -> bool:
    """Add the vault row; return False if the ticket already had one."""
    cur = conn.execute(
        _INSERT, (ticket_id, contact.full_name, contact.phone, Jsonb(dict(mask_map)))
    )
    return bool(cur.rowcount)
