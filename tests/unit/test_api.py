"""S12 API in-process: the fixed request order, error mapping and audit, with fakes
(no services). The live checks are tests/e2e (CP12.1, CP12.2)."""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from support_agent.api import service as service_mod
from support_agent.api.app import create_app
from support_agent.api.auth import ApiVerifier, AuthError, Subject, subject_from_claims
from support_agent.api.limits import RateLimits
from support_agent.api.routes import ApiDeps, minutes_left, policy_resource, sla_passed
from support_agent.api.service import ApiError, TicketService, _open_kind
from support_agent.api.store import DuplicateReplay, Source
from support_agent.cli.ticket import approval_body, check
from support_agent.common.audit import AuditEvent
from support_agent.mcp.base.opa import Decision

pytestmark = [pytest.mark.unit, pytest.mark.anyio]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


NOW = datetime(2026, 3, 10, 4, 0, tzinfo=UTC)
ISSUER = "http://kc.test/realms/servewell"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def sign(**claims: Any) -> str:
    base = {"iss": ISSUER, "aud": "api", "iat": int(time.time()), "exp": int(time.time()) + 300,
            "sub": "u-1", "azp": "mock-store-sw-0003", "scope": "api"}  # fmt: skip
    return jwt.encode(base | claims, KEY, algorithm="RS256")


def subject(**kw: Any) -> Subject:
    base: dict[str, Any] = {"client_id": "mock-store-sw-0003", "user": "u-store", "username": None,
            "roles": ("store_user",), "store_id": "SW-0003", "scopes": ("api",),
            "aud": ("api",)}  # fmt: skip
    return Subject(**(base | kw))


# ---- auth ------------------------------------------------------------------------------


def verifier() -> ApiVerifier:
    return ApiVerifier(issuer=ISSUER, key_resolver=lambda _t: KEY.public_key())


async def test_verifier_reads_the_user_context() -> None:
    s = await verifier().verify("Bearer " + sign(
        store_id="SW-0003", name="Testa Mockwell", phone_number="+91-90000-00003",
        realm_access={"roles": ["store_user"]},
    ))  # fmt: skip
    assert (s.client_id, s.user, s.store_id, s.roles) == (
        "mock-store-sw-0003", "u-1", "SW-0003", ("store_user",))  # fmt: skip
    assert s.name == "Testa Mockwell" and "Testa" not in repr(s)
    assert "name" not in s.policy() and "phone" not in s.policy()


@pytest.mark.parametrize(
    ("header", "reason"),
    [
        (None, "no_token"),
        ("Basic abc", "no_token"),
        ("Bearer not-a-jwt", "bad_signature_key"),
        ("Bearer " + sign(aud="it-data"), "wrong_audience"),
        ("Bearer " + sign(iss="http://evil.test"), "wrong_issuer"),
        ("Bearer " + sign(exp=int(time.time()) - 10), "expired"),
    ],
)
async def test_verifier_refuses(header: str | None, reason: str) -> None:
    v = ApiVerifier(issuer=ISSUER, key_resolver=lambda t: (
        KEY.public_key() if t.count(".") == 2 else (_ for _ in ()).throw(jwt.InvalidTokenError())
    ))  # fmt: skip
    with pytest.raises(AuthError) as err:
        await v.verify(header)
    assert err.value.reason == reason


def test_subject_needs_client_and_user() -> None:
    with pytest.raises(AuthError):
        subject_from_claims({"sub": "u"})


# ---- limits and facts ------------------------------------------------------------------


def test_write_limit_per_user_then_per_store() -> None:
    lim = RateLimits(write_user="2/minute", write_store="3/minute")
    a, b = subject(user="a"), subject(user="b")
    assert [lim.hit(a, "write") for _ in range(3)] == [None, None, "write_user"]
    # a's refused write did not count for the store: b gets the store's third write.
    assert [lim.hit(b, "write") for _ in range(2)] == [None, "write_store"]
    assert lim.hit(a, "read") is None


def test_replayer_has_its_own_limit() -> None:
    lim = RateLimits(write_user="1/minute", replay="5/minute")
    runner = subject(client_id="eval-runner", scopes=("api", "eval:replay"), store_id=None)
    assert all(lim.hit(runner, "write") is None for _ in range(5))
    assert lim.hit(runner, "write") == "replay"


def row(**kw: Any) -> dict[str, Any]:
    base = {"ticket_id": "SWT-1", "run_id": uuid.uuid4(), "store_id": "SW-0003",
            "submitted_by_user": "u-store", "assignee_queue": "store", "status": "waiting_store",
            "source_ticket_id": None, "pending_id": None, "escalate_by": NOW + timedelta(hours=1),
            "clock_offset_s": 0.0, "api_status": "running"}  # fmt: skip
    return base | kw


