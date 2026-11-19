"""Enrich flag rules with a fake it-data client (S8 build step 2)."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from typing import Any

import pytest

from support_agent.agent.nodes.enrich import enrich
from support_agent.agent.state import Flag
from support_agent.intake.schema import MaskedTicket
from support_agent.mcp.it_data.models import (
    Asset,
    AssetResult,
    AssetSummary,
    KnownBugResult,
    RecentTicketsResult,
    SlaResult,
    StoreAssetsResult,
    StoreResult,
)

pytestmark = pytest.mark.unit

OPENED = datetime(2026, 1, 5, 12, 0, tzinfo=UTC)


class FakeItData:
    def __init__(self, store_types: list[str], asset_type: str | None = "POS Terminal") -> None:
        self.store_types, self.asset_type = store_types, asset_type
        self.calls: list[tuple[str, Any]] = []

    async def get_store(self, store_id: str) -> StoreResult:
        return StoreResult(status="not_found")

    async def get_asset(self, asset_id: str, as_of: datetime) -> AssetResult:
        self.calls.append(("get_asset", asset_id))
        if self.asset_type is None:
            return AssetResult(status="not_found")
        d = date(2025, 1, 1)
        return AssetResult(
            status="found",
            asset=Asset(
                asset_id=asset_id, store_id="SW-0001", asset_type=self.asset_type, make="M",
                model="X", system_version="FoodTech POS v4.2.1", system_name="FoodTech POS",
                version="v4.2.1", install_date=d, last_service_date=d, warranty_expiry=d,
                as_of=d, in_warranty=True, warranty_days_left=1,
            ),
        )  # fmt: skip

    async def get_store_assets(self, store_id: str) -> StoreAssetsResult:
        return StoreAssetsResult(
            status="found",
            assets=[
                AssetSummary(asset_id=f"A{i}", asset_type=t, make="M", model="X", system_version="")
                for i, t in enumerate(self.store_types)
            ],
        )

    async def get_sla(
        self, priority: str, category: str | None, date_opened: datetime
    ) -> SlaResult:
        self.calls.append(("get_sla", priority))
        return SlaResult(
            status="found", priority=priority, category_requested=category,  # type: ignore[arg-type]
            category_used="General", first_response_minutes=1, escalation_to_l2_minutes=1,
            resolution_target_minutes=1, first_response_by=date_opened, escalate_by=date_opened,
            resolve_by=date_opened,
        )  # fmt: skip

    async def get_known_bug(self, system: str, version: str) -> KnownBugResult:
        self.calls.append(("get_known_bug", (system, version)))
        status = "unknown_system" if system == "KitchenBridge" else "found"
        return KnownBugResult(status=status, system=system, version=version)  # type: ignore[arg-type]

    async def get_recent_tickets(
        self, before: datetime, *, store_id: str | None = None,
        asset_id: str | None = None, limit: int = 10,
    ) -> RecentTicketsResult:  # fmt: skip
        return RecentTicketsResult(status="none")


def ticket(**over: Any) -> MaskedTicket:
    base: dict[str, Any] = {
        "ticket_id": "T-1", "store_id": "SW-0001", "date_opened": OPENED,
        "subject": "POS terminal frozen", "description": "Till stuck on the login screen.",
        "priority": "P2", "category": "POS", "asset_id": "POS-0001-T1",
        "system_version": "FoodTech POS v4.2.1",
    }  # fmt: skip
    return MaskedTicket(**(base | over))


def flags(t: MaskedTicket, fake: FakeItData) -> list[Flag]:
    return asyncio.run(enrich(t, fake)).flags


def test_clean_ticket_has_no_flags() -> None:
    assert flags(ticket(), FakeItData(["POS Terminal"])) == []


def test_text_about_another_device_sets_no_flag() -> None:
    # S8a: Enrich never reads the text; Triage judges the device from the facts.
    t = ticket(subject="Soft serve machine error", description="Machine shows an error.")
    fake = FakeItData(["POS Terminal"])
    facts = asyncio.run(enrich(t, fake))
    assert facts.flags == []
    assert [a.asset_type for a in facts.store_assets] == ["POS Terminal"]


def test_asset_not_found_skips_cmdb_bug() -> None:
    fake = FakeItData(["POS Terminal"], asset_type=None)
    assert flags(ticket(), fake) == [Flag.ASSET_NOT_FOUND]
    assert [c for c in fake.calls if c[0] == "get_known_bug"] == [
        ("get_known_bug", ("FoodTech POS", "v4.2.1"))
    ]


def test_unknown_system_and_mismatch_even_with_a_real_asset() -> None:
    t = ticket(system_version="KitchenBridge v2.3")
    assert flags(t, FakeItData(["POS Terminal"])) == [Flag.UNKNOWN_SYSTEM, Flag.VERSION_MISMATCH]


def test_version_without_a_version_token_is_unknown_system() -> None:
    t = ticket(system_version="KitchenBridge")
    assert Flag.UNKNOWN_SYSTEM in flags(t, FakeItData(["POS Terminal"]))


def test_version_compare_ignores_case_and_spaces() -> None:
    t = ticket(system_version="foodtech  POS v4.2.1")
    assert flags(t, FakeItData(["POS Terminal"])) == []


def test_no_asset_id_no_asset_flags() -> None:
    fake = FakeItData(["POS Terminal"])
    assert flags(ticket(asset_id=None, system_version=None), fake) == []
    assert not [c for c in fake.calls if c[0] == "get_asset"]


@pytest.mark.parametrize("priority", [None, "High", "P9"])
def test_missing_or_bad_priority_uses_p3(priority: str | None) -> None:
    fake = FakeItData(["POS Terminal"])
    facts = asyncio.run(enrich(ticket(priority=priority), fake))
    assert facts.priority_used == "P3"
    assert ("get_sla", "P3") in fake.calls
