"""CP14.6: the store simulator never sees the answer, outcomes are decided by exact
id (D40, D58), and fault cards cannot leak the fix into observations."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from support_agent.eval import fault_cards as fc
from support_agent.eval.simulator import Card, decide, load_card, prompt_data
from support_agent.mcp.itsm.outcome import FaultCardOutcome
from support_agent.mcp.itsm.registry import default_registry

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
CARDS = sorted((ROOT / "eval" / "fault_cards").glob("INC-*.yaml"))
TICKET = {"subject": "Kitchen printer offline", "description": "POS shows printer offline."}
CARD = Card("INC-99901", ("Power light on", "Self-test prints"),
            frozenset({"restart_print_spooler"}), frozenset({"po-usb-reconnect"}),
            ("po-physical-check",))  # fmt: skip


def _view(step: str | None, *, walked: tuple[str, ...] = (), kind: str = "store_reply",
          actions: list[dict[str, Any]] | None = None) -> dict[str, Any]:  # fmt: skip
    return {
        "pending": {"kind": kind, "step_id": step},
        "walk": {"steps": [{"step_id": s} for s in (*walked, step) if s]},
        "actions": actions or [],
    }


@pytest.mark.parametrize("path", CARDS, ids=lambda p: p.stem[-3:])
def test_simulator_prompt_holds_no_answer(path: Path) -> None:
    raw = yaml.safe_load(path.read_text())
    card = load_card(path.parent, path.stem)
    assert card is not None
    registry = {a.action_id: a.description for a in default_registry().actions}
    prompt = prompt_data(TICKET, card, "Please check the cable.")
    data = json.loads(prompt)
    assert set(data) == {"ticket", "observations", "agent_last_message"}
    secret = [raw["fault"], *raw["fixed_by_actions"], *raw["fixed_by_store_steps"],
              *raw.get("requires", []),
              *(registry[a] for a in raw["fixed_by_actions"])]  # fmt: skip
    for text in secret:
        assert text not in prompt, f"{path.stem}: {text!r} reaches the simulator"


def test_fix_step_counts_only_after_its_prerequisite() -> None:
    assert decide(CARD, _view("po-usb-reconnect")) == "no_change"
    assert decide(CARD, _view("po-usb-reconnect", walked=("po-physical-check",))) == "fixed"


def test_similar_step_with_another_id_does_not_fix() -> None:
    assert decide(CARD, _view("po-usb-recognition", walked=("po-physical-check",))) == "no_change"


def test_l2_task_done_fixes_only_when_its_step_is_in_the_card() -> None:
    walked = ("po-physical-check",)
    assert decide(CARD, _view("po-self-test", walked=walked), ["po-usb-driver-reinstall"]) == (
        "no_change"
    )
    assert decide(CARD, _view("po-self-test", walked=walked), ["po-usb-reconnect"]) == "fixed"


def test_it_action_result_and_clarify() -> None:
    assert decide(CARD, _view("po-self-test", actions=[{"outcome": "fixed"}])) == "fixed"
    assert decide(None, _view("po-self-test")) == "no_change"
    assert decide(CARD, _view(None, kind="answer")) == "answer"


def test_eval_mode_action_not_in_card_gives_no_change() -> None:
    reg = default_registry()
    provider = FaultCardOutcome({"INC-99901": frozenset({"restart_print_spooler"})})

    async def run(action_id: str) -> str:
        action = reg.get(action_id)
        assert action is not None
        r = await provider.outcome(action, ticket_id="SWT-1", asset_id="A",
                                   source_ticket_id="INC-99901")  # fmt: skip
        return r.outcome

    assert asyncio.run(run("clear_print_queue")) == "no_change"
    assert asyncio.run(run("restart_print_spooler")) == "fixed"


def test_card_leak_guard_and_ids() -> None:
    steps = fc.load_bindings()["runbooks/printer-offline.md"]
    registry = fc.load_registry()
    good = fc.CardDraft(fault="Spooler stuck", observations=["Printer light is green"],
                        fixed_by_actions=["restart_print_spooler"], fixed_by_store_steps=[],
                        requires=[])  # fmt: skip
    assert fc.validate(good, steps, registry) == []
    leak = good.model_copy(update={"observations": ["Staff did a Print Spooler restart"]})
    assert any("name the fix" in p for p in fc.validate(leak, steps, registry))
    bad_id = good.model_copy(update={"fixed_by_actions": ["format_disk"]})
    assert fc.validate(bad_id, steps, registry) == ["unknown action id format_disk"]
    it_as_store = good.model_copy(update={"fixed_by_store_steps": ["po-usb-spooler-restart"]})
    assert any("IT step" in p for p in fc.validate(it_as_store, steps, registry))