def test_policy_facts_use_ticket_time() -> None:
    r = row(clock_offset_s=-7200.0)  # replay: ticket time is two hours behind wall time
    assert not sla_passed(r, NOW + timedelta(hours=2))
    assert sla_passed(r, NOW + timedelta(hours=4))
    assert minutes_left(r, NOW + timedelta(hours=2)) == 60.0
    facts = policy_resource(r | {"pending_id": uuid.uuid4(), "pending_kind": "approval",
                                 "approver_role": "l2_engineer", "approval_kb_rev": "kb-1"},
                            now=NOW, kb_rev_current="kb-1")  # fmt: skip
    assert facts["pending"] == {"kind": "approval", "approver_role": "l2_engineer",
                                "kb_rev": "kb-1", "guarded": False}  # fmt: skip
    assert facts["sla_passed"] is False and facts["replay"] is False


def test_open_kind_names_the_open_pause_only() -> None:
    pid = uuid.uuid4()
    r = row(pending_id=pid, pending_kind="store_reply")
    assert _open_kind(r, str(pid), ("store_reply", "answer")) == "store_reply"
    with pytest.raises(ApiError) as stale:
        _open_kind(r, str(uuid.uuid4()), ("store_reply",))
    assert stale.value.status == 409
    with pytest.raises(ApiError) as wrong:
        _open_kind(r, str(pid), ("approval", "l2_task"))
    assert wrong.value.reason == "pending_is_store_reply"


# ---- routes with fakes -----------------------------------------------------------------


class FakeStore:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.sources = {"INC-T1": Source("INC-T1", "SW-0007", NOW)}
        self.seen: set[tuple[str, str]] = set()

    async def resource(self, ticket_id: str) -> dict[str, Any] | None:
        return self.rows.get(ticket_id)

    async def source(self, sid: str) -> Source | None:
        return self.sources.get(sid)

    async def current_kb_rev(self) -> str:
        return "kb-1"

    async def list_for(self, **kw: Any) -> list[dict[str, Any]]:
        return [r for r in self.rows.values() if r["store_id"] == kw.get("store_id")]

    async def details(self, run_id: Any, ticket_id: str) -> dict[str, list[Any]]:
        return {k: [] for k in ("messages", "comments", "actions", "approvals", "l2_tasks",
                                "audit")}  # fmt: skip


class FakeService:
    def __init__(self, store: FakeStore) -> None:
        self.store, self.created, self.replies, self.approvals = store, [], [], []

    async def create(self, subj: Subject, body: dict[str, Any], **kw: Any) -> str:
        key = (str(kw["run_id"]), str(kw["source_ticket_id"]))
        if kw["source_ticket_id"] and key in self.store.seen:
            raise DuplicateReplay(kw["source_ticket_id"])
        self.store.seen.add(key)
        self.created.append((subj, body, kw))
        return "SWT-NEW"

    async def reply(self, resource: dict[str, Any], pending_id: str, text: str) -> None:
        _open_kind(resource, pending_id, ("store_reply", "answer"))
        self.replies.append(text)

    async def approve(self, *a: Any) -> None:
        self.approvals.append(a)

    async def state(self, resource: dict[str, Any]) -> tuple[None, None]:
        return None, None

    async def drain(self, timeout: float = 0) -> None:
        return None


