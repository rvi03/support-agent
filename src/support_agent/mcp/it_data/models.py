"""Pydantic input and result models of the 7 it-data tools (design.md, IT data tools).

Domain outcomes are typed results in each model's `status` (`not_found`,
`unknown_system`, ...); only refusals and failures are tool errors (base/errors.py).
The history tools return `TicketSummary`, which has no `status`,
`resolution_notes` or `ticket_history` field and forbids extra keys (CP5.2).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, model_validator

StoreId = Annotated[str, StringConstraints(pattern=r"^SW-\d{4}$")]
Id = Annotated[str, StringConstraints(min_length=1, max_length=64, strip_whitespace=True)]
Text = Annotated[str, StringConstraints(min_length=1, max_length=120, strip_whitespace=True)]
Priority = Literal["P1", "P2", "P3", "P4"]
Found = Literal["found", "not_found"]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# ---- get_store ----------------------------------------------------------------------


class GetStoreIn(_In):
    store_id: StoreId


class Store(_Out):
    store_id: str
    store_name: str
    store_type: str
    city: str
    neighborhood: str


class StoreResult(_Out):
    status: Found
    store: Store | None = None


# ---- get_asset ----------------------------------------------------------------------


class GetAssetIn(_In):
    asset_id: Id
    as_of: AwareDatetime = Field(description="The ticket's date_opened; never 'now'.")


class Asset(_Out):
    asset_id: str
    store_id: str
    asset_type: str
    make: str
    model: str
    system_version: str
    system_name: str
    version: str
    install_date: date
    last_service_date: date
    warranty_expiry: date
    as_of: date
    in_warranty: bool
    warranty_days_left: int = Field(description="Negative once the warranty has ended.")


class AssetResult(_Out):
    status: Found
    asset: Asset | None = None


# ---- get_store_assets ----------------------------------------------------------------


class GetStoreAssetsIn(_In):
    store_id: StoreId


class AssetSummary(_Out):
    asset_id: str
    asset_type: str
    make: str
    model: str
    system_version: str


class StoreAssetsResult(_Out):
    status: Found
    assets: list[AssetSummary] = Field(default_factory=list)


# ---- get_sla ------------------------------------------------------------------------


class GetSlaIn(_In):
    priority: Priority
    category: Text | None = None
    date_opened: AwareDatetime


class SlaResult(_Out):
    status: Literal["found", "fallback_general"]
    priority: Priority
    category_requested: str | None
    category_used: str
    first_response_minutes: int
    escalation_to_l2_minutes: int
    resolution_target_minutes: int
    first_response_by: datetime
    escalate_by: datetime
    resolve_by: datetime


# ---- get_known_bug ------------------------------------------------------------------


class GetKnownBugIn(_In):
    system: Text
    version: Annotated[str, StringConstraints(min_length=1, max_length=32, strip_whitespace=True)]


class KnownBugResult(_Out):
    status: Literal["found", "unknown_system", "unknown_version"]
    system: str
    version: str
    release_date: date | None = None
    known_bug: str | None = Field(default=None, description="None: no known bug.")
    patch_status: Literal["Yes", "No", "Partial"] | None = None
    patch_fix: str | None = None
    notes: str | None = None
    known_versions: list[str] = Field(default_factory=list)
    latest_version: str | None = None


# ---- history: get_ticket, get_recent_tickets ----------------------------------------


class TicketSummary(_Out):
    """Masked schema fields of an earlier ticket. Its own `ticket_history` is left
    out: its later lines can run past the asking ticket's `date_opened`."""

    ticket_id: str
    store_id: str
    store_name: str | None
    date_opened: datetime
    priority: str | None
    category: str | None
    subcategory: str | None
    subject: str
    description: str
    asset_id: str | None
    system_version: str | None
    tags: list[str]
    escalation_flag: bool | None
    related_tickets: list[str]


class GetTicketIn(_In):
    ticket_id: Id
    before: AwareDatetime = Field(description="The asking ticket's date_opened.")


class TicketResult(_Out):
    status: Found
    ticket: TicketSummary | None = None


class GetRecentTicketsIn(_In):
    store_id: StoreId | None = None
    asset_id: Id | None = None
    before: AwareDatetime = Field(description="The asking ticket's date_opened.")
    limit: int = Field(default=10, ge=1, le=20)

    @model_validator(mode="after")
    def _one_key(self) -> GetRecentTicketsIn:
        if not self.store_id and not self.asset_id:
            raise ValueError("store_id or asset_id is required")
        return self


class RecentTicketsResult(_Out):
    status: Literal["found", "none"]
    tickets: list[TicketSummary] = Field(default_factory=list)
