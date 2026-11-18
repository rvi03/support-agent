"""MCP base (S5): the fixed call order, typed errors, audit of every call (CP5.3 in unit form).

A real Streamable HTTP server runs in a thread with a test signing key, so the
four refused token kinds (none, missing scope, wrong audience, expired) can be
made here; the integration test repeats the ones Keycloak can issue.
"""

from __future__ import annotations

import asyncio
import socket
import threading
import time
from collections.abc import Iterator
from contextlib import asynccontextmanager
from typing import Any, Literal

import httpx
import jwt
import pytest
import uvicorn
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import BaseModel, ConfigDict

from support_agent.agent.tools import McpToolClient, ToolCallError
from support_agent.common.audit import AuditEvent
from support_agent.mcp.base.auth import JwtVerifier
from support_agent.mcp.base.errors import ErrorCode, ToolFailure
from support_agent.mcp.base.opa import Decision, OpaClient
from support_agent.mcp.base.server import McpService, args_hash

pytestmark = pytest.mark.unit

ISSUER = "http://issuer.test/realms/servewell"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def make_token(
    *,
    aud: str | list[str] = "it-data",
    scope: str = "it-data:read",
    azp: str = "agent-reader",
    exp_in: int = 300,
    key: Any = KEY,
    iss: str = ISSUER,
) -> str:
    now = int(time.time())
    claims = {"iss": iss, "aud": aud, "azp": azp, "scope": scope, "iat": now, "exp": now + exp_in}
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "test"})


class EchoIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    n: int


class EchoOut(BaseModel):
    status: Literal["found", "not_found"]
    n: int
    note: str = ""


class FakePool:
    @asynccontextmanager
    async def connection(self) -> Any:
        yield None

    async def open(self) -> None:
        pass

    async def close(self) -> None:
        pass


class FakePolicy:
    def __init__(self, allowed: bool = True) -> None:
        self.allowed = allowed
        self.inputs: list[dict[str, Any]] = []

    async def allow(self, policy_input: dict[str, Any]) -> Decision:
        self.inputs.append(policy_input)
        return Decision(self.allowed, "allowed" if self.allowed else "no policy allows")


class Sink:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []
        self.fail = False

    async def __call__(self, event: AuditEvent) -> None:
        if self.fail:
            raise RuntimeError("db down")
        self.events.append(event)


def build(policy: Any, sink: Sink) -> McpService:
    service = McpService(
        name="it-data",
        policy_prefix="it_data",
        issuer=ISSUER,
        verifier=JwtVerifier(
            issuer=ISSUER, audience="it-data", key_resolver=lambda _t: KEY.public_key()
        ),
        policy=policy,
        pool=FakePool(),  # type: ignore[arg-type]
        audit=sink,
    )

    @service.tool(scope="it-data:read")
    async def get_store(args: EchoIn, conn: Any) -> EchoOut:
        """Echo, for the base tests."""
        if args.n < 0:
            raise RuntimeError("boom")
        if args.n == 99:
            return EchoOut.model_construct(status="weird", n=99)  # type: ignore[arg-type]
        return EchoOut(status="found" if args.n else "not_found", n=args.n)

    return service


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class Running:
    def __init__(self, service: McpService) -> None:
        self.port = _free_port()
        self.url = f"http://127.0.0.1:{self.port}/mcp"
        config = uvicorn.Config(service.app(), port=self.port, log_config=None, lifespan="on")
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self) -> Running:
        self.thread.start()
        deadline = time.time() + 10
        while not self.server.started:
            if time.time() > deadline:
                raise RuntimeError("server did not start")
            time.sleep(0.05)
        return self

    def __exit__(self, *_: object) -> None:
        self.server.should_exit = True
        self.thread.join(5)


@pytest.fixture
def sink() -> Sink:
    return Sink()


@pytest.fixture
def policy() -> FakePolicy:
    return FakePolicy()


@pytest.fixture
def running(policy: FakePolicy, sink: Sink) -> Iterator[Running]:
    with Running(build(policy, sink)) as r:
        yield r


class FixedToken:
    def __init__(self, token: str) -> None:
        self._token = token

    async def token(self, *, refresh: bool = False) -> str:
        return self._token