class OwnStorePolicy:
    """P1-like rules, enough to test the route order; Rego is tested by `opa test`."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def allow(self, i: dict[str, Any]) -> Decision:
        self.calls.append(i)
        s, r = i["subject"], i.get("resource") or {}
        if i["action"] == "api.approve" and r.get("submitted_by_user") == s["user"]:
            return Decision(False, "self_approval")
        if "store_user" in s["roles"]:
            ok = r.get("store_id") in (None, s["store_id"]) or i["action"] == "api.list_tickets"
            return Decision(ok, "allowed" if ok else "no policy allows")
        return Decision(s["client_id"] == "eval-runner" or "l2_engineer" in s["roles"], "x")


@pytest.fixture
def api() -> tuple[TestClient, ApiDeps, list[AuditEvent]]:
    events: list[AuditEvent] = []

    async def audit(e: AuditEvent) -> int:
        events.append(e)
        return len(events)

    store = FakeStore()
    tokens = {
        "store3": subject(),
        "store2": subject(client_id="mock-store-sw-0002", user="u-2", store_id="SW-0002"),
        "dual": subject(client_id="mock-dual", user="u-store",
                        roles=("store_user", "l2_engineer")),
        "runner": subject(client_id="eval-runner", user="u-eval", roles=(), store_id=None,
                          scopes=("api", "eval:replay")),
    }  # fmt: skip

    class Verifier:
        async def verify(self, header: str | None) -> Subject:
            name = (header or "").removeprefix("Bearer ")
            if name not in tokens:
                raise AuthError("no_token" if not header else "invalid_token")
            return tokens[name]

    d = ApiDeps(
        verifier=Verifier(),
        policy=OwnStorePolicy(),  # type: ignore[arg-type]
        limits=RateLimits(write_user="5/minute"),
        store=store,  # type: ignore[arg-type]
        service=FakeService(store),
        audit=audit,
        wall=lambda: NOW,
    )  # type: ignore[arg-type]
    store.rows["SWT-1"] = row(pending_id=uuid.uuid4(), pending_kind="store_reply")
    return TestClient(create_app(d, max_body_bytes=2_000)), d, events


def h(name: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {name}"}


BODY = {"subject": "Printer offline", "description": "The receipt printer shows Offline."}


def test_health_needs_no_token(api: Any) -> None:
    client, _, events = api
    assert client.get("/health").json() == {"status": "ok"}
    assert events == []


def test_no_token_is_401_and_audited(api: Any) -> None:
    client, _, events = api
    r = client.post("/tickets", json=BODY)
    assert r.status_code == 401
    assert (events[-1].actor, events[-1].result, events[-1].reason) == (
        "anonymous", "denied", "no_token")  # fmt: skip
    assert events[-1].payload["status"] == 401


def test_create_takes_store_and_contact_from_the_token(api: Any) -> None:
    client, d, events = api
    r = client.post("/tickets", json=BODY, headers=h("store3"))
    assert r.status_code == 202 and r.json()["ticket_id"] == "SWT-NEW"
    subj, body, kw = d.service.created[-1]
    assert kw["store_id"] == "SW-0003" and kw["date_opened"] == NOW
    assert kw["source_ticket_id"] is None and set(body) == {"subject", "description"}
    assert events[-1].result == "accepted" and events[-1].action == "api.create_ticket"


@pytest.mark.parametrize("field", ["store_id", "ticket_id", "date_opened", "submitted_by",
                                   "contact_phone", "resolution_notes", "status"])  # fmt: skip
def test_server_fields_are_422(api: Any, field: str) -> None:
    client, d, events = api
    r = client.post("/tickets", json=BODY | {field: "Testa Mockwell"}, headers=h("store3"))
    assert r.status_code == 422
    assert events[-1].payload["status"] == 422 and field in events[-1].payload["fields"]
    assert "Testa" not in str(events[-1].payload)  # names only, never values
    assert d.service.created == []


def test_replay_fields_from_a_store_are_422(api: Any) -> None:
    client, _, events = api
    r = client.post("/tickets", json=BODY | {"source_ticket_id": "INC-T1"}, headers=h("store3"))
    assert r.status_code == 422 and r.json()["error"] == "fields_not_allowed"
    assert events[-1].payload["rule"] == "source_ticket_id"


def test_replay_acts_for_the_source_store_and_dedups_per_run(api: Any) -> None:
    client, d, events = api
    body = BODY | {"source_ticket_id": "INC-T1", "run_id": str(uuid.uuid4())}
    assert client.post("/tickets", json=body, headers=h("runner")).status_code == 202
    _, _, kw = d.service.created[-1]
    assert (kw["store_id"], kw["date_opened"], kw["source_ticket_id"]) == (
        "SW-0007", NOW, "INC-T1")  # fmt: skip
    again = client.post("/tickets", json=body, headers=h("runner"))
    assert again.status_code == 409 and events[-1].payload["rule"] == "D45"


def test_other_store_and_unknown_ticket_look_the_same(api: Any) -> None:
    client, _, events = api
    other = client.get("/tickets/SWT-1", headers=h("store2"))
    missing = client.get("/tickets/SWT-NOPE", headers=h("store2"))
    assert other.status_code == missing.status_code == 404
    assert other.json() == missing.json()
    assert events[-2].ticket_id == "SWT-1" and events[-2].payload["rule"] == "no policy allows"


def test_reply_needs_the_open_pending_id(api: Any) -> None:
    client, d, events = api
    pid = str(d.store.rows["SWT-1"]["pending_id"])
    stale_body = {"pending_id": str(uuid.uuid4()), "text": "done"}
    stale = client.post("/tickets/SWT-1/reply", json=stale_body, headers=h("store3"))
    assert stale.status_code == 409 and events[-1].payload["status"] == 409
    ok = client.post("/tickets/SWT-1/reply", json={"pending_id": pid, "text": "done"},
                     headers=h("store3"))  # fmt: skip
    assert ok.status_code == 202 and d.service.replies == ["done"]


def test_self_approval_is_403(api: Any) -> None:
    client, d, events = api
    body = {"pending_id": str(uuid.uuid4()), "decision": "approve"}
    r = client.post("/tickets/SWT-1/approve", json=body, headers=h("dual"))
    assert r.status_code == 403
    assert events[-1].payload["rule"] == "self_approval" and d.service.approvals == []


def test_rate_limit_comes_before_opa(api: Any) -> None:
    client, d, events = api

    def post() -> int:
        body = {"pending_id": str(uuid.uuid4()), "text": "x"}
        return client.post("/tickets/SWT-1/reply", json=body, headers=h("store2")).status_code

    codes = [post() for _ in range(7)]
    assert codes == [404] * 5 + [429] * 2
    assert events[-1].payload == {"status": 429, "rule": "write_user"}


def test_body_cap_is_413_and_audited(api: Any) -> None:
    client, _, events = api
    r = client.post("/tickets", content=b"x" * 5_000, headers=h("store3") | {
        "content-type": "application/json"})  # fmt: skip
    assert r.status_code == 413
    assert events[-1].reason == "body_too_large" and events[-1].payload["status"] == 413


def test_openapi_lists_the_six_endpoints(api: Any) -> None:
    client, _, _ = api
    paths = client.get("/openapi.json").json()["paths"]
    ops = {(p, m) for p, v in paths.items() for m in v}
    assert ops == {("/health", "get"), ("/tickets", "post"), ("/tickets", "get"),
                   ("/tickets/{ticket_id}", "get"), ("/tickets/{ticket_id}/reply", "post"),
                   ("/tickets/{ticket_id}/approve", "post")}  # fmt: skip


# ---- service: approval payloads --------------------------------------------------------


class FakeLock:
    def __init__(self) -> None:
        self.entered = self.exited = 0

    def hold(self, run_id: str, ticket_id: str) -> FakeLock:
        return self

    async def __aenter__(self) -> None:
        self.entered += 1

    async def __aexit__(self, *a: Any) -> None:
        self.exited += 1


class FakeAgent:
    def __init__(self) -> None:
        self.app, self.deps, self.locker = object(), object(), FakeLock()

    def reload_contact(self, ticket_id: str) -> bool:
        return True

    def mask_text(self, ticket_id: str, text: str) -> str:
        return text.replace("Testa Mockwell", "[PERSON_1]").replace("+91-90000-00001", "[PHONE_1]")


async def test_approve_maps_decisions_to_resume_payloads(monkeypatch: pytest.MonkeyPatch) -> None:
    got: list[tuple[str, dict[str, Any]]] = []

    async def claim(*a: Any, **k: Any) -> None:
        return None

    async def cont(app: Any, run_id: str, tid: str, kind: str, payload: dict[str, Any]) -> Any:
        got.append((kind, payload))

        class Out:
            paused = None

        return Out()

    monkeypatch.setattr(service_mod, "claim", claim)
    monkeypatch.setattr(service_mod, "continue_run", cont)

    class Store:
        async def set_state(self, *a: Any, **k: Any) -> None:
            return None

    agent = FakeAgent()
    svc = TicketService(store=Store(), raw=None, agent=agent, intake=None)  # type: ignore[arg-type]
    l2 = subject(user="u-l2", roles=("l2_engineer",))
    pid = uuid.uuid4()
    card = row(pending_id=pid, pending_kind="approval")
    with pytest.raises(ApiError) as no_reason:
        await svc.approve(l2, card, str(pid), "reject", None, None)
    assert no_reason.value.status == 422
    with pytest.raises(ApiError) as wrong:
        await svc.approve(l2, card, str(pid), "done", None, None)
    assert wrong.value.status == 409
    await svc.approve(l2, card, str(pid), "reject", "not during service", None)
    task = row(pending_id=pid, pending_kind="l2_task")
    await svc.approve(l2, task, str(pid), "failed", None, "driver would not install")
    await svc.drain()
    assert got == [
        ("approval", {"decision": "reject", "decided_by": "u-l2", "reason": "not during service"}),
        ("l2_task", {"result": "failed", "note": "driver would not install", "done_by": "u-l2"}),
    ]
    assert agent.locker.entered == agent.locker.exited == 2  # released after each run


async def test_lost_claim_is_409_and_releases_the_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    from support_agent.agent.runtime import WrongState

    async def claim(*a: Any, **k: Any) -> None:
        raise WrongState("already cleared")

    monkeypatch.setattr(service_mod, "claim", claim)
    agent = FakeAgent()
    svc = TicketService(store=None, raw=None, agent=agent, intake=None)  # type: ignore[arg-type]
    pid = uuid.uuid4()
    with pytest.raises(ApiError) as err:
        await svc.reply(row(pending_id=pid, pending_kind="store_reply"), str(pid), "fixed")
    assert err.value.status == 409
    assert agent.locker.entered == agent.locker.exited == 1


async def test_free_text_is_masked_before_claim_and_resume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S12a: the resume value is persisted by the checkpointer, so a reply, a reject
    reason and an L2 result note reach claim and the graph already masked."""
    got: list[dict[str, Any]] = []
    order: list[str] = []

    async def claim(*a: Any, **k: Any) -> None:
        order.append("claim")

    async def cont(app: Any, run_id: str, tid: str, kind: str, payload: dict[str, Any]) -> Any:
        got.append(payload)

        class Out:
            paused = None

        return Out()

    monkeypatch.setattr(service_mod, "claim", claim)
    monkeypatch.setattr(service_mod, "continue_run", cont)

    class Store:
        async def set_state(self, *a: Any, **k: Any) -> None:
            return None

    agent = FakeAgent()
    real_mask = agent.mask_text

    def mask(tid: str, text: str) -> str:
        order.append("mask")
        return real_mask(tid, text)

    agent.mask_text = mask  # type: ignore[method-assign,assignment]
    svc = TicketService(store=Store(), raw=None, agent=agent, intake=None)  # type: ignore[arg-type]
    pid = uuid.uuid4()
    await svc.reply(row(pending_id=pid, pending_kind="store_reply"), str(pid),
                    "Testa Mockwell here, call +91-90000-00001, still offline")  # fmt: skip
    l2 = subject(user="u-l2", roles=("l2_engineer",))
    await svc.approve(l2, row(pending_id=pid, pending_kind="approval"), str(pid), "reject",
                      "ask Testa Mockwell first", None)  # fmt: skip
    await svc.approve(l2, row(pending_id=pid, pending_kind="l2_task"), str(pid), "done",
                      None, "rang +91-90000-00001, fixed")  # fmt: skip
    await svc.drain()
    blob = repr(got)
    assert "Testa" not in blob and "90000" not in blob, blob
    assert got[0]["text"] == "[PERSON_1] here, call [PHONE_1], still offline"
    assert order.index("mask") < order.index("claim")


