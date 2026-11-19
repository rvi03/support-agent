"""CP12.1: `make ticket FILE=tests/fixtures/new_printer_ticket.json` runs a fresh
ticket end to end through the API and prints the outcome (S12).

The fixture states its expected outcome (route `resolver`, an allowed first step,
status `resolved`); the test asserts it and that the printed outcome matches the
stored rows (Codex S12). D108: every simulated action is bound to the ticket's CMDB
asset; the walk's source spans are persisted with each message, action and
approval; the store messages, ticket update and audit records agree.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.e2e.api_env import API_URL, api_up, db, fixture
from tests.integration.platform_env import ROOT

pytestmark = [pytest.mark.e2e, pytest.mark.integration]

FIXTURE = "new_printer_ticket.json"


@pytest.fixture(scope="module")
def run(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    if not api_up():
        pytest.fail("The API is not running: `make up` starts it")
    out = tmp_path_factory.mktemp("cp12_1") / "outcome.json"
    proc = subprocess.run(
        ["make", "ticket", f"FILE=tests/fixtures/{FIXTURE}"],
        cwd=ROOT, capture_output=True, text=True, timeout=900,
        env={**os.environ, "OUTCOME_FILE": str(out), "API_URL": API_URL},
    )  # fmt: skip
    return {"proc": proc, "view": json.loads(Path(out).read_text()) if out.exists() else None}


def test_fixture_outcome_holds(run: dict[str, Any]) -> None:
    proc = run["proc"]
    assert proc.returncode == 0, proc.stdout[-3000:] + proc.stderr[-2000:]
    assert "PASS: route, first step and status match the fixture" in proc.stdout
    expected = fixture(FIXTURE)["expected"]
    view = run["view"]
    assert view["route"] == expected["route"]
    assert view["walk"]["steps"][0]["step_id"] in expected["first_step_in"]
    assert view["status"] == expected["status"]


def test_printed_outcome_matches_stored_rows(run: dict[str, Any]) -> None:
    view, out = run["view"], run["proc"].stdout
    tid, run_id = view["ticket_id"], view["run_id"]
    with db() as conn:
        t = conn.execute(
            "SELECT route, status, priority, runbook_id, asset_id, submitted_by_user, "
            "source_ticket_id FROM itsm.tickets WHERE run_id = %s AND ticket_id = %s",
            (run_id, tid),
        ).fetchone()
        a = conn.execute("SELECT submitted_by_user, api_status FROM tickets.api_tickets "
                         "WHERE ticket_id = %s", (tid,)).fetchone()  # fmt: skip
        msgs = conn.execute("SELECT kind, body FROM itsm.store_messages WHERE run_id = %s "
                            "AND ticket_id = %s ORDER BY id", (run_id, tid)).fetchall()  # fmt: skip
        acts = conn.execute("SELECT action_id, outcome FROM itsm.actions WHERE run_id = %s "
                            "AND ticket_id = %s ORDER BY id", (run_id, tid)).fetchall()  # fmt: skip
        events = conn.execute("SELECT count(*) FROM audit.events WHERE run_id = %s "
                              "AND ticket_id = %s", (run_id, tid)).fetchone()  # fmt: skip
    assert t is not None and a is not None
    assert (t[0], t[1], t[2], t[3]) == (view["route"], view["status"], view["priority"],
                                        view["runbook_id"])  # fmt: skip
    assert f"route: {t[0]}; status: {t[1]}; priority: {t[2]}" in out
    assert t[5] == a[0] and t[6] is None  # requester = the token's user; not a replay
    assert a[1] == "done"
    assert [(m["kind"], m["text"]) for m in view["messages"]] == [tuple(m) for m in msgs]
    for kind, body in msgs:
        assert f"store message [{kind}]: {body.splitlines()[0]}" in out
    assert [(x["action_id"], x["outcome"]) for x in view["actions"]] == [tuple(x) for x in acts]
    assert view["audit_summary"]["events"] == events[0]
    assert f"audit: {events[0]} events" in out
    assert "summary" in [m[0] for m in msgs]


def test_actions_bind_to_the_cmdb_asset_and_source_spans(run: dict[str, Any]) -> None:
    """D108: the asset of every action is the ticket's CMDB asset (same store), and each
    message, action and approval carries the runbook section it came from."""
    view = run["view"]
    tid, run_id = view["ticket_id"], view["run_id"]
    with db() as conn:
        acts = conn.execute(
            "SELECT x.asset_id, t.asset_id, s.store_id = t.store_id, x.section_id, x.quote, "
            "x.kb_rev = t.kb_rev FROM itsm.actions x JOIN itsm.tickets t USING (run_id, ticket_id) "
            "JOIN data.assets s ON s.asset_id = x.asset_id "
            "WHERE x.run_id = %s AND x.ticket_id = %s", (run_id, tid)).fetchall()  # fmt: skip
        key = (run_id, tid)
        steps = conn.execute("SELECT section_id FROM itsm.store_messages WHERE run_id = %s "
                             "AND ticket_id = %s AND kind = 'step'", key).fetchall()  # fmt: skip
        appr = conn.execute("SELECT section_id, quote, decision FROM itsm.approvals "
                            "WHERE run_id = %s AND ticket_id = %s", key).fetchall()  # fmt: skip
        fixed_audit = conn.execute(
            "SELECT count(*) FROM audit.events WHERE run_id = %s AND ticket_id = %s "
            "AND step = 'itsm' AND action = 'run_fix'", (run_id, tid)).fetchone()  # fmt: skip
    assert acts, "no simulated action ran"
    for asset, ticket_asset, same_store, section, quote, same_rev in acts:
        assert asset == ticket_asset == "PRN-0003-P1"
        assert same_store and same_rev
        assert section.startswith("runbooks/printer-offline.md#") and quote
    assert steps and all(s[0] and s[0].startswith("runbooks/printer-offline.md#") for s in steps)
    for section, quote, decision in appr:
        assert section.startswith("runbooks/printer-offline.md#") and quote
        assert decision in ("approved", "rejected")
    assert fixed_audit[0] >= len(acts)


def test_no_asset_bound_action_while_several_printers_fit() -> None:
    """D108: SW-0003 has two receipt printers; a ticket naming neither may get store
    steps, but no simulated action runs until the target asset is established."""
    from tests.e2e.api_env import As, wait_for

    store = As("mock-store-sw-0003")
    r = store.call("POST", "/tickets", {
        "category": "Printers",
        "subject": "A receipt printer is offline",
        "description": "One of our receipt printers shows Offline on the POS and prints nothing.",
    })  # fmt: skip
    assert r.status_code == 202, r.text
    tid = r.json()["ticket_id"]
    answers = iter(["Done. The power light is on and the cable is in. It still shows Offline."] * 6)

    def step() -> dict[str, Any]:
        view = store.call("GET", f"/tickets/{tid}").json()
        p = view.get("pending")
        if p and p["kind"] in ("store_reply", "answer"):
            store.call("POST", f"/tickets/{tid}/reply",
                       {"pending_id": p["pending_id"], "text": next(answers)})  # fmt: skip
        return view

    view = wait_for(step, lambda v: v["api_status"] in ("done", "failed") and not v["pending"],
                    timeout=600)  # fmt: skip
    with db() as conn:
        acts = conn.execute("SELECT count(*) FROM itsm.actions WHERE ticket_id = %s",
                            (tid,)).fetchone()  # fmt: skip
        appr = conn.execute("SELECT count(*) FROM itsm.approvals WHERE ticket_id = %s",
                            (tid,)).fetchone()  # fmt: skip
    assert acts == (0,) and appr == (0,), view
    assert view["actions"] == []