def call(
    running: Running, token: str, args: dict[str, Any], ticket: str | None = "INC-T1"
) -> dict[str, Any]:
    client = McpToolClient(running.url, FixedToken(token), lambda d, _t: d, retries=0)  # type: ignore[arg-type]
    return asyncio.run(client.call("get_store", args, ticket_id=ticket))


def raw_post(running: Running, token: str | None) -> httpx.Response:
    headers = {"content-type": "application/json", "accept": "application/json, text/event-stream"}
    if token:
        headers["authorization"] = f"Bearer {token}"
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    return httpx.post(running.url, json=body, headers=headers, timeout=5)


# ---- happy path and typed results ------------------------------------------------------


def test_call_runs_in_order_and_audits(running: Running, policy: FakePolicy, sink: Sink) -> None:
    out = call(running, make_token(), {"n": 3})
    assert out == {"status": "found", "n": 3, "note": ""}
    assert policy.inputs == [
        {
            "action": "it_data.get_store",
            "subject": {
                "client_id": "agent-reader",
                "scopes": ["it-data:read"],
                "aud": ["it-data"],
            },
        }
    ]
    (event,) = sink.events
    assert (event.actor, event.action, event.result, event.ticket_id) == (
        "agent-reader",
        "get_store",
        "found",
        "INC-T1",
    )
    assert event.payload["args_sha256"] == args_hash({"n": 3})
    assert "n" not in event.payload


def test_domain_outcome_is_a_result_not_an_error(running: Running, sink: Sink) -> None:
    assert call(running, make_token(), {"n": 0})["status"] == "not_found"
    assert sink.events[-1].result == "not_found"


def test_published_schema_is_the_input_model(running: Running) -> None:
    response = raw_post(running, make_token())
    tools = response.json()["result"]["tools"]
    schema = tools[0]["inputSchema"]
    assert schema["required"] == ["n"]
    assert schema["properties"]["n"]["type"] == "integer"
    assert tools[0]["outputSchema"]["properties"]["status"]["enum"] == ["found", "not_found"]


@pytest.mark.parametrize(
    ("args", "reason"),
    [({}, "n:missing"), ({"n": "abc"}, "n:int_parsing")],
)
def test_bad_arguments_are_invalid_and_audited(
    running: Running, sink: Sink, args: dict[str, Any], reason: str
) -> None:
    with pytest.raises(ToolCallError) as err:
        call(running, make_token(), args)
    assert err.value.code is ErrorCode.INVALID
    assert reason in err.value.reason
    assert sink.events[-1].result == "invalid"
    assert "abc" not in (sink.events[-1].reason or "")  # never the input value


def test_unknown_argument_is_dropped_by_the_sdk(running: Running) -> None:
    # The SDK keeps only declared names; the published schema forbids extras.
    assert call(running, make_token(), {"n": 2, "x": 1})["n"] == 2


def test_tool_crash_is_error_and_audited(running: Running, sink: Sink) -> None:
    with pytest.raises(ToolCallError) as err:
        call(running, make_token(), {"n": -1})
    assert (err.value.code, err.value.reason) == (ErrorCode.ERROR, "RuntimeError")
    assert sink.events[-1].result == "error"


def test_bad_result_fails_validation(running: Running, sink: Sink) -> None:
    with pytest.raises(ToolCallError) as err:
        call(running, make_token(), {"n": 99})
    assert err.value.code is ErrorCode.ERROR
    assert err.value.reason.startswith("result_invalid")


def test_no_audit_no_reply(running: Running, sink: Sink) -> None:
    sink.fail = True
    with pytest.raises(ToolCallError) as err:
        call(running, make_token(), {"n": 3})
    assert (err.value.code, err.value.reason) == (ErrorCode.ERROR, "audit_failed")


# ---- refusals (CP5.3) ------------------------------------------------------------------


def _refusal(sink: Sink) -> AuditEvent:
    (event,) = [e for e in sink.events if e.action == "auth"]
    return event


def test_no_token_is_401_and_audited(running: Running, sink: Sink) -> None:
    assert raw_post(running, None).status_code == 401
    event = _refusal(sink)
    assert (event.result, event.reason, event.actor) == ("denied", "no_token", "unknown")


