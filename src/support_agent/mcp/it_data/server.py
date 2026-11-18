"""it-data MCP server: 7 read-only tools over Postgres as `it_data_ro` (S5 build step 2).

Run: `python -m support_agent.mcp.it_data` (container `it-data`, port 8101).
"""

from __future__ import annotations

from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from support_agent.common.config import ItDataSettings
from support_agent.common.db import dsn
from support_agent.mcp.base.auth import JwtVerifier
from support_agent.mcp.base.opa import OpaClient
from support_agent.mcp.base.server import McpService, Policy
from support_agent.mcp.it_data import logic
from support_agent.mcp.it_data.models import (
    Asset,
    AssetResult,
    AssetSummary,
    GetAssetIn,
    GetKnownBugIn,
    GetRecentTicketsIn,
    GetSlaIn,
    GetStoreAssetsIn,
    GetStoreIn,
    GetTicketIn,
    KnownBugResult,
    RecentTicketsResult,
    SlaResult,
    Store,
    StoreAssetsResult,
    StoreResult,
    TicketResult,
    TicketSummary,
)

NAME = "it-data"
POLICY_PREFIX = "it_data"
SCOPE = "it-data:read"

# Only masked schema fields; never status, resolution_notes or ticket_history (CP5.2).
_TICKET_COLUMNS = (
    "ticket_id, store_id, store_name, date_opened, priority, category, subcategory, "
    "subject, description, asset_id, system_version, tags, escalation_flag, related_tickets"
)

Conn = AsyncConnection[Any]


async def _one(conn: Conn, query: str, params: tuple[Any, ...]) -> dict[str, Any] | None:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(query, params)
        return await cur.fetchone()


