"""Bearer JWT checks for the API (S12 build step 2; D25).

PyJWT + JWKS (cached) check the signature, the issuer, `aud = api` and expiry. The
user context comes from the claims: `sub` (the user id), the realm roles,
`store_id`, the scopes, and for a store user the profile contact (`name`,
`phone_number`), which the API puts into a new ticket's vault row and nowhere else.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import anyio.to_thread
import jwt

ALGORITHMS = ["RS256"]
JWKS_CACHE_SECONDS = 300


class AuthError(Exception):
    """The request has no valid token (401). `reason` goes to the audit event."""

    def __init__(self, reason: str, client_id: str | None = None) -> None:
        super().__init__(reason)
        self.reason, self.client_id = reason, client_id


@dataclass(frozen=True)
class Subject:
    client_id: str
    user: str
    username: str | None
    roles: tuple[str, ...]
    store_id: str | None
    scopes: tuple[str, ...]
    aud: tuple[str, ...]
    # Profile contact (store users only). Never logged, never in a policy input.
    name: str | None = field(default=None, repr=False)
    phone: str | None = field(default=None, repr=False)

    def has(self, role: str) -> bool:
        return role in self.roles

    @property
    def is_replayer(self) -> bool:
        return self.client_id == "eval-runner" and "eval:replay" in self.scopes

    def policy(self) -> dict[str, Any]:
        """The subject as OPA sees it: ids, roles and scopes, no contact."""
        return {
            "client_id": self.client_id,
            "user": self.user,
            "roles": list(self.roles),
            "store_id": self.store_id,
            "scopes": list(self.scopes),
            "aud": list(self.aud),
        }


def _str(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def subject_from_claims(claims: dict[str, Any]) -> Subject:
    client_id = _str(claims.get("azp")) or _str(claims.get("client_id"))
    user = _str(claims.get("sub"))
    if not client_id or not user:
        raise AuthError("no_subject", client_id)
    realm = claims.get("realm_access")
    roles = realm.get("roles", []) if isinstance(realm, dict) else []
    aud = claims.get("aud")
    return Subject(
        client_id=client_id,
        user=user,
        username=_str(claims.get("preferred_username")),
        roles=tuple(r for r in roles if isinstance(r, str)),
        store_id=_str(claims.get("store_id")),
        scopes=tuple(str(claims.get("scope", "")).split()),
        aud=(aud,) if isinstance(aud, str) else tuple(a for a in aud or [] if isinstance(a, str)),
        name=_str(claims.get("name")),
        phone=_str(claims.get("phone_number")),
    )


KeyResolver = Callable[[str], Any]


class ApiVerifier:
    def __init__(
        self,
        *,
        issuer: str,
        audience: str = "api",
        jwks_url: str | None = None,
        key_resolver: KeyResolver | None = None,
    ) -> None:
        if key_resolver is None:
            if not jwks_url:
                raise ValueError("ApiVerifier needs a jwks_url or a key_resolver")
            client = jwt.PyJWKClient(jwks_url, cache_keys=True, lifespan=JWKS_CACHE_SECONDS)
            key_resolver = lambda token: client.get_signing_key_from_jwt(token).key  # noqa: E731
        self.issuer, self.audience, self._key = issuer, audience, key_resolver

    async def verify(self, authorization: str | None) -> Subject:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise AuthError("no_token")
        token = authorization[7:].strip()
        try:
            key = await anyio.to_thread.run_sync(self._key, token)
        except jwt.PyJWKClientConnectionError:
            raise AuthError("jwks_unavailable") from None
        except (jwt.PyJWKClientError, jwt.InvalidTokenError):
            raise AuthError("bad_signature_key") from None
        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                key,
                algorithms=ALGORITHMS,
                audience=self.audience,
                issuer=self.issuer,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except jwt.ExpiredSignatureError:
            raise AuthError("expired") from None
        except jwt.InvalidAudienceError:
            raise AuthError("wrong_audience") from None
        except jwt.InvalidIssuerError:
            raise AuthError("wrong_issuer") from None
        except jwt.InvalidTokenError:
            raise AuthError("invalid_token") from None
        return subject_from_claims(claims)
