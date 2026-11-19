"""Agent-side MCP client (S5 build step 3): token cache, retry, result guard."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from support_agent.agent import tools
from support_agent.agent.tools import McpToolClient, ResultGuard, TokenSource, ToolCallError
from support_agent.intake.safety_net import Channel, Hit, PIIBlocked
from support_agent.mcp.base.errors import ErrorCode

pytestmark = pytest.mark.unit


def test_token_is_cached_until_near_expiry() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        assert b"grant_type=client_credentials" in request.content
        return httpx.Response(200, json={"access_token": f"t{len(calls)}", "expires_in": 300})

    now = [1000.0]
    source = TokenSource(
        "http://kc.test/realms/servewell",
        "agent-reader",
        "secret",
        http=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        clock=lambda: now[0],
    )

    async def run() -> list[str]:
        out = [await source.token(), await source.token()]
        now[0] += 300 - tools.TOKEN_REFRESH_MARGIN_S  # within the margin: refresh
        out.append(await source.token())
        out.append(await source.token(refresh=True))
        return out

    assert asyncio.run(run()) == ["t1", "t1", "t2", "t3"]


class FakeTokens:
    def __init__(self) -> None:
        self.refreshes = 0

    async def token(self, *, refresh: bool = False) -> str:
        self.refreshes += refresh
        return "tok"


class Result:
    def __init__(self, data: Any, is_error: bool = False, text: str = "") -> None:
        self.structured_content, self.is_error = data, is_error
        self.content = [type("C", (), {"text": text})()]


def client_with(outcomes: list[Any], **kw: Any) -> tuple[McpToolClient, FakeTokens]:
    tokens = FakeTokens()
    client = McpToolClient("http://x/mcp", tokens, lambda d, _t: d, backoff=0, **kw)  # type: ignore[arg-type]

    async def once(*_a: Any) -> Any:
        outcome = outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    client._once = once  # type: ignore[method-assign]
    return client, tokens


def failed(status: int | None) -> tools._HttpFailed:
    return tools._HttpFailed(status, ConnectionError("x"))


def test_retries_transport_faults_then_succeeds() -> None:
    client, _ = client_with([failed(None), failed(503), Result({"status": "found"})])
    assert asyncio.run(client.call("get_store", {})) == {"status": "found"}


def test_gives_up_after_retries() -> None:
    client, _ = client_with([failed(None)] * 3, retries=2)
    with pytest.raises(ToolCallError) as err:
        asyncio.run(client.call("get_store", {}))
    assert err.value.code is ErrorCode.ERROR


def test_401_refreshes_the_token_once_then_denies() -> None:
    client, tokens = client_with([failed(401), failed(401)])
    with pytest.raises(ToolCallError) as err:
        asyncio.run(client.call("get_store", {}))
    assert (err.value.code, err.value.reason, tokens.refreshes) == (ErrorCode.DENIED, "http_401", 1)


def test_403_is_not_retried() -> None:
    client, _ = client_with([failed(403)])
    with pytest.raises(ToolCallError) as err:
        asyncio.run(client.call("get_store", {}))
    assert err.value.code is ErrorCode.DENIED


def test_typed_tool_error_is_raised_as_is() -> None:
    text = 'Error executing tool get_asset: {"error": "invalid", "reason": "as_of:missing"}'
    client, _ = client_with([Result(None, is_error=True, text=text)])
    with pytest.raises(ToolCallError) as err:
        asyncio.run(client.call("get_asset", {}))
    assert (err.value.code, err.value.reason) == (ErrorCode.INVALID, "as_of:missing")


class FakeMasker:
    def mask_tool_result(self, text: str) -> str:
        return text.replace("Testa Mockwell", "[PERSON_1]")


class FakeNet:
    def __init__(self, block: bool = False) -> None:
        self.block, self.seen = block, []

    def scan(self, text: str, ticket_id: str | None, channel: Channel | str) -> list[Hit]:
        self.seen.append((text, ticket_id, channel))
        if self.block:
            raise PIIBlocked(ticket_id, Channel(channel), [Hit("pattern", "PHONE", 0, 1)])
        return []

    scan_token = scan


def test_guard_masks_every_text_value_then_scans() -> None:
    net = FakeNet()
    guard = ResultGuard(FakeMasker(), net)
    data = {"store": {"name": "Testa Mockwell"}, "list": ["Testa Mockwell", 3], "n": 1}
    out = guard(data, "INC-T1")
    assert out == {"store": {"name": "[PERSON_1]"}, "list": ["[PERSON_1]", 3], "n": 1}
    # Each text value is scanned on its own, after masking (D67).
    assert [t for t, _, _ in net.seen] == ["[PERSON_1]", "[PERSON_1]"]
    assert all(ticket == "INC-T1" and channel is Channel.PROMPT for _, ticket, channel in net.seen)


def test_guard_scans_machine_tokens_without_the_name_model() -> None:
    """A phone is one word with digits: it is never masked as a token, but its scan
    still runs (regexes and vault), so it is blocked."""
    from support_agent.intake.reference import build_reference
    from support_agent.intake.safety_net import SafetyNet

    net = SafetyNet(build_reference((), ()), lambda e: 0, actor="test")
    with pytest.raises(PIIBlocked):
        ResultGuard(NameEverything(), net)({"phone": "+91-90000-00001"}, None)
    assert ResultGuard(NameEverything(), net)({"s": "not_found"}, None) == {"s": "not_found"}


class NameEverything:
    def mask_tool_result(self, text: str) -> str:
        return "[PERSON_1]"


def test_guard_never_masks_machine_tokens() -> None:
    # Presidio read `not_found` as a PERSON in S5; ids, dates and enums stay as they are.
    data = {
        "status": "not_found",
        "asset_id": "POS-9791-T1",
        "as_of": "2026-02-22T05:53:00Z",
        "version": "v4.2.1",
        "note": "Testa Mockwell",
        "name": "Testa",
    }
    out = ResultGuard(NameEverything(), FakeNet())(data, None)
    assert out == {**data, "note": "[PERSON_1]", "name": "[PERSON_1]"}


def test_guard_blocks_on_a_hit() -> None:
    with pytest.raises(PIIBlocked):
        ResultGuard(FakeMasker(), FakeNet(block=True))({"a": "+91-90000-00001"}, "INC-T1")
