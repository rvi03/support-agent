"""The shared MCP server base (S5 build step 1; S6 and S7 reuse it unchanged).

Every tool call runs in one fixed order:

    call -> 1 verify JWT -> 2 scope -> 3 OPA -> 4 validate args -> tool
         -> 5 validate result -> 6 audit -> reply

Steps 1 (and the server-wide scope) run in the SDK's resource-server hook with
`JwtVerifier`; a refusal there is audited by `RefusalAudit`. Steps 2-6 run in
the wrapper below, so a call with bad arguments is audited as `invalid` too:
the SDK sees lenient arguments and publishes the tool's own Pydantic schema.

A tool is an async function `(args: InModel, conn: AsyncConnection) -> OutModel`
registered with `@service.tool(scope=...)`. A call carries the ticket in the
request `_meta` (`servewell/ticket_id`, `servewell/run_id`, and for writes the
bound `servewell/store_id`, S7) for the audit row.
If the audit write fails, the call fails (D9).
"""

from __future__ import annotations

import hashlib
import inspect
import json
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Protocol, get_type_hints

import structlog
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.tools import Tool
from mcp.server.transport_security import TransportSecuritySettings
from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel, ValidationError
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import ASGIApp

from support_agent.common.audit import AuditEvent, awrite_event
from support_agent.mcp.base.auth import JwtVerifier, RefusalAudit
from support_agent.mcp.base.errors import ErrorCode, ToolFailure
from support_agent.mcp.base.opa import Decision

_log = structlog.get_logger(__name__)

META_TICKET = "servewell/ticket_id"
META_RUN = "servewell/run_id"
# The ticket's store, set by agent code from intake (the token or the source row),
# never by the LLM; itsm-actions checks every write against it (S7).
META_STORE = "servewell/store_id"
MCP_PATH = "/mcp"

ToolFn = Callable[[Any, AsyncConnection[Any]], Awaitable[BaseModel]]
AuditSink = Callable[[AuditEvent], Awaitable[None]]


class Policy(Protocol):
    """What the wrapper asks OPA; `OpaClient` fits, tests pass a fake."""

    async def allow(self, policy_input: dict[str, Any], /) -> Decision: ...


@dataclass(frozen=True)
class ToolSpec:
    name: str
    scope: str
    in_model: type[BaseModel]
    out_model: type[BaseModel]
    fn: ToolFn
    description: str