@pytest.mark.parametrize(
    ("token", "status", "reason"),
    [
        (make_token(scope="kb:read"), 403, "insufficient_scope"),
        (make_token(aud="knowledge", scope="kb:read it-data:read"), 401, "wrong_audience"),
        (make_token(exp_in=-60), 401, "expired"),
        (make_token(key=OTHER_KEY), 401, "invalid_token"),
        (make_token(iss="http://evil.test/realms/servewell"), 401, "wrong_issuer"),
    ],
    ids=["missing-scope", "wrong-audience", "expired", "bad-signature", "wrong-issuer"],
)
def test_bad_token_is_refused_and_audited(
    running: Running, sink: Sink, token: str, status: int, reason: str
) -> None:
    assert raw_post(running, token).status_code == status
    event = _refusal(sink)
    assert (event.result, event.reason) == ("denied", reason)
    assert event.payload == {"http_status": status}


def test_client_sees_typed_denied(running: Running) -> None:
    with pytest.raises(ToolCallError) as err:
        call(running, make_token(exp_in=-60), {"n": 1})
    assert (err.value.code, err.value.reason) == (ErrorCode.DENIED, "http_401")


def test_opa_deny_is_denied_and_audited(policy: FakePolicy, sink: Sink) -> None:
    policy.allowed = False
    with Running(build(policy, sink)) as running, pytest.raises(ToolCallError) as err:
        call(running, make_token(), {"n": 3})
    assert err.value.code is ErrorCode.DENIED
    assert sink.events[-1].result == "denied"
    assert sink.events[-1].reason == "opa:no policy allows"


def test_opa_unreachable_fails_closed(sink: Sink) -> None:
    opa = OpaClient(f"http://127.0.0.1:{_free_port()}")
    with Running(build(opa, sink)) as running, pytest.raises(ToolCallError) as err:
        call(running, make_token(), {"n": 3})
    assert (err.value.code, err.value.reason) == (ErrorCode.DENIED, "opa:opa_unavailable")
    assert sink.events[-1].result == "denied"


def test_opa_client_reads_decision() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/data/servewell/p10_default_deny"
        return httpx.Response(200, json={"result": {"allow": True, "reason": "allowed"}})

    opa = OpaClient("http://opa.test")
    opa._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    assert asyncio.run(opa.allow({"action": "x"})) == Decision(True, "allowed")


def test_opa_client_without_result_denies() -> None:
    opa = OpaClient("http://opa.test")
    opa._http = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _r: httpx.Response(200, json={}))
    )
    assert asyncio.run(opa.allow({"action": "x"})).allowed is False


# ---- errors ----------------------------------------------------------------------------


def test_error_json_round_trip_with_sdk_prefix() -> None:
    text = (
        "Error executing tool get_asset: "
        + ToolFailure(ErrorCode.INVALID, "as_of:missing").as_json()
    )
    failure = ToolFailure.from_json(text)
    assert (failure.code, failure.reason) == (ErrorCode.INVALID, "as_of:missing")
    assert ToolFailure.from_json("garbage").code is ErrorCode.ERROR


# ---- verifier edge cases and DSN -------------------------------------------------------


def test_jwks_unreachable_refuses() -> None:
    def down(_token: str) -> Any:
        raise jwt.PyJWKClientConnectionError("down")

    verifier = JwtVerifier(issuer=ISSUER, audience="it-data", key_resolver=down)
    assert asyncio.run(verifier.verify_token(make_token())) is None


def test_token_without_client_id_refused() -> None:
    now = int(time.time())
    token = jwt.encode(
        {"iss": ISSUER, "aud": "it-data", "iat": now, "exp": now + 60}, KEY, algorithm="RS256"
    )
    verifier = JwtVerifier(
        issuer=ISSUER, audience="it-data", key_resolver=lambda _t: KEY.public_key()
    )
    assert asyncio.run(verifier.verify_token(token)) is None


def test_verifier_needs_a_key_source() -> None:
    with pytest.raises(ValueError, match="jwks_url"):
        JwtVerifier(issuer=ISSUER, audience="it-data")


def test_dsn_replaces_only_the_host() -> None:
    from pydantic import SecretStr

    from support_agent.common.db import dsn

    url = SecretStr("postgresql://it_data_ro:pw@localhost:5432/servewell")
    assert dsn(url) == url.get_secret_value()
    out = dsn(url, "postgres")
    assert "host=postgres" in out and "user=it_data_ro" in out and "dbname=servewell" in out
