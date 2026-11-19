"""Agent-side MCP client (S5 build step 3).

- `TokenSource`: client-credential tokens per service identity (D25), cached
  until shortly before expiry.
- `McpToolClient`: one tool call over Streamable HTTP with the ticket in the
  request `_meta`; retries with backoff on transport faults only; a refused or
  invalid call raises `ToolCallError` at once.
- `ResultGuard`: every result is masked (`Masker.mask_tool_result` on each text
  value) and scanned by the safety net before it can enter graph state (D5, D43).
- `ItDataClient`: typed it-data calls for S8 Enrich and Triage.

langchain-mcp-adapters is not used: it pins `mcp<2` and the servers run on the
MCP SDK 2.x (X12), so the SDK's own client is used.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

import httpx
import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from pydantic import BaseModel

from support_agent.intake.safety_net import Channel
from support_agent.mcp.base.errors import ErrorCode, ToolFailure
from support_agent.mcp.base.server import META_RUN, META_STORE, META_TICKET
from support_agent.mcp.it_data.models import (
    AssetResult,
    KnownBugResult,
    RecentTicketsResult,
    SlaResult,
    StoreAssetsResult,
    StoreResult,
    TicketResult,
)
from support_agent.mcp.knowledge.models import GetDocumentResult, SearchKbResult

TOKEN_REFRESH_MARGIN_S = 30
RETRIES = 3
BACKOFF_S = 0.25
CALL_TIMEOUT_S = 10.0


class ToolCallError(RuntimeError):
    """A typed refusal or failure from a server (denied, invalid, error), or a
    transport fault that outlasted the retries (`error`)."""

    def __init__(self, tool: str, code: ErrorCode, reason: str) -> None:
        super().__init__(f"{tool}: {code}: {reason}")
        self.tool, self.code, self.reason = tool, code, reason


# ---- tokens --------------------------------------------------------------------------


class TokenSource:
    """Client-credentials tokens for one Keycloak client, cached until expiry."""

    def __init__(
        self,
        issuer: str,
        client_id: str,
        client_secret: str,
        *,
        http: httpx.AsyncClient | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.url = issuer.rstrip("/") + "/protocol/openid-connect/token"
        self.client_id, self._secret = client_id, client_secret
        self._http = http or httpx.AsyncClient(timeout=5.0)
        self._clock = clock
        self._token: str | None = None
        self._expires = 0.0
        self._lock = asyncio.Lock()

    async def token(self, *, refresh: bool = False) -> str:
        async with self._lock:
            if refresh or not self._token or self._clock() >= self._expires:
                response = await self._http.post(
                    self.url,
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self.client_id,
                        "client_secret": self._secret,
                    },
                )
                response.raise_for_status()
                body = response.json()
                self._token = str(body["access_token"])
                lifetime = float(body.get("expires_in", 60))
                self._expires = self._clock() + max(lifetime - TOKEN_REFRESH_MARGIN_S, 1.0)
            return self._token


# ---- result guard --------------------------------------------------------------------


class _Masker(Protocol):
    def mask_tool_result(self, text: str) -> str: ...


class _SafetyNet(Protocol):
    def scan(self, text: str, ticket_id: str | None, channel: Channel | str) -> Any: ...


_MACHINE_TOKEN = re.compile(r"^(?=\S*[\d_])\S+$")


def is_machine_token(text: str) -> bool:
    """One word with a digit or `_`: an id, date, version or enum value
    (`not_found`, `INC-00014`, `2026-02-22T05:53:00Z`). Presidio reads `not_found`
    as a name, so these are never masked; the scan still covers them."""
    return bool(_MACHINE_TOKEN.match(text))


def _map_strings(value: Any, fn: Callable[[str], str]) -> Any:
    if isinstance(value, str):
        return value if is_machine_token(value) else fn(value)
    if isinstance(value, list):
        return [_map_strings(v, fn) for v in value]
    if isinstance(value, dict):
        return {k: _map_strings(v, fn) for k, v in value.items()}
    return value


@dataclass(frozen=True)
class ResultGuard:
    """Mask every text value (not machine tokens), then scan the whole result,
    before it enters state. A hit raises `PIIBlocked` (audited by the safety net);
    the caller hands off."""

    masker: _Masker
    safety_net: _SafetyNet

    def __call__(self, data: dict[str, Any], ticket_id: str | None) -> dict[str, Any]:
        masked: dict[str, Any] = _map_strings(data, self.masker.mask_tool_result)
        self.safety_net.scan(json.dumps(masked, ensure_ascii=False), ticket_id, Channel.PROMPT)
        return masked


Guard = Callable[[dict[str, Any], str | None], dict[str, Any]]


class _VaultNet(Protocol):
    def scan_vault(self, text: str, ticket_id: str | None, channel: Channel | str) -> Any: ...


@dataclass(frozen=True)
class KbGuard:
    """KB results are sanitized at index time (D75) and are not masked again: the
    masker reads Title Case KB terms as names. Only the vault exact match runs."""

    safety_net: _VaultNet

    def __call__(self, data: dict[str, Any], ticket_id: str | None) -> dict[str, Any]:
        self.safety_net.scan_vault(json.dumps(data, ensure_ascii=False), ticket_id, Channel.PROMPT)
        return data


# ---- one tool call -------------------------------------------------------------------


class _HttpFailed(Exception):  # noqa: N818 - internal signal
    """The SDK reports an HTTP error as a generic MCPError; the status comes from a
    response hook instead."""

    def __init__(self, status: int | None, cause: BaseException) -> None:
        super().__init__(f"http {status}")
        self.status, self.cause = status, cause


def _is_retryable(failure: _HttpFailed) -> bool:
    """Transport faults and 5xx are retried; 4xx (401/403 included) are not."""
    if failure.status is not None:
        return failure.status >= 500
    return True


class McpToolClient:
    def __init__(
        self,
        url: str,
        tokens: TokenSource,
        guard: Guard,
        *,
        retries: int = RETRIES,
        backoff: float = BACKOFF_S,
    ) -> None:
        self.url, self.tokens, self.guard = url, tokens, guard
        self.retries, self.backoff = retries, backoff

    async def _once(self, tool: str, args: dict[str, Any], meta: dict[str, Any], token: str) -> Any:
        errors: list[int] = []

        async def on_response(response: httpx2.Response) -> None:
            if response.status_code >= 400:
                errors.append(response.status_code)

        http = httpx2.AsyncClient(
            headers={"Authorization": f"Bearer {token}"},
            timeout=httpx2.Timeout(CALL_TIMEOUT_S),
            event_hooks={"response": [on_response]},
        )
        try:
            async with http, Client(streamable_http_client(self.url, http_client=http)) as client:
                return await client.call_tool(tool, args, meta=meta)  # type: ignore[arg-type]
        except Exception as exc:
            raise _HttpFailed(errors[0] if errors else None, exc) from exc

    async def call(
        self,
        tool: str,
        args: dict[str, Any],
        *,
        ticket_id: str | None = None,
        run_id: uuid.UUID | None = None,
        store_id: str | None = None,
    ) -> dict[str, Any]:
        meta: dict[str, Any] = {}
        if ticket_id:
            meta[META_TICKET] = ticket_id
        if run_id:
            meta[META_RUN] = str(run_id)
        if store_id:
            meta[META_STORE] = store_id
        refreshed = False
        attempt = 0
        while True:
            token = await self.tokens.token(refresh=refreshed)
            try:
                result = await self._once(tool, args, meta, token)
                break
            except _HttpFailed as failed:
                if failed.status == 401 and not refreshed:
                    refreshed = True  # the cached token may have just expired: one retry
                    continue
                if failed.status in (401, 403):
                    raise ToolCallError(tool, ErrorCode.DENIED, f"http_{failed.status}") from None
                attempt += 1
                if attempt > self.retries or not _is_retryable(failed):
                    reason = (
                        f"http_{failed.status}" if failed.status else type(failed.cause).__name__
                    )
                    raise ToolCallError(tool, ErrorCode.ERROR, reason) from failed.cause
                await asyncio.sleep(self.backoff * 2 ** (attempt - 1))
        if result.is_error:
            text = " ".join(getattr(c, "text", "") for c in result.content)
            failure = ToolFailure.from_json(text)
            raise ToolCallError(tool, failure.code, failure.reason)
        data = result.structured_content
        if not isinstance(data, dict):
            raise ToolCallError(tool, ErrorCode.ERROR, "no structured result")
        return self.guard(data, ticket_id)


# ---- it-data -------------------------------------------------------------------------


class ItDataClient:
    """Typed it-data calls; every result is masked and scanned (ResultGuard)."""

    def __init__(
        self, client: McpToolClient, *, ticket_id: str, run_id: uuid.UUID | None = None
    ) -> None:
        self.client, self.ticket_id, self.run_id = client, ticket_id, run_id

    async def _call[M: BaseModel](self, tool: str, model: type[M], **args: Any) -> M:
        clean = {
            k: (v.isoformat() if isinstance(v, datetime) else v)
            for k, v in args.items()
            if v is not None
        }
        data = await self.client.call(tool, clean, ticket_id=self.ticket_id, run_id=self.run_id)
        return model.model_validate(data)

    async def get_store(self, store_id: str) -> StoreResult:
        return await self._call("get_store", StoreResult, store_id=store_id)

    async def get_asset(self, asset_id: str, as_of: datetime) -> AssetResult:
        return await self._call("get_asset", AssetResult, asset_id=asset_id, as_of=as_of)

    async def get_store_assets(self, store_id: str) -> StoreAssetsResult:
        return await self._call("get_store_assets", StoreAssetsResult, store_id=store_id)

    async def get_sla(
        self, priority: str, category: str | None, date_opened: datetime
    ) -> SlaResult:
        return await self._call(
            "get_sla", SlaResult, priority=priority, category=category, date_opened=date_opened
        )

    async def get_known_bug(self, system: str, version: str) -> KnownBugResult:
        return await self._call("get_known_bug", KnownBugResult, system=system, version=version)

    async def get_ticket(self, ticket_id: str, before: datetime) -> TicketResult:
        return await self._call("get_ticket", TicketResult, ticket_id=ticket_id, before=before)

    async def get_recent_tickets(
        self,
        before: datetime,
        *,
        store_id: str | None = None,
        asset_id: str | None = None,
        limit: int = 10,
    ) -> RecentTicketsResult:
        return await self._call(
            "get_recent_tickets",
            RecentTicketsResult,
            store_id=store_id,
            asset_id=asset_id,
            before=before,
            limit=limit,
        )


# ---- knowledge -----------------------------------------------------------------------


class KnowledgeClient:
    """Typed knowledge calls with the run in `_meta`, so run-scoped eval exclusions
    and the per-run KB-text budget apply (S6)."""

    def __init__(
        self, client: McpToolClient, *, ticket_id: str, run_id: uuid.UUID | None = None
    ) -> None:
        self.client, self.ticket_id, self.run_id = client, ticket_id, run_id

    async def search_kb(
        self,
        query: str,
        *,
        doc_type: str | None = None,
        device_family: str | None = None,
        k: int = 5,
    ) -> SearchKbResult:
        args: dict[str, Any] = {"query": query, "k": k}
        if doc_type:
            args["doc_type"] = doc_type
        if device_family:
            args["device_family"] = device_family
        data = await self.client.call(
            "search_kb", args, ticket_id=self.ticket_id, run_id=self.run_id
        )
        return SearchKbResult.model_validate(data)

    async def get_document(self, doc_id: str) -> GetDocumentResult:
        data = await self.client.call(
            "get_document",
            {"doc_id": doc_id, "with_section_text": True},
            ticket_id=self.ticket_id,
            run_id=self.run_id,
        )
        return GetDocumentResult.model_validate(data)
