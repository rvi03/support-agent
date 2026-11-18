"""Bearer-token checks for the MCP servers (S5 build step 1; D25).

`JwtVerifier` plugs into the SDK's resource-server hook (`TokenVerifier`). It
checks the signature against Keycloak's JWKS (cached), the issuer, the
audience (= this server's name) and expiry. A refused token returns None, so
the SDK answers 401; a missing scope is answered 403 by the SDK.

`RefusalAudit` sits in front of the whole app and writes one audit event for
every 401 or 403, with the reason the verifier noted, because the SDK refuses
those calls before any tool code runs (CP5.3).
"""

from __future__ import annotations

import contextvars
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import anyio.to_thread
import jwt
from mcp.server.auth.provider import AccessToken
from starlette.types import ASGIApp, Message, Receive, Scope, Send

ALGORITHMS = ["RS256"]
JWKS_CACHE_SECONDS = 300


@dataclass
class AuthNote:
    """What the verifier learned about this request, for the refusal audit."""

    reason: str | None = None
    client_id: str | None = None


_note: contextvars.ContextVar[AuthNote | None] = contextvars.ContextVar("auth_note", default=None)


def _set_reason(reason: str, client_id: str | None = None) -> None:
    note = _note.get()
    if note is not None:
        note.reason, note.client_id = reason, client_id


KeyResolver = Callable[[str], Any]


class JwtVerifier:
    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        jwks_url: str | None = None,
        key_resolver: KeyResolver | None = None,
    ) -> None:
        if key_resolver is None:
            if not jwks_url:
                raise ValueError("JwtVerifier needs a jwks_url or a key_resolver")
            client = jwt.PyJWKClient(jwks_url, cache_keys=True, lifespan=JWKS_CACHE_SECONDS)
            key_resolver = lambda token: client.get_signing_key_from_jwt(token).key  # noqa: E731
        self.issuer, self.audience, self._key = issuer, audience, key_resolver

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            key = await anyio.to_thread.run_sync(self._key, token)
        except jwt.PyJWKClientConnectionError:
            _set_reason("jwks_unavailable")
            return None
        except (jwt.PyJWKClientError, jwt.InvalidTokenError):
            _set_reason("bad_signature_key")
            return None
        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                key,
                algorithms=ALGORITHMS,
                audience=self.audience,
                issuer=self.issuer,
                options={"require": ["exp", "iat", "iss", "aud"]},
            )
        except jwt.ExpiredSignatureError:
            _set_reason("expired")
            return None
        except jwt.InvalidAudienceError:
            _set_reason("wrong_audience")
            return None
        except jwt.InvalidIssuerError:
            _set_reason("wrong_issuer")
            return None
        except jwt.InvalidTokenError:
            _set_reason("invalid_token")
            return None
        client_id = claims.get("azp") or claims.get("client_id")
        if not isinstance(client_id, str) or not client_id:
            _set_reason("no_client_id")
            return None
        aud = claims["aud"]
        _set_reason("verified", client_id)
        return AccessToken(
            token=token,
            client_id=client_id,
            scopes=str(claims.get("scope", "")).split(),
            expires_at=int(claims["exp"]),
            resource=self.audience,
            subject=claims.get("sub"),
            claims={"iss": claims["iss"], "aud": [aud] if isinstance(aud, str) else list(aud)},
        )


RefusalSink = Callable[[int, str, str | None], Awaitable[None]]
"""(http status, reason, client id or None) -> writes the audit event."""


class RefusalAudit:
    """Outermost ASGI middleware: audit every 401 and 403 on the MCP path."""

    def __init__(self, app: ASGIApp, sink: RefusalSink, path: str = "/mcp") -> None:
        self.app, self.sink, self.path = app, sink, path

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not str(scope.get("path", "")).startswith(self.path):
            await self.app(scope, receive, send)
            return
        note = AuthNote()
        token = _note.set(note)
        status: int | None = None

        async def watch(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, watch)
        finally:
            _note.reset(token)
        if status in (401, 403):
            await self.sink(status, _refusal_reason(status, note, scope), note.client_id)


def _refusal_reason(status: int, note: AuthNote, scope: Scope) -> str:
    if status == 403:
        return "insufficient_scope"
    if note.reason and note.reason != "verified":
        return note.reason
    headers = dict(scope.get("headers") or [])
    auth = headers.get(b"authorization", b"")
    return "no_token" if not auth.lower().startswith(b"bearer ") else "invalid_token"
