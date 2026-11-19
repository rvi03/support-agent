"""The FastAPI service (S12 build step 1; D30). `python -m support_agent.api`.

The lifespan loads the three settings classes this process needs (ApiSettings,
IntakeSettings, AgentSettings: the API hosts intake and the graph), opens the DB
pools, builds intake (masker, safety net, moderation) and the agent (MCP clients,
checkpointer, lock), and starts the SLA timer. Port 8000; `/metrics` is a separate
internal Prometheus exporter on port 9000, outside the API contract (D30).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import Counter
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from support_agent.api.routes import ApiDeps, deny, router
from support_agent.api.service import ApiError
from support_agent.common.logging import get_logger
from support_agent.platform.realm import UI_ORIGIN

log = get_logger(__name__)

REQUESTS = Counter("api_requests_total", "API responses by route and status", ["route", "status"])


# ---- body size cap (S12 build step 5) --------------------------------------------------


class BodyTooLarge(Exception):  # noqa: N818
    pass


class BodyLimit:
    """Refuse a body over `max_bytes` (Content-Length or counted while streaming)."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        length = headers.get(b"content-length")
        if length is not None and length.isdigit() and int(length) > self.max_bytes:
            await self._refuse(scope, send)
            return
        seen = 0

        async def counted() -> Message:
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > self.max_bytes:
                    raise BodyTooLarge
            return message

        try:
            await self.app(scope, counted, send)
        except BodyTooLarge:
            await self._refuse(scope, send)

    async def _refuse(self, scope: Scope, send: Send) -> None:
        app = scope.get("app")
        d = getattr(getattr(app, "state", None), "deps", None)
        if d is not None:
            await d.audit_refusal(413, "body_too_large", str(scope.get("path")))
        body = b'{"error":"body_too_large","status":413}'
        await send({"type": "http.response.start", "status": 413,
                    "headers": [(b"content-type", b"application/json"),
                                (b"content-length", str(len(body)).encode())]})  # fmt: skip
        await send({"type": "http.response.body", "body": body})


# ---- app -------------------------------------------------------------------------------


@dataclass
class Running:
    """What the lifespan started, to stop it again."""

    close: Callable[[], Awaitable[None]]


def _action(request: Request) -> str:
    route = request.scope.get("route")
    name = getattr(route, "name", None) or request.url.path
    return f"api.{name}"


