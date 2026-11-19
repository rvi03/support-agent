"""itsm-actions logic without services (S7): registry schema and version, the
autonomy rule, and the outcome providers."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from pydantic import ValidationError

from support_agent.mcp.itsm.autonomy import Autonomy, next_state
from support_agent.mcp.itsm.outcome import (
    FaultCardOutcome,
    SimulatedOutcome,
    load_fault_cards,
    provider_for,
)
from support_agent.mcp.itsm.registry import (
    ASSET_FAMILIES,
    REGISTRY_PATH,
    load_registry,
    registry_version,
)

pytestmark = pytest.mark.unit


# ---- registry --------------------------------------------------------------------------


def test_registry_ships_every_tier() -> None:
    reg = load_registry()
    assert {a.tier for a in reg.actions} == {"destructive", "read_only", "reversible"}
    assert reg.version == registry_version(REGISTRY_PATH.read_bytes())
    assert reg.version.startswith("reg-") and len(reg.version) == 20


def test_registry_version_follows_the_bytes(tmp_path: Path) -> None:
    raw = REGISTRY_PATH.read_bytes()
    copy = tmp_path / "r.yaml"
    copy.write_bytes(raw + b"\n# edited\n")
    assert load_registry(copy).version != load_registry().version


def test_registry_rejects_duplicates_and_unknown_keys(tmp_path: Path) -> None:
    entry = (
        "  - action_id: {id}\n    description: d\n    device_families: [printer]\n"
        "    tier: read_only\n"
        "    simulated_result: {{outcome: no_change, text: t}}\n{extra}"
    )
    cases = {
        "dup": entry.format(id="a_one", extra="") * 2,
        "extra": entry.format(id="a_one", extra="    risk: low\n"),
        "match": entry.format(id="a_one", extra="    match: [[x]]\n"),  # S8a: no patterns
        "tier": entry.format(id="a_one", extra="").replace("read_only", "safe"),
    }
    for name, body in cases.items():
        path = tmp_path / f"{name}.yaml"
        path.write_text("actions:\n" + body)
        with pytest.raises((ValidationError, ValueError)):
            load_registry(path)


def test_every_asset_type_has_a_family() -> None:
    # data.assets holds exactly these five types (S3).
    assert set(ASSET_FAMILIES) == {
        "POS Terminal", "Receipt Printer", "Network Router", "Self-Order Kiosk",
        "Soft Serve Machine",
    }  # fmt: skip


# ---- autonomy rule ---------------------------------------------------------------------

SUP, AUTO = Autonomy("supervised", 0), Autonomy("autonomous", 1)


def test_reversible_promotes_after_n_approved_runs() -> None:
    one = next_state("reversible", SUP, approved=True, success=True, threshold=1)
    assert one.promote and one.after.runs == 1
    state = SUP
    for i in range(1, 3):
        step = next_state("reversible", state, approved=True, success=True, threshold=3)
        assert not step.promote and step.after == Autonomy("supervised", i)
        state = step.after
    assert next_state("reversible", state, approved=True, success=True, threshold=3).promote


def test_reject_or_failure_resets_to_supervised() -> None:
    for tier in ("reversible", "destructive"):
        for approved, success in ((False, False), (True, False)):
            step = next_state(tier, AUTO, approved=approved, success=success, threshold=1)
            assert step.after == Autonomy("supervised", 0) and not step.promote


def test_destructive_is_never_a_promotion_candidate() -> None:
    state = SUP
    for _ in range(5):
        step = next_state("destructive", state, approved=True, success=True, threshold=1)
        assert not step.promote and step.after.state == "supervised"
        state = step.after


def test_read_only_is_not_tracked() -> None:
    step = next_state("read_only", SUP, approved=False, success=False, threshold=1)
    assert step.after == SUP and not step.promote


def test_unapproved_supervised_run_does_not_count() -> None:
    step = next_state("reversible", Autonomy("supervised", 2), approved=False, success=True,
                      threshold=3)  # fmt: skip
    assert step.after == Autonomy("supervised", 2) and not step.promote


# ---- outcomes --------------------------------------------------------------------------


def test_simulated_outcome_is_the_registry_result() -> None:
    action = load_registry().get("restart_print_spooler")
    assert action is not None
    out = asyncio.run(SimulatedOutcome().outcome(action, ticket_id="INC-90001", asset_id="A"))
    assert (out.outcome, out.text) == ("fixed", action.simulated_result.text)
    assert out.success


def test_fault_card_fixes_only_listed_ids() -> None:
    reg = load_registry()
    spooler, queue = reg.get("restart_print_spooler"), reg.get("clear_print_queue")
    assert spooler is not None and queue is not None
    cards = FaultCardOutcome({"INC-90001": frozenset({"restart_print_spooler"})})
    hit = asyncio.run(cards.outcome(spooler, ticket_id="INC-90001", asset_id="A"))
    miss = asyncio.run(cards.outcome(queue, ticket_id="INC-90001", asset_id="A"))
    other = asyncio.run(cards.outcome(spooler, ticket_id="INC-90002", asset_id="A"))
    assert (hit.outcome, miss.outcome, other.outcome) == ("fixed", "no_change", "no_change")
    assert miss.success  # ran, did not fix: not a failure for autonomy


def test_eval_mode_picks_fault_cards() -> None:
    assert isinstance(provider_for(True, {}), FaultCardOutcome)
    assert isinstance(provider_for(False), SimulatedOutcome)
    with pytest.raises(ValueError, match="FAULT_CARDS_DIR"):
        provider_for(True)  # eval mode never runs without cards (S12a)


def test_replayed_ticket_is_looked_up_by_source_id() -> None:
    """S12a: cards are keyed by the dataset ticket; the API gives a replay a new
    operational id, so the lookup must use source_ticket_id."""
    spooler = load_registry().get("restart_print_spooler")
    assert spooler is not None
    cards = FaultCardOutcome({"INC-99042": frozenset({"restart_print_spooler"})})
    replay = asyncio.run(cards.outcome(spooler, ticket_id="SWT-0123456789ab", asset_id="A",
                                       source_ticket_id="INC-99042"))  # fmt: skip
    by_operational_id = asyncio.run(
        cards.outcome(spooler, ticket_id="SWT-0123456789ab", asset_id="A")
    )
    assert (replay.outcome, by_operational_id.outcome) == ("fixed", "no_change")


def test_fault_cards_load_and_reject_bad_cards(tmp_path: Path) -> None:
    ids = [a.action_id for a in load_registry().actions]
    (tmp_path / "INC-99042.yaml").write_text(
        "ticket_id: INC-99042\nfixed_by_actions: [restart_print_spooler]\n"
    )
    (tmp_path / "INC-99043.yaml").write_text("ticket_id: INC-99043\nfixed_by_actions: []\n")
    assert load_fault_cards(tmp_path, ids) == {
        "INC-99042": frozenset({"restart_print_spooler"}), "INC-99043": frozenset(),
    }  # fmt: skip
    (tmp_path / "INC-99044.yaml").write_text("fixed_by_actions: [format_disk]\n")
    with pytest.raises(ValueError, match="unknown action"):
        load_fault_cards(tmp_path, ids)
    with pytest.raises(ValueError, match="does not exist"):
        load_fault_cards(tmp_path / "missing", ids)
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ValueError, match="no cards"):
        load_fault_cards(empty, ids)
