"""What a simulated fix returns (S7 build step 6; D40, D58).

- `SimulatedOutcome` (live and demo): the registry entry's `simulated_result`.
- `FaultCardOutcome` (eval): "fixed" only when the action id is in the ticket's
  fault card `fixed_by_actions`, else "no change"; decided by exact id, never by
  text. S14 loads the cards; until then every eval action is "no change".
`EVAL_MODE` picks the provider (`provider_for`).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal, Protocol

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
        self, action: RegistryAction, *, ticket_id: str, asset_id: str
    ) -> Outcome: ...


class SimulatedOutcome:
    async def outcome(self, action: RegistryAction, *, ticket_id: str, asset_id: str) -> Outcome:
        r = action.simulated_result
        return Outcome(r.outcome, r.text)


@dataclass
class FaultCardOutcome:
    # ticket_id -> the card's fixed_by_actions registry ids (S14 fills it)
    fixed_by_actions: Mapping[str, frozenset[str]] = field(default_factory=dict)

    async def outcome(self, action: RegistryAction, *, ticket_id: str, asset_id: str) -> Outcome:
        if action.action_id in self.fixed_by_actions.get(ticket_id, frozenset()):
            return Outcome("fixed", action.simulated_result.text)
        return Outcome("no_change", f"{action.action_id} ran; no change.")


def provider_for(eval_mode: bool) -> OutcomeProvider:
    return FaultCardOutcome() if eval_mode else SimulatedOutcome()