# ---- CLI -------------------------------------------------------------------------------


def test_cli_answers_become_bodies() -> None:
    assert approval_body("approval", "p", "approve") == {
        "pending_id": "p", "decision": "approve", "reason": None}  # fmt: skip
    assert approval_body("approval", "p", "reject: not now")["reason"] == "not now"
    assert approval_body("l2_task", "p", "failed: no change") == {
        "pending_id": "p", "decision": "failed", "result": "no change"}  # fmt: skip


def test_cli_check_against_the_fixture() -> None:
    view = {"route": "resolver", "status": "resolved",
            "walk": {"steps": [{"step_id": "po-physical-check"}]}}  # fmt: skip
    expected = {"route": "resolver", "first_step_in": ["po-physical-check"], "status": "resolved"}
    assert check(view, expected) == []
    assert check(view | {"status": "escalated"}, expected) == ["status escalated != resolved"]


# ---- S12a: typed responses for the UI client ------------------------------------------


def test_list_item_fits_the_typed_response() -> None:
    from support_agent.api.routes import list_item
    from support_agent.api.views import TicketItem

    now = datetime(2026, 11, 19, 10, 0, tzinfo=UTC)
    r = row(pending_id=uuid.uuid4(), pending_kind="approval") | {
        "subject": "Printer offline", "status": "waiting_approval", "api_status": "running",
        "escalate_by": now, "clock_offset": timedelta(0), "created_at": now,
    }  # fmt: skip
    item = TicketItem.model_validate(list_item(r, now))
    assert item.pending is not None and item.pending.kind == "approval"


def test_openapi_types_the_ticket_views() -> None:
    schema = create_app().openapi()
    comps = schema["components"]["schemas"]
    for name in ("TicketList", "TicketView", "Message", "Pending", "ApprovalCard", "WalkView"):
        assert name in comps, name
    get = schema["paths"]["/tickets/{ticket_id}"]["get"]["responses"]["200"]
    assert get["content"]["application/json"]["schema"]["$ref"].endswith("/TicketView")
    assert "approval" in comps["Pending"]["properties"]
