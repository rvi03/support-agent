"""Database access for the API (S12).

- Reads as `api_rw`: SELECT on the itsm tables and tickets.api_tickets, the audit
  columns without payload, and `kb_admin.current_rev()` (db/sql/012_api.sql).
- Writes as `intake_rw`: the tickets.api_tickets row (before the 202), the masked
  subject after intake, the run state, and the vault row (or the replay copy, D52).

No query here reads pii.vault; real names reach a viewer only through the
store messages of that store's own ticket (P9 is the reply sender's).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from support_agent.intake.vault import VAULT_INSERT, Contact

Row = dict[str, Any]


class DuplicateReplay(Exception):  # noqa: N818 - becomes 409
    """The same source ticket twice in one run (D45)."""


@dataclass(frozen=True)
class Source:
    ticket_id: str
    store_id: str
    date_opened: datetime


_RESOURCE = """
SELECT a.ticket_id, a.run_id, a.store_id, a.submitted_by_user, a.client_id,
       a.source_ticket_id, a.date_opened, a.api_status, a.error, a.subject, a.created_at,
       t.status, t.route, t.priority, t.category, t.real_category, t.asset_id,
       t.assignee_queue, t.runbook_id, t.kb_rev, t.escalate_by, t.resolve_by,
       t.first_response_by, extract(epoch FROM t.clock_offset)::float AS clock_offset_s,
       p.pending_id, p.kind AS pending_kind, p.step_id AS pending_step_id,
       p.approval_id AS pending_approval_id, p.created_at AS pending_since,
       ap.approver_role, ap.kb_rev AS approval_kb_rev, ap.action_id AS approval_action_id,
       ap.expires_at AS approval_expires_at
FROM tickets.api_tickets a
LEFT JOIN itsm.tickets t ON t.run_id = a.run_id AND t.ticket_id = a.ticket_id
LEFT JOIN itsm.pending p ON p.run_id = a.run_id AND p.ticket_id = a.ticket_id
                        AND p.cleared_at IS NULL
