"""CP12.2: the API's refusals, each audited (S12 tests per checkpoint).

Against the running API with real mock-user tokens (Codex S12: no stubs):
other store 404, self-approval 403, duplicate replay 409, replay or contact fields
from a store 422, stale approve 409 with no new action, no token 401, reply with
nothing pending 409, `resolution_notes` 422, 30 fast posts 429.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from tests.e2e.api_env import As, api_up, db, denials, fixture, tune_ticket_ids, wait_for

pytestmark = [pytest.mark.e2e, pytest.mark.integration]

STORE = As("mock-store-sw-0003")
OTHER_STORE = As("mock-store-sw-0002")
DUAL = As("mock-dual")  # store_user + l2_engineer at SW-0001
L2 = As("mock-l2")
RUNNER = As("eval-runner")
NOBODY = As(None)

PRINTER = {
    "category": "Printers", "asset_id": "PRN-0003-P1",
    "subject": "Receipt printer offline (negative test)",
    "description": "The receipt printer at the front counter shows Offline on the POS.",
}  # fmt: skip


@pytest.fixture(scope="module", autouse=True)
def _api() -> None:
    if not api_up():
        pytest.fail("The API is not running: `make up` starts it")


@pytest.fixture(scope="module")
def since() -> datetime:
    return datetime.now(UTC) - timedelta(seconds=5)


def _post(who: As, body: dict[str, Any]) -> str:
    r = who.call("POST", "/tickets", body)
    assert r.status_code == 202, r.text
    return str(r.json()["ticket_id"])


@pytest.fixture(scope="module")
def store_ticket() -> str:
    """A SW-0003 ticket (its run continues in the background)."""
    return _post(STORE, PRINTER)


@pytest.fixture(scope="module")
def handoff_ticket() -> dict[str, Any]:
    """A SW-0003 ticket that ends in the L2 queue with nothing pending (payment outage)."""
    raw = fixture("tickets/route_handoff.json")
    body = {k: raw[k] for k in ("category", "asset_id", "subject", "description")}
    tid = _post(STORE, body)
    return wait_for(
        lambda: STORE.call("GET", f"/tickets/{tid}").json(),
        lambda v: v["api_status"] in ("done", "failed") and not v["pending"],
    )


def test_other_store_gets_404(store_ticket: str, since: datetime) -> None:
    r = OTHER_STORE.call("GET", f"/tickets/{store_ticket}")
    assert r.status_code == 404
    assert r.json()["error"] == "not_found"
    unknown = OTHER_STORE.call("GET", "/tickets/SWT-DOESNOTEXIST")
    assert unknown.status_code == 404
    assert unknown.json() == r.json()  # the same answer: existence is not revealed
    assert denials(since, action="api.get_ticket", status=404, actor="mock-store-sw-0002",
                   ticket_id=store_ticket)  # fmt: skip


def test_self_approval_gets_403(since: datetime) -> None:
    tid = _post(DUAL, {**PRINTER, "asset_id": None, "subject": "Printer offline (dual user)"})
    r = DUAL.call("POST", f"/tickets/{tid}/approve",
                  {"pending_id": str(uuid.uuid4()), "decision": "approve"})  # fmt: skip
    assert r.status_code == 403, r.text
    events = denials(since, action="api.approve", status=403, actor="mock-dual", ticket_id=tid)
    assert events and events[0][3]["rule"] == "self_approval"


def test_same_source_ticket_twice_in_one_run_gets_409(since: datetime) -> None:
    source = tune_ticket_ids()[0]
    run_id = str(uuid.uuid4())
    with db() as conn:
        row = conn.execute("SELECT subject, description FROM tickets.source_tickets "
                           "WHERE ticket_id = %s", (source,)).fetchone()  # fmt: skip
    assert row, source
    body = {"source_ticket_id": source, "run_id": run_id, "subject": row[0], "description": row[1]}
    first = RUNNER.call("POST", "/tickets", body)
    assert first.status_code == 202, first.text
    assert first.json()["run_id"] == run_id
    second = RUNNER.call("POST", "/tickets", body)
    assert second.status_code == 409, second.text
    assert denials(since, action="api.create_ticket", status=409, actor="eval-runner")
    with db() as conn:  # the replay keeps its source for scoring; date_opened is the source's
        got = conn.execute(
            "SELECT a.source_ticket_id, a.date_opened = s.date_opened FROM tickets.api_tickets a "
            "JOIN tickets.source_tickets s ON s.ticket_id = a.source_ticket_id "
            "WHERE a.ticket_id = %s", (first.json()["ticket_id"],)).fetchone()  # fmt: skip
    assert got == (source, True)


@pytest.mark.parametrize(
    "extra",
    [
        {"source_ticket_id": "INC-MOCK-1"},
        {"date_opened": "2026-03-10T04:00:00+00:00"},
        {"submitted_by": "Testa Mockwell"},
        {"contact_phone": "+91-90000-00001"},
        {"ticket_id": "SWT-MINE"},
        {"store_id": "SW-0002"},
        {"resolution_notes": "Fixed by restarting the spooler."},
    ],
    ids=lambda e: next(iter(e)),
)
def test_store_cannot_send_server_fields(extra: dict[str, Any], since: datetime) -> None:
    r = STORE.call("POST", "/tickets", {**PRINTER, **extra})
    assert r.status_code == 422, r.text
    events = denials(since, action="api.create_ticket", status=422, actor="mock-store-sw-0003")
    assert any(next(iter(extra)) in str(e[3]) for e in events), events


def test_stale_approve_gets_409_and_runs_nothing(handoff_ticket: dict[str, Any],
                                                 since: datetime) -> None:  # fmt: skip
    tid = handoff_ticket["ticket_id"]
    assert handoff_ticket["assignee_queue"] == "l2", handoff_ticket
    with db() as conn:
        before = conn.execute("SELECT count(*) FROM itsm.actions WHERE ticket_id = %s",
                              (tid,)).fetchone()  # fmt: skip
    r = L2.call("POST", f"/tickets/{tid}/approve",
                {"pending_id": str(uuid.uuid4()), "decision": "approve"})  # fmt: skip
    assert r.status_code == 409, r.text
    with db() as conn:
        after = conn.execute("SELECT count(*) FROM itsm.actions WHERE ticket_id = %s",
                             (tid,)).fetchone()  # fmt: skip
    assert after == before
    assert denials(since, action="api.approve", status=409, actor="mock-l2", ticket_id=tid)


def test_no_token_gets_401(since: datetime) -> None:
    assert NOBODY.call("GET", "/tickets").status_code == 401
    assert NOBODY.call("POST", "/tickets", PRINTER).status_code == 401
    bad = NOBODY.call("GET", "/tickets", headers={"Authorization": "Bearer not-a-jwt"})
    assert bad.status_code == 401
    reasons = {e[2] for e in denials(since, action="api.list_tickets", status=401,
                                     actor="anonymous")}  # fmt: skip
    assert {"no_token", "bad_signature_key"} <= reasons


def test_reply_with_nothing_pending_gets_409(handoff_ticket: dict[str, Any],
                                             since: datetime) -> None:  # fmt: skip
    tid = handoff_ticket["ticket_id"]
    r = STORE.call("POST", f"/tickets/{tid}/reply",
                   {"pending_id": str(uuid.uuid4()), "text": "Is anyone there?"})  # fmt: skip
    assert r.status_code == 409, r.text
    assert denials(since, action="api.reply", status=409, actor="mock-store-sw-0003",
                   ticket_id=tid)  # fmt: skip


def test_thirty_fast_posts_get_429(handoff_ticket: dict[str, Any], since: datetime) -> None:
    """Another store's user, so the SW-0003 user keeps its budget for CP12.1. The rate
    limit comes before OPA, so the posts count although the ticket is not theirs (404)."""
    tid = handoff_ticket["ticket_id"]
    codes = [OTHER_STORE.call("POST", f"/tickets/{tid}/reply",
                              {"pending_id": str(uuid.uuid4()), "text": "ping"}).status_code
             for _ in range(30)]  # fmt: skip
    assert 429 in codes, codes
    assert set(codes) <= {404, 429}
    assert codes.index(429) == 20  # API_RATE_WRITE_USER=20/minute
    assert denials(since, action="api.reply", status=429, actor="mock-store-sw-0002")