async def _all(conn: Conn, query: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(query, params)
        return await cur.fetchall()


def register(service: McpService) -> None:
    @service.tool(scope=SCOPE)
    async def get_store(args: GetStoreIn, conn: Conn) -> StoreResult:
        """Store type, city and neighbourhood of a store. No contact fields."""
        row = await _one(
            conn,
            "SELECT store_id, store_name, store_type, city, neighborhood "
            "FROM data.stores WHERE store_id = %s",
            (args.store_id,),
        )
        return (
            StoreResult(status="found", store=Store(**row))
            if row
            else StoreResult(status="not_found")
        )

    @service.tool(scope=SCOPE)
    async def get_asset(args: GetAssetIn, conn: Conn) -> AssetResult:
        """One asset: type, make, model, version and warranty as of the ticket's
        date_opened (`as_of`). `not_found` if the id is not in the asset register."""
        row = await _one(
            conn,
            "SELECT asset_id, store_id, asset_type, make, model, system_version, system_name, "
            "version, install_date, last_service_date, warranty_expiry "
            "FROM data.assets WHERE asset_id = %s",
            (args.asset_id,),
        )
        if row is None:
            return AssetResult(status="not_found")
        day, in_warranty, days_left = logic.warranty(args.as_of, row["warranty_expiry"])
        return AssetResult(
            status="found",
            asset=Asset(**row, as_of=day, in_warranty=in_warranty, warranty_days_left=days_left),
        )

    @service.tool(scope=SCOPE)
    async def get_store_assets(args: GetStoreAssetsIn, conn: Conn) -> StoreAssetsResult:
        """Every device registered at a store."""
        rows = await _all(
            conn,
            "SELECT asset_id, asset_type, make, model, system_version "
            "FROM data.assets WHERE store_id = %s ORDER BY asset_id",
            (args.store_id,),
        )
        if not rows:
            return StoreAssetsResult(status="not_found")
        return StoreAssetsResult(status="found", assets=[AssetSummary(**r) for r in rows])

    @service.tool(scope=SCOPE)
    async def get_sla(args: GetSlaIn, conn: Conn) -> SlaResult:
        """First-response, escalate-by and resolve-by deadlines from date_opened; a
        category missing from the SLA matrix falls back to General."""
        query = (
            "SELECT category, first_response_minutes, escalation_to_l2_minutes, "
            "resolution_target_minutes FROM data.sla_matrix WHERE priority = %s AND category = %s"
        )
        row = None
        if args.category:
            row = await _one(conn, query, (args.priority, args.category))
        status = "found" if row else "fallback_general"
        if row is None:
            row = await _one(conn, query, (args.priority, logic.GENERAL))
        if row is None:  # the matrix itself is incomplete: a data fault, not a ticket fact
            raise LookupError(f"no {logic.GENERAL} SLA row for {args.priority}")
        first, escalate, resolve = logic.sla_deadlines(
            args.date_opened,
            row["first_response_minutes"],
            row["escalation_to_l2_minutes"],
            row["resolution_target_minutes"],
        )
        return SlaResult(
            status=status,
            priority=args.priority,
            category_requested=args.category,
            category_used=row["category"],
            first_response_minutes=row["first_response_minutes"],
            escalation_to_l2_minutes=row["escalation_to_l2_minutes"],
            resolution_target_minutes=row["resolution_target_minutes"],
            first_response_by=first,
            escalate_by=escalate,
            resolve_by=resolve,
        )

    @service.tool(scope=SCOPE)
    async def get_known_bug(args: GetKnownBugIn, conn: Conn) -> KnownBugResult:
        """Known bug, patch status and fix for a system version from the version
        matrix; `unknown_system` if the system is not in it."""
        rows = await _all(
            conn,
            "SELECT system, version, release_date, known_bugs, patch_status, patch_fix, notes "
            "FROM data.version_matrix ORDER BY system, release_date",
            (),
        )
        system_rows = [r for r in rows if logic.norm(r["system"]) == logic.norm(args.system)]
        if not system_rows:
            return KnownBugResult(status="unknown_system", system=args.system, version=args.version)
        versions = [r["version"] for r in system_rows]
        match = [
            r
            for r in system_rows
            if logic.version_key(r["version"]) == logic.version_key(args.version)
        ]
        if not match:
            return KnownBugResult(
                status="unknown_version",
                system=system_rows[0]["system"],
                version=args.version,
                known_versions=versions,
                latest_version=versions[-1],
            )
        r = match[0]
        return KnownBugResult(
            status="found",
            system=r["system"],
            version=r["version"],
            release_date=r["release_date"],
            known_bug=r["known_bugs"],
            patch_status=r["patch_status"],
            patch_fix=r["patch_fix"],
            notes=r["notes"],
            known_versions=versions,
            latest_version=versions[-1],
        )

    @service.tool(scope=SCOPE)
    async def get_ticket(args: GetTicketIn, conn: Conn) -> TicketResult:
        """An earlier ticket cited by the current one: only if it was opened before
        `before`; masked fields only."""
        row = await _one(
            conn,
            f"SELECT {_TICKET_COLUMNS} FROM tickets.source_tickets "  # noqa: S608 - fixed columns
            "WHERE ticket_id = %s AND date_opened < %s",
            (args.ticket_id, args.before),
        )
        if row is None:
            return TicketResult(status="not_found")
        return TicketResult(status="found", ticket=TicketSummary(**row))

    @service.tool(scope=SCOPE)
    async def get_recent_tickets(args: GetRecentTicketsIn, conn: Conn) -> RecentTicketsResult:
        """Earlier tickets for the store or the asset, newest first, opened before
        `before`; masked fields only."""
        rows = await _all(
            conn,
            f"SELECT {_TICKET_COLUMNS} FROM tickets.source_tickets "  # noqa: S608 - fixed columns
            "WHERE date_opened < %s AND (store_id = %s OR asset_id = %s) "
            "ORDER BY date_opened DESC, ticket_id LIMIT %s",
            (args.before, args.store_id, args.asset_id, args.limit),
        )
        if not rows:
            return RecentTicketsResult(status="none")
        return RecentTicketsResult(status="found", tickets=[TicketSummary(**r) for r in rows])


def build_service(
    settings: ItDataSettings,
    *,
    verifier: JwtVerifier | None = None,
    policy: Policy | None = None,
    pool: AsyncConnectionPool[AsyncConnection[Any]] | None = None,
) -> McpService:
    service = McpService(
        name=NAME,
        policy_prefix=POLICY_PREFIX,
        issuer=settings.keycloak_issuer,
        verifier=verifier
        or JwtVerifier(issuer=settings.keycloak_issuer, audience=NAME, jwks_url=settings.jwks_url),
        policy=policy or OpaClient(settings.opa_url),
        pool=pool
        or AsyncConnectionPool(
            dsn(settings.database_url_it_data, settings.db_host),
            min_size=1,
            max_size=5,
            open=False,
            kwargs={"autocommit": True},
        ),
        public_url=f"http://localhost:{settings.it_data_port}",
    )
    register(service)
    return service
