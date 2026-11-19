"""The action registry (S7 build step 2; D37, D42).

`registry.yaml` is plain data: `yaml.safe_load` plus this Pydantic schema. Its
version is the hash of the file bytes, which the indexer puts into `kb_rev`
(`rule_versions.action_registry`), so `run_fix` can refuse a registry that
drifted from the KB revision a ticket was triaged on. The S14 checker reads the
same file with its own loader and never imports this module. The agent picks an
action from this list as a tool; no text patterns map runbook steps to actions
(S8a).
"""

from __future__ import annotations

import hashlib
from functools import cache
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

REGISTRY_PATH = Path(__file__).with_name("registry.yaml")

Tier = Literal["read_only", "reversible", "destructive"]
Family = Literal["pos", "printer", "network", "online_orders", "soft_serve", "kiosk", "payment"]
Outcome = Literal["fixed", "no_change", "failed"]
ActionId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{2,63}$")]

# data.assets.asset_type -> device family (the KB's family names).
ASSET_FAMILIES: dict[str, Family] = {
    "POS Terminal": "pos",
    "Receipt Printer": "printer",
    "Network Router": "network",
    "Self-Order Kiosk": "kiosk",
    "Soft Serve Machine": "soft_serve",
}


class SimulatedResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    outcome: Outcome
    text: Annotated[str, StringConstraints(min_length=1, max_length=500)]


class RegistryAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    action_id: ActionId
    description: Annotated[str, StringConstraints(min_length=1, max_length=300)]
    device_families: tuple[Family, ...] = Field(min_length=1)
    tier: Tier
    simulated_result: SimulatedResult
    approver: Literal["l2", "vendor"] | None = None


class Registry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    actions: tuple[RegistryAction, ...]
    version: str = ""

    @field_validator("actions")
    @classmethod
    def _unique_ids(cls, actions: tuple[RegistryAction, ...]) -> tuple[RegistryAction, ...]:
        ids = [a.action_id for a in actions]
        dup = sorted({i for i in ids if ids.count(i) > 1})
        if dup:
            raise ValueError(f"duplicate action ids: {dup}")
        return actions

    def get(self, action_id: str) -> RegistryAction | None:
        return next((a for a in self.actions if a.action_id == action_id), None)


def registry_version(raw: bytes) -> str:
    return "reg-" + hashlib.sha256(raw).hexdigest()[:16]


def load_registry(path: Path = REGISTRY_PATH) -> Registry:
    raw = path.read_bytes()
    data = yaml.safe_load(raw)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: not a mapping")
    return Registry.model_validate({**data, "version": registry_version(raw)})


@cache
def default_registry() -> Registry:
    return load_registry()


def family_of(asset_type: str) -> Family | None:
    return ASSET_FAMILIES.get(asset_type)