def create_app(
    deps: ApiDeps | None = None,
    *,
    builder: Callable[[], Awaitable[tuple[ApiDeps, Running]]] | None = None,
    max_body_bytes: int = 64_000,
    cors_origins: tuple[str, ...] = (UI_ORIGIN,),
) -> FastAPI:
    """`deps` for tests; otherwise `builder` (default: from the environment) runs in
    the lifespan."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        running: Running | None = None
        if app.state.deps is None:
            build = builder or build_from_env
            app.state.deps, running = await build()
        try:
            yield
        finally:
            d: ApiDeps = app.state.deps
            await d.service.drain(timeout=10)
            if running:
                await running.close()

    app = FastAPI(
        title="ServeWell support agent API",
        version="1.0.0",
        lifespan=lifespan,
        description="Tickets only (D29): create, list, get, reply, approve, health.",
    )
    app.state.deps = deps
    app.include_router(router)

    @app.exception_handler(ApiError)
    async def on_api_error(request: Request, exc: ApiError) -> JSONResponse:
        REQUESTS.labels(_action(request), str(exc.status)).inc()
        extra = {"rule": exc.rule} if exc.status == 401 else None
        return await deny(
            request.app.state.deps, exc.status, exc.reason, action=_action(request),
            subject=getattr(request.state, "subject", None), resource=exc.resource,
            rule=exc.rule, extra=extra,
        )  # fmt: skip

    @app.exception_handler(RequestValidationError)
    async def on_invalid(request: Request, exc: RequestValidationError) -> JSONResponse:
        REQUESTS.labels(_action(request), "422").inc()
        # Field names and error types only: never the values (they may hold contact text).
        fields = sorted({".".join(str(p) for p in e.get("loc", ())[1:]) or "body"
                         for e in exc.errors()})  # fmt: skip
        return await deny(
            request.app.state.deps, 422, "invalid_body", action=_action(request),
            subject=getattr(request.state, "subject", None),
            extra={"fields": fields, "types": sorted({str(e.get("type")) for e in exc.errors()})},
        )  # fmt: skip

    @app.middleware("http")
    async def count(request: Request, call_next: Any) -> Any:
        response = await call_next(request)
        if response.status_code < 400:
            REQUESTS.labels(_action(request), str(response.status_code)).inc()
        return response

    app.add_middleware(BodyLimit, max_bytes=max_body_bytes)
    # The Demo UI (S13) calls the API from its own origin with a bearer token, so CORS
    # allows that one origin, no cookies. Added last, so it is the outermost layer and
    # answers preflights before the body cap or the token check.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
        max_age=600,
    )
    return app


# ---- building from the environment -----------------------------------------------------


async def build_from_env() -> tuple[ApiDeps, Running]:
    import boto3
    import psycopg
    from prometheus_client import start_http_server

    from support_agent.agent.app import build_agent
    from support_agent.agent.sla_timer import SlaTimer, schedule
    from support_agent.api.auth import ApiVerifier
    from support_agent.api.limits import RateLimits
    from support_agent.api.service import TicketService
    from support_agent.api.store import ApiStore
    from support_agent.common.audit import AuditEvent, awrite_event, write_event
    from support_agent.common.config import (
        AgentSettings,
        ApiSettings,
        IntakeSettings,
        get_settings,
    )
    from support_agent.common.db import dsn
    from support_agent.intake.masker import Masker
    from support_agent.intake.moderation import (
        ModerationBudget,
        ModerationClient,
        Moderator,
    )
    from support_agent.intake.pipeline import IntakeResult, process_ticket
    from support_agent.intake.reference import load_reference
    from support_agent.intake.safety_net import SafetyNet
    from support_agent.mcp.base.opa import OpaClient

    api_s = get_settings(ApiSettings)
    intake_s = get_settings(IntakeSettings)
    agent_s = get_settings(AgentSettings)
    api_dsn = dsn(api_s.database_url_api, api_s.db_host)
    intake_dsn = dsn(intake_s.database_url_intake, intake_s.db_host)

    store = ApiStore(api_dsn, intake_dsn)
    await store.open()
    audit_conn = await psycopg.AsyncConnection.connect(api_dsn, autocommit=True)
    audit_lock = asyncio.Lock()

    async def audit(event: AuditEvent) -> int:
        async with audit_lock:
            return await awrite_event(audit_conn, event)

    # Intake, built once (the masker loads spaCy): as intake_rw, like `make ticket-local`.
    intake_conn = psycopg.connect(intake_dsn, autocommit=True)
    reference = load_reference(intake_conn)

    def intake_audit(event: AuditEvent) -> int:
        return write_event(intake_conn, event)

    masker = Masker(reference)
    # Load spaCy and Presidio once before serving: `analyzer()` is cached but not
    # guarded, and two tickets at once loaded the 600 MB model twice (S12).
    from support_agent.intake.masker import analyzer

    await asyncio.to_thread(analyzer)
    net = SafetyNet(reference, intake_audit, actor="intake")
    moderator = Moderator(
        ModerationClient(intake_s.litellm_base_url, intake_s.litellm_master_key.get_secret_value(),
                         model=intake_s.model_moderation),
        net, intake_audit,
    )  # fmt: skip

    async def intake(raw: dict[str, Any]) -> IntakeResult:
        return await asyncio.to_thread(
            process_ticket, raw, masker, safety_net=net, moderator=moderator,
            budget=ModerationBudget(intake_s.moderation_max_calls),
        )  # fmt: skip

    s3 = boto3.client(
        "s3",
        endpoint_url=api_s.s3_endpoint_url,
        aws_access_key_id=api_s.s3_access_key_api.get_secret_value(),
        aws_secret_access_key=api_s.s3_secret_key_api.get_secret_value(),
        region_name="us-east-1",
    )

    class S3Raw:
        async def put(self, key: str, body: bytes) -> None:
            await asyncio.to_thread(
                s3.put_object, Bucket=api_s.s3_bucket, Key=key, Body=body,
                ContentType="application/json",
            )  # fmt: skip

    agent = await build_agent(agent_s)
    service = TicketService(store=store, raw=S3Raw(), agent=agent, intake=intake)
    opa = OpaClient(api_s.opa_url)
    d = ApiDeps(
        verifier=ApiVerifier(
            issuer=api_s.keycloak_issuer, audience=api_s.api_audience, jwks_url=api_s.jwks_url
        ),  # fmt: skip
        policy=opa,
        limits=RateLimits(
            api_s.api_rate_write_user,
            api_s.api_rate_write_store,
            api_s.api_rate_read_user,
            api_s.api_rate_replay,
        ),  # fmt: skip
        store=store,
        service=service,
        audit=audit,
    )
    scheduler = None
    if api_s.api_sla_timer:
        timer = SlaTimer(agent.app, agent.deps, agent.locker,
                         dsn(agent_s.database_url_agent, agent_s.db_host))  # fmt: skip
        scheduler = schedule(timer, agent_s.sla_timer_interval_s)
    start_http_server(api_s.api_metrics_port, addr=api_s.api_host)

    async def close() -> None:
        if scheduler is not None:
            scheduler.shutdown(wait=False)
        await agent.aclose()
        await opa.aclose()
        await store.close()
        await audit_conn.close()
        intake_conn.close()

    return d, Running(close)


def main() -> int:
    import uvicorn

    from support_agent.common.config import ApiSettings, get_settings
    from support_agent.common.logging import configure_logging

    s = get_settings(ApiSettings)
    configure_logging("api", s.log_dir)
    app = create_app(max_body_bytes=s.api_max_body_bytes)
    uvicorn.run(app, host=s.api_host, port=s.api_port, log_config=None, access_log=False)
    return 0
