"""Enrich node (S8 build step 2; agent-architecture.md, 2 Enrich): code, no LLM.

Fetches the facts every ticket needs from it-data as `agent-reader` and flags
what code can see on its own:

- `asset_not_found` (E4): the linked asset id is not in the CMDB.
- `unknown_system` (E5): the ticket's `system_version` names a system the version
  matrix does not know, even when the linked asset exists.
- `version_mismatch`: the ticket's `system_version` differs from the CMDB's.

It never reads the ticket's text: whether the device the store describes is at the
store or matches the linked asset is Triage's judgement over these facts (S8a).
A tool refusal or failure raises `ToolCallError` and the graph hands off with
`tool_error`.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Protocol

from support_agent.agent.state import Facts, Flag
from support_agent.ingest.csv_clean import CleaningError, split_system_version
from support_agent.intake.schema import MaskedTicket
from support_agent.mcp.it_data.models import (
    AssetResult,
    KnownBugResult,
    RecentTicketsResult,
    SlaResult,
    StoreAssetsResult,
    StoreResult,
)

DEFAULT_PRIORITY = "P3"
PRIORITIES = ("P1", "P2", "P3", "P4")
RECENT_LIMIT = 20


class ItData(Protocol):
    """The it-data calls Enrich makes (`agent.tools.ItDataClient`)."""

    async def get_store(self, store_id: str) -> StoreResult: ...
    async def get_asset(self, asset_id: str, as_of: datetime) -> AssetResult: ...
    async def get_store_assets(self, store_id: str) -> StoreAssetsResult: ...
    async def get_sla(
        self, priority: str, category: str | None, date_opened: datetime
    ) -> SlaResult: ...
    async def get_known_bug(self, system: str, version: str) -> KnownBugResult: ...
    async def get_recent_tickets(
        self,
        before: datetime,
        *,
        store_id: str | None = None,
        asset_id: str | None = None,
        limit: int = 10,
    ) -> RecentTicketsResult: ...


def _norm(value: str) -> str:
    return " ".join(value.split()).casefold()


async def _no_bug() -> None:
    return None


async def enrich(ticket: MaskedTicket, it_data: ItData) -> Facts:
    opened = ticket.date_opened
    priority = ticket.priority if ticket.priority in PRIORITIES else DEFAULT_PRIORITY

    ticket_system: tuple[str, str] | None = None
    unparsable_version = False
    if ticket.system_version:
        try:
            ticket_system = split_system_version(ticket.system_version)
        except CleaningError:
            unparsable_version = True

    store_r, assets_r, recent_r, sla, asset_r, bug_ticket = await asyncio.gather(
        it_data.get_store(ticket.store_id),
        it_data.get_store_assets(ticket.store_id),
        it_data.get_recent_tickets(
            opened, store_id=ticket.store_id, asset_id=ticket.asset_id, limit=RECENT_LIMIT
        ),
        it_data.get_sla(priority, ticket.category, opened),
        it_data.get_asset(ticket.asset_id, opened) if ticket.asset_id else _no_bug(),
        it_data.get_known_bug(*ticket_system) if ticket_system else _no_bug(),
    )
    others = [p for p in PRIORITIES if p != priority]
    slas = await asyncio.gather(*(it_data.get_sla(p, ticket.category, opened) for p in others))
    sla_by_priority = {priority: sla, **dict(zip(others, slas, strict=True))}
    asset = asset_r.asset if isinstance(asset_r, AssetResult) else None
    bug_cmdb = await it_data.get_known_bug(asset.system_name, asset.version) if asset else None

    flags: list[Flag] = []
    if ticket.asset_id and asset is None:
        flags.append(Flag.ASSET_NOT_FOUND)
    if unparsable_version or (bug_ticket and bug_ticket.status == "unknown_system"):
        flags.append(Flag.UNKNOWN_SYSTEM)
    if (
        asset
        and ticket.system_version
        and _norm(ticket.system_version) != _norm(asset.system_version)
    ):
        flags.append(Flag.VERSION_MISMATCH)

    return Facts(
        store=store_r.store,
        asset=asset,
        store_assets=assets_r.assets,
        recent_tickets=recent_r.tickets,
        sla=sla,
        sla_by_priority=sla_by_priority,
        priority_used=priority,
        known_bug_cmdb=bug_cmdb,
        known_bug_ticket=bug_ticket,
        flags=flags,
    )