LEFT JOIN itsm.approvals ap ON ap.id = p.approval_id
"""


class ApiStore:
    def __init__(self, api_dsn: str, intake_dsn: str) -> None:
        self.read = AsyncConnectionPool(
            api_dsn, min_size=1, max_size=8, open=False, kwargs={"autocommit": True}
        )
        self.write = AsyncConnectionPool(
            intake_dsn, min_size=1, max_size=4, open=False, kwargs={"autocommit": True}
        )

    async def open(self) -> None:
        await self.read.open(wait=True)
        await self.write.open(wait=True)

    async def close(self) -> None:
        await self.read.close()
        await self.write.close()

    # ---- reads (api_rw) ----------------------------------------------------------------

    async def _all(self, query: str, params: tuple[Any, ...] = ()) -> list[Row]:
        async with self.read.connection() as conn:
            cur = await conn.cursor(row_factory=dict_row).execute(query, params)
            return list(await cur.fetchall())

    async def _one(self, query: str, params: tuple[Any, ...] = ()) -> Row | None:
        rows = await self._all(query, params)
        return rows[0] if rows else None

    async def resource(self, ticket_id: str) -> Row | None:
        return await self._one(_RESOURCE + " WHERE a.ticket_id = %s", (ticket_id,))

    async def list_for(
        self,
        *,
        store_id: str | None,
        submitted_by: str | None,
        queues: set[str],
        approver_roles: set[str],
        l2_tasks: bool,
        everything: bool,
        limit: int = 200,
    ) -> list[Row]:
        """The tickets a subject may see, by role (P1, P2, P6). Conditions are OR-ed."""
        conds: list[str] = []
        params: list[Any] = []
        if everything:
            conds.append("TRUE")
        if store_id:
            conds.append("a.store_id = %s")
            params.append(store_id)
        if submitted_by:
            conds.append("a.submitted_by_user = %s")
            params.append(submitted_by)
        if queues:
            conds.append("t.assignee_queue = ANY(%s)")
            params.append(sorted(queues))
        if approver_roles:
            conds.append("(p.kind = 'approval' AND ap.approver_role = ANY(%s))")
            params.append(sorted(approver_roles))
        if l2_tasks:
            conds.append("p.kind = 'l2_task'")
        if not conds:
            return []
        query = (
            _RESOURCE
            + " WHERE "
            + " OR ".join(f"({c})" for c in conds)
            + " ORDER BY a.created_at DESC LIMIT %s"
        )
        return await self._all(query, (*params, limit))

    async def source(self, source_ticket_id: str) -> Source | None:
        row = await self._one(
            "SELECT ticket_id, store_id, date_opened FROM tickets.source_tickets "
            "WHERE ticket_id = %s",
            (source_ticket_id,),
        )
        return Source(row["ticket_id"], row["store_id"], row["date_opened"]) if row else None

    async def current_kb_rev(self) -> str | None:
        row = await self._one("SELECT kb_admin.current_rev() AS rev")
        return str(row["rev"]) if row and row["rev"] else None

    async def details(self, run_id: uuid.UUID, ticket_id: str) -> dict[str, list[Row]]:
        key = (run_id, ticket_id)
        where = " WHERE run_id = %s AND ticket_id = %s ORDER BY "
        return {
            "messages": await self._all(
                "SELECT id, kind, section_id, body, created_at FROM itsm.store_messages"  # noqa: S608
                + where
                + "id",
                key,
            ),
            "comments": await self._all(
                "SELECT id, kind, body, created_at FROM itsm.ticket_comments" + where + "id",  # noqa: S608
                key,
            ),
            "actions": await self._all(
                "SELECT action_id, tier, autonomy_state_at_run, section_id, outcome, result, "  # noqa: S608
                "approval_id, eval_mode, created_at FROM itsm.actions" + where + "id",
                key,
            ),
            "approvals": await self._all(
                "SELECT id, action_id, section_id, approver_role, decision, decided_by, reason, "  # noqa: S608
                "requested_at, decided_at, expires_at, used_at FROM itsm.approvals"
                + where
                + "requested_at",
                key,
            ),
            "l2_tasks": await self._all(
                "SELECT id, section_id, reason, note, result, result_note, done_by, done_at, "  # noqa: S608
                "created_at FROM itsm.l2_tasks" + where + "created_at",
                key,
            ),
            "audit": await self._all(
                "SELECT id, ts, step, actor, action, result, reason FROM audit.events"  # noqa: S608
                + where
                + "id",
                key,
            ),
        }

    async def action_count(self, run_id: uuid.UUID, ticket_id: str) -> int:
        row = await self._one(
            "SELECT count(*) AS n FROM itsm.actions WHERE run_id = %s AND ticket_id = %s",
            (run_id, ticket_id),
        )
        return int(row["n"]) if row else 0

    # ---- writes (intake_rw) ------------------------------------------------------------

    async def add_ticket(
        self,
        *,
        ticket_id: str,
        run_id: uuid.UUID,
        store_id: str,
        submitted_by_user: str,
        client_id: str,
        source_ticket_id: str | None,
        date_opened: datetime,
        raw_key: str,
    ) -> None:
        async with self.write.connection() as conn:
            try:
                await conn.execute(
                    "INSERT INTO tickets.api_tickets (ticket_id, run_id, store_id, "
                    "submitted_by_user, client_id, source_ticket_id, date_opened, raw_key) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                    (ticket_id, run_id, store_id, submitted_by_user, client_id,
                     source_ticket_id, date_opened, raw_key),
                )  # fmt: skip
            except psycopg.errors.UniqueViolation:
                raise DuplicateReplay(source_ticket_id or ticket_id) from None

    async def set_state(
        self, ticket_id: str, api_status: str, *, error: str | None = None,
        subject: str | None = None,
    ) -> None:  # fmt: skip
        async with self.write.connection() as conn:
            await conn.execute(
                "UPDATE tickets.api_tickets SET api_status = %s, error = %s, "
                "subject = COALESCE(%s, subject), updated_at = now() WHERE ticket_id = %s",
                (api_status, error, subject, ticket_id),
            )

    async def write_vault(self, ticket_id: str, contact: Contact, mask_map: dict[str, str]) -> None:
        """The vault row of a new ticket (insert only, as intake_rw; vault.py's SQL)."""
        async with self.write.connection() as conn:
            await conn.execute(
                VAULT_INSERT, (ticket_id, contact.full_name, contact.phone, Jsonb(mask_map))
            )

    async def copy_source_contact(self, source_ticket_id: str, ticket_id: str) -> None:
        async with self.write.connection() as conn:
            await conn.execute(
                "SELECT pii.copy_source_contact(%s, %s)", (source_ticket_id, ticket_id)
            )
