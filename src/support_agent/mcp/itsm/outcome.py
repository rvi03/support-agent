"""What a simulated fix returns (S7 build step 6; D40, D58; S12a).

- `SimulatedOutcome` (live and demo): the registry entry's `simulated_result`.
- `FaultCardOutcome` (eval): "fixed" only when the action id is in the ticket's
  fault card `fixed_by_actions`, else "no change"; decided by exact id, never by
  text. Cards are keyed by the dataset ticket (`INC-…`), so a replayed ticket is
  looked up by its `source_ticket_id`, never by the operational `SWT-…` id (S12a).
`EVAL_MODE` picks the provider (`provider_for`); eval mode refuses to start without
a fault-card folder, so a missing folder can't quietly turn every action into
"no change".
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

import yaml

from support_agent.mcp.itsm.registry import RegistryAction

OutcomeKind = Literal["fixed", "no_change", "failed"]


@dataclass(frozen=True)
class Outcome:
    outcome: OutcomeKind
    text: str

    @property
    def success(self) -> bool:
        """The action ran (for autonomy); "no change" is a run that did not fix it."""
        return self.outcome != "failed"


class OutcomeProvider(Protocol):
    async def outcome(
        self,
        action: RegistryAction,
        *,
        ticket_id: str,
        asset_id: str,
        source_ticket_id: str | None = None,
    ) -> Outcome: ...


class SimulatedOutcome:
    async def outcome(
        self,
        action: RegistryAction,
        *,
        ticket_id: str,
        asset_id: str,
        source_ticket_id: str | None = None,
    ) -> Outcome:
        r = action.simulated_result
        return Outcome(r.outcome, r.text)


@dataclass
class FaultCardOutcome:
    # dataset ticket id -> the card's fixed_by_actions registry ids
    fixed_by_actions: Mapping[str, frozenset[str]] = field(default_factory=dict)

    async def outcome(
        self,
        action: RegistryAction,
        *,
        ticket_id: str,
        asset_id: str,
        source_ticket_id: str | None = None,
    ) -> Outcome:
        card = self.fixed_by_actions.get(source_ticket_id or ticket_id, frozenset())
        if action.action_id in card:
            return Outcome("fixed", action.simulated_result.text)
        return Outcome("no_change", f"{action.action_id} ran; no change.")


def load_fault_cards(folder: Path, known_actions: Collection[str]) -> dict[str, frozenset[str]]:
    """`eval/fault_cards/<ticket>.yaml` -> {ticket: fixed_by_actions}; an unknown action
    id, a card naming another ticket or an empty folder is an error (D58)."""
    if not folder.is_dir():
        raise ValueError(f"fault-card folder {folder} does not exist")
    cards: dict[str, frozenset[str]] = {}
    for path in sorted(folder.glob("*.yaml")):
        data = yaml.safe_load(path.read_bytes()) or {}
        if not isinstance(data, dict):
            raise ValueError(f"{path}: not a mapping")
        ticket = str(data.get("ticket_id") or path.stem)
        if ticket != path.stem:
            raise ValueError(f"{path}: card is for {ticket}, not {path.stem}")
        actions = frozenset(str(a) for a in data.get("fixed_by_actions") or ())
        unknown = actions - set(known_actions)
        if unknown:
            raise ValueError(f"{path}: unknown action ids {sorted(unknown)}")
        cards[ticket] = actions
    if not cards:
        raise ValueError(f"fault-card folder {folder} holds no cards")
    return cards


def provider_for(
    eval_mode: bool, cards: Mapping[str, frozenset[str]] | None = None
) -> OutcomeProvider:
    if not eval_mode:
        return SimulatedOutcome()
    if cards is None:
        raise ValueError("EVAL_MODE needs fault cards (FAULT_CARDS_DIR)")
    return FaultCardOutcome(cards)
