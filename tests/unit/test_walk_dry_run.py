"""CP9.3 dry-run checker rules (S9): quotes verified, warnings first, technical
steps never to the store, approval lines flagged."""

from __future__ import annotations

import pytest

from support_agent.eval.walk_dry_run import (
    TECHNICAL,
    Quote,
    WalkTurn,
    check_turn,
    step_item,
    warnings_in,
)
from support_agent.mcp.knowledge.models import Document, SectionRef

pytestmark = pytest.mark.unit

RB = "runbooks/printer-offline.md"
IMMEDIATE = (
    "## Immediate Steps\n\n"
    "1. **Power cycle the printer.** Switch it off for 10 seconds.\n"
    "2. **Restart the terminal.** Hold power for 5 seconds. **Do NOT hold power for >10 "
    "seconds**—that forces a hard power-off.\n"
    "3. Touch inputs do not register when the screen is frozen; note it.\n"
)
SPOOLER = (
    "### Step 4: Verify Print Spooler\n\n"
    "1. Open services.msc and right-click **Print Spooler** → **Restart**.\n"
    "2. Clearing the queue requires L2 approval before you proceed.\n"
)


def _doc() -> Document:
    secs = [
        SectionRef(
            section_id=f"{RB}#immediate",
            parent_section_id=None,
            path="Immediate",
            ord=0,
            masked_text=IMMEDIATE,
        ),  # fmt: skip
        SectionRef(
            section_id=f"{RB}#spooler",
            parent_section_id=None,
            path="Spooler",
            ord=1,
            masked_text=SPOOLER,
        ),  # fmt: skip
    ]
    return Document(doc_id=RB, doc_type="runbook", title="Printer offline", categories=[],
                    device_family=["printer"], covered_systems=[], related=[], revision=None,
                    last_updated=None, truncated=False, masked_text=IMMEDIATE + SPOOLER,
                    sections=secs)  # fmt: skip


def _turn(section: str, quote: str, doer: str = "store", **kw: object) -> WalkTurn:
    data: dict[str, object] = {
        "decision": "next", "warnings": [], "step": {"section_id": f"{RB}#{section}",
        "quote": quote}, "doer": doer, "action_id": None, "ask_approval": False,
        "approval_evidence": None, "reply_quote": None, "reason": "r",
    }  # fmt: skip
    data.update(kw)
    return WalkTurn.model_validate(data)


ACTIONS = {"restart_print_spooler": "reversible", "check_printer_status": "read_only"}


def test_verified_store_step_passes() -> None:
    turn = _turn("immediate", "Power cycle the printer. Switch it off for 10 seconds.")
    assert check_turn(turn, _doc(), ACTIONS, []) == []


def test_invented_quote_fails() -> None:
    turn = _turn("immediate", "Unplug the router and wait two full minutes.")
    assert any("quote_not_in_section" in f for f in check_turn(turn, _doc(), ACTIONS, []))


def test_warning_must_come_first_but_descriptions_do_not_count() -> None:
    step = "Restart the terminal. Hold power for 5 seconds."
    fails = check_turn(_turn("immediate", step), _doc(), ACTIONS, [])
    assert any("warning not given first" in f for f in fails)
    warned = _turn("immediate", step, warnings=[Quote(section_id=f"{RB}#immediate",
                   quote="Do NOT hold power for >10 seconds")])  # fmt: skip
    assert check_turn(warned, _doc(), ACTIONS, []) == []
    desc = _turn("immediate", "Touch inputs do not register when the screen is frozen")
    assert check_turn(desc, _doc(), ACTIONS, []) == []


def test_technical_step_never_goes_to_the_store() -> None:
    step = "Open services.msc and right-click Print Spooler → Restart"
    fails = check_turn(_turn("spooler", step), _doc(), ACTIONS, [])
    assert any("technical step sent to the store" in f for f in fails)
    as_action = _turn("spooler", step, doer="action", action_id="restart_print_spooler")
    assert check_turn(as_action, _doc(), ACTIONS, []) == []


def test_unoffered_action_and_unflagged_approval_line_fail() -> None:
    bad = _turn("spooler", "Open services.msc and right-click Print Spooler → Restart",
                doer="action", action_id="clear_print_queue")  # fmt: skip
    assert any("not offered" in f for f in check_turn(bad, _doc(), ACTIONS, []))
    line = "Clearing the queue requires L2 approval before you proceed."
    assert any("approval" in f for f in check_turn(
        _turn("spooler", line, doer="action", action_id="restart_print_spooler"),
        _doc(), ACTIONS, []))  # fmt: skip
    assert check_turn(_turn("spooler", line, doer="l2"), _doc(), ACTIONS, []) == []


def test_step_item_and_warning_cores() -> None:
    item = step_item(IMMEDIATE, "Restart the terminal. Hold power")
    assert len(item) == 1 and "Do NOT hold" in item[0]
    assert warnings_in(item) == ["do not hold power for 10 "]
    assert not TECHNICAL.search("Ask the store manager whether the driver was updated")
    assert TECHNICAL.search("On the POS terminal, open Settings → Devices and Printers")