def args_hash(raw: dict[str, Any]) -> str:
    """Audit keeps a hash of the arguments, never the values."""
    text = json.dumps(raw, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()


def _meta_str(meta: Any, key: str, limit: int = 64) -> str | None:
    value = meta.get(key) if isinstance(meta, dict) else None
    return value[:limit] if isinstance(value, str) and value else None


def _run_id(value: str | None) -> uuid.UUID | None:
    try:
        return uuid.UUID(value) if value else None
    except ValueError:
        return None


def _validation_reason(exc: ValidationError) -> str:
    """Field names and error types only; never the input values."""
    parts = [
        f"{'.'.join(str(p) for p in e['loc']) or '<args>'}:{e['type']}"
        for e in exc.errors(include_input=False, include_url=False)
    ]
    return "; ".join(parts)[:300]


@dataclass(frozen=True)
class CallContext:
    """Who is calling and for which run (S6): a tool reads it with `current_call()`.
    The run, ticket and store come from the request `_meta`, never from tool arguments."""

    client_id: str
    ticket_id: str | None
    run_id: uuid.UUID | None
    store_id: str | None = None


_CALL: ContextVar[CallContext | None] = ContextVar("mcp_call", default=None)


def current_call() -> CallContext:
    ctx = _CALL.get()
    if ctx is None:
        raise RuntimeError("current_call() outside a tool call")
    return ctx


class McpService:
    """One MCP server: `name` is its audience (`it-data`), `policy_prefix` its OPA
    action prefix (`it_data`)."""

    def __init__(
        self,
        *,
        name: str,
        policy_prefix: str,
        issuer: str,
        verifier: JwtVerifier,
        policy: Policy,
        pool: AsyncConnectionPool[AsyncConnection[Any]],
        audit: AuditSink | None = None,
        allowed_hosts: tuple[str, ...] = (),
        public_url: str = "http://localhost",
    ) -> None:
        self.name, self.policy_prefix = name, policy_prefix
        self.issuer, self.verifier, self.policy, self.pool = issuer, verifier, policy, pool
        self.audit: AuditSink = audit or self._db_audit
        self.allowed_hosts = ("127.0.0.1:*", "localhost:*", f"{name}:*", *allowed_hosts)
        self.public_url = public_url
        self.specs: dict[str, ToolSpec] = {}

    # ---- registration -------------------------------------------------------------

    def tool(self, *, scope: str, name: str | None = None) -> Callable[[ToolFn], ToolFn]:
        def register(fn: ToolFn) -> ToolFn:
            hints = get_type_hints(fn)
            params = list(inspect.signature(fn).parameters)
            in_model, out_model = hints[params[0]], hints["return"]
            if not (issubclass(in_model, BaseModel) and issubclass(out_model, BaseModel)):
                raise TypeError(f"{fn.__name__}: input and result must be Pydantic models")
            tool_name = name or fn.__name__
            if tool_name in self.specs:
                raise ValueError(f"duplicate tool {tool_name}")
            self.specs[tool_name] = ToolSpec(
                tool_name, scope, in_model, out_model, fn, inspect.getdoc(fn) or tool_name
            )
            return fn

        return register

    def _sdk_tool(self, spec: ToolSpec) -> Tool:
        async def handler(ctx: Context, **kwargs: Any) -> BaseModel:
            raw = {k: v for k, v in kwargs.items() if v is not None}
            return await self.call(spec, raw, ctx.request_context.meta)

        # Lenient SDK-side parameters (all optional, any type) so every call reaches
        # `call`; the published schema is the tool's own input model.
        fields = [
            inspect.Parameter(f, inspect.Parameter.KEYWORD_ONLY, default=None, annotation=Any)
            for f in spec.in_model.model_fields
        ]
        ctx_param = inspect.Parameter("ctx", inspect.Parameter.KEYWORD_ONLY, annotation=Context)
        handler.__signature__ = inspect.Signature(  # type: ignore[attr-defined]
            [ctx_param, *fields], return_annotation=spec.out_model
        )
        handler.__annotations__ = {
            "ctx": Context,
            **{f: Any for f in spec.in_model.model_fields},
            "return": spec.out_model,
        }
        tool = Tool.from_function(
            handler, name=spec.name, description=spec.description, structured_output=True
        )
        tool.parameters = spec.in_model.model_json_schema()
        return tool

    # ---- the call -----------------------------------------------------------------

    async def call(self, spec: ToolSpec, raw: dict[str, Any], meta: Any = None) -> BaseModel:
        started = time.monotonic()
        token = get_access_token()
        client_id = token.client_id if token else "unknown"
        fail: ToolFailure | None = None
        reset = _CALL.set(
            CallContext(
                client_id,
                _meta_str(meta, META_TICKET),
                _run_id(_meta_str(meta, META_RUN)),
                _meta_str(meta, META_STORE),
            )
        )
        try:
            result = await self._checked_call(spec, raw, token)
        except ToolFailure as exc:
            fail = exc
        except Exception as exc:
            _log.exception("mcp_tool_failed", server=self.name, tool=spec.name)
            fail = ToolFailure(ErrorCode.ERROR, type(exc).__name__)
        finally:
            _CALL.reset(reset)
        if fail is not None:
            await self._audit(spec, raw, meta, client_id, str(fail.code), fail.reason, started)
            raise ToolError(fail.as_json())
        status = str(getattr(result, "status", "ok"))
        await self._audit(spec, raw, meta, client_id, status, None, started)
        return result

    async def _checked_call(self, spec: ToolSpec, raw: dict[str, Any], token: Any) -> BaseModel:
        # 1 is done by the SDK hook; a call that got here without a token is refused.
        if token is None:
            raise ToolFailure(ErrorCode.DENIED, "no_token")
        # 2 scope, per tool
        if spec.scope not in token.scopes:
            raise ToolFailure(ErrorCode.DENIED, f"missing_scope:{spec.scope}")
        # 3 OPA (P7 via P10), fail closed
        claims = token.claims or {}
        decision = await self.policy.allow(
            {
                "action": f"{self.policy_prefix}.{spec.name}",
                "subject": {
                    "client_id": token.client_id,
                    "scopes": list(token.scopes),
                    "aud": list(claims.get("aud", [])),
                },
            }
        )
        if not decision.allowed:
            raise ToolFailure(ErrorCode.DENIED, f"opa:{decision.reason}")
        # 4 arguments
        try:
            args = spec.in_model.model_validate(raw)
        except ValidationError as exc:
            raise ToolFailure(ErrorCode.INVALID, _validation_reason(exc)) from None
        # the tool
        async with self.pool.connection() as conn:
            result = await spec.fn(args, conn)
        # 5 result
        try:
            return spec.out_model.model_validate(result.model_dump())
        except ValidationError as exc:
            raise ToolFailure(
                ErrorCode.ERROR, "result_invalid: " + _validation_reason(exc)
            ) from None

    # ---- audit --------------------------------------------------------------------

    async def _audit(
        self,
        spec: ToolSpec,
        raw: dict[str, Any],
        meta: Any,
        client_id: str,
        status: str,
        reason: str | None,
        started: float,
    ) -> None:
        event = AuditEvent(
            step=f"mcp.{self.policy_prefix}",
            actor=client_id,
            action=spec.name,
            result=status,
            reason=reason,
            source=self.name,
            ticket_id=_meta_str(meta, META_TICKET),
            run_id=_run_id(_meta_str(meta, META_RUN)),
            payload={
                "args_sha256": args_hash(raw),
                "latency_ms": round((time.monotonic() - started) * 1000, 1),
            },
        )
        try:
            await self.audit(event)
        except Exception:
            _log.exception("mcp_audit_failed", server=self.name, tool=spec.name)
            # D9: no audit, no reply.
            raise ToolError(ToolFailure(ErrorCode.ERROR, "audit_failed").as_json()) from None

    async def _db_audit(self, event: AuditEvent) -> None:
        async with self.pool.connection() as conn:
            await awrite_event(conn, event)

    async def _refused(self, status: int, reason: str, client_id: str | None) -> None:
        try:
            await self.audit(
                AuditEvent(
                    step=f"mcp.{self.policy_prefix}",
                    actor=client_id or "unknown",
                    action="auth",
                    result=str(ErrorCode.DENIED),
                    reason=reason,
                    source=self.name,
                    payload={"http_status": status},
                )
            )
        except Exception:
            # The call is already refused; a lost audit row is logged loudly.
            _log.exception("mcp_refusal_audit_failed", server=self.name, reason=reason)

    # ---- the ASGI app -------------------------------------------------------------

    def common_scopes(self) -> list[str]:
        scopes = [{s.scope} for s in self.specs.values()]
        return sorted(set.intersection(*scopes)) if scopes else []

    def build_server(self) -> MCPServer:
        auth = AuthSettings(
            issuer_url=self.issuer,
            resource_server_url=f"{self.public_url}{MCP_PATH}",
            # The verifier checks the audience itself (aud = this server's name).
            validate_token_resource=False,
            # Only scopes every tool needs; each tool's own scope is checked per call (step 2).
            # A server with an eval-only tool (knowledge, S6) must still admit agent-reader.
            required_scopes=self.common_scopes(),
        )
        return MCPServer(
            name=self.name,
            token_verifier=self.verifier,
            auth=auth,
            tools=[self._sdk_tool(s) for s in self.specs.values()],
        )

    def app(self) -> ASGIApp:
        server = self.build_server()
        mcp_app = server.streamable_http_app(
            streamable_http_path=MCP_PATH,
            stateless_http=True,
            json_response=True,
            transport_security=TransportSecuritySettings(
                enable_dns_rebinding_protection=True,
                allowed_hosts=list(self.allowed_hosts),
                allowed_origins=[],
            ),
        )
        pool = self.pool

        async def health(_: Request) -> JSONResponse:
            try:
                async with pool.connection() as conn:
                    await conn.execute("SELECT 1")
            except Exception:
                return JSONResponse({"status": "db_down"}, status_code=503)
            return JSONResponse({"status": "ok"})

        mcp_lifespan = mcp_app.router.lifespan_context

        @asynccontextmanager
        async def lifespan(app: Starlette) -> AsyncIterator[None]:
            await pool.open()
            try:
                async with mcp_lifespan(app):
                    yield
            finally:
                await pool.close()

        outer = Starlette(
            routes=[Route("/health", health)],
            lifespan=lifespan,
        )
        outer.mount("/", mcp_app)
        return RefusalAudit(outer, self._refused, path=MCP_PATH)
