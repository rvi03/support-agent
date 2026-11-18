"""`make seed` intake hook (S4 build step 7, D59).

Runs intake (schema, contact out, leak-line drop, masking, safety-net scan) on
every train ticket in `tickets.source_staging`, as `intake_rw`. It fills
`pii.vault` and writes only the masked rows to `tickets.source_tickets`, the
table the history tools read. One transaction: a safety-net hit on any ticket
writes its audit event, then fails the seed with no masked row written.
Moderation is not run here: train tickets are history, never acted on.

Run `python -m support_agent.intake.seed`.
"""

from __future__ import annotations

import sys
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from support_agent.common.audit import AuditEvent, write_event
from support_agent.common.config import IntakeSettings, get_settings
from support_agent.common.pii_filter import clear_exact_values
from support_agent.intake.masker import Masker
from support_agent.intake.pipeline import process_ticket
from support_agent.intake.reference import load_reference
from support_agent.intake.safety_net import PIIBlocked, SafetyNet
from support_agent.intake.vault import write_vault

STAGING_COLUMNS = (
    "ticket_id",
    "store_id",
    "store_name",
    "submitted_by",
    "contact_phone",
    "date_opened",
    "priority",
    "category",
    "subcategory",
    "subject",
    "description",
    "asset_id",
    "system_version",
    "tags",
    "escalation_flag",
    "related_tickets",
    "ticket_history",
)
MASKED_COLUMNS = tuple(c for c in STAGING_COLUMNS if c not in ("submitted_by", "contact_phone"))
JSON_COLUMNS = ("tags", "related_tickets", "ticket_history")

_UPSERT = (
    f"INSERT INTO tickets.source_tickets ({', '.join(MASKED_COLUMNS)}) "  # noqa: S608 - fixed
    f"VALUES ({', '.join(['%s'] * len(MASKED_COLUMNS))}) ON CONFLICT (ticket_id) DO UPDATE SET "
    + ", ".join(f"{c} = excluded.{c}" for c in MASKED_COLUMNS if c != "ticket_id")
)


def staging_rows(conn: psycopg.Connection[Any]) -> list[dict[str, Any]]:
    rows = conn.execute(
        f"SELECT {', '.join(STAGING_COLUMNS)} FROM tickets.source_staging ORDER BY ticket_id"  # noqa: S608
    ).fetchall()
    out = []
    for row in rows:
        raw = dict(zip(STAGING_COLUMNS, row, strict=True))
        raw["date_opened"] = raw["date_opened"].isoformat()
        out.append(raw)
    return out


def seed_masked(
    conn: psycopg.Connection[Any], audit_conn: psycopg.Connection[Any]
) -> dict[str, int]:
    """Mask every staged ticket; return counts. Raises PIIBlocked on a safety-net hit.

    `audit_conn` is autocommit, so a `pii_blocked` event survives the rollback."""
    masker = Masker(load_reference(conn))
    net = SafetyNet(masker.reference, lambda e: write_event(audit_conn, e), actor="intake_seed")
    counts = {"tickets": 0, "vault_new": 0, "dropped_lines": 0}
    with conn.transaction():
        for raw in staging_rows(conn):
            ticket_id = raw["ticket_id"]
            try:
                result = process_ticket(raw, masker, safety_net=net)
            finally:
                clear_exact_values(ticket_id)
            row = result.ticket.model_dump(mode="json")
            row["date_opened"] = result.ticket.date_opened
            conn.execute(
                _UPSERT,
                tuple(Jsonb(row[c]) if c in JSON_COLUMNS else row[c] for c in MASKED_COLUMNS),
            )
            counts["vault_new"] += write_vault(conn, ticket_id, result.contact, result.mask_map)
            counts["tickets"] += 1
            counts["dropped_lines"] += result.dropped_lines
        write_event(
            conn,
            AuditEvent(
                step="intake_seed",
                actor="intake_seed",
                action="source_tickets_masked",
                result="ok",
                payload=counts,
            ),
        )
    return counts


def main() -> int:
    settings = get_settings(IntakeSettings)
    try:
        url = settings.database_url_intake.get_secret_value()
        with psycopg.connect(url) as conn, psycopg.connect(url, autocommit=True) as audit_conn:
            counts = seed_masked(conn, audit_conn)
    except PIIBlocked as exc:  # the audit event is written before the raise
        print(f"Intake seed failed: {exc}", file=sys.stderr)
        return 1
    print(
        f"Intake: {counts['tickets']} tickets masked into tickets.source_tickets, "
        f"{counts['vault_new']} new vault rows, {counts['dropped_lines']} leak line(s) dropped"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
