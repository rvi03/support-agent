"""Build the Keycloak realm `servewell` (D25, D52; S2 build step 5).

The realm is built in code and rendered with secrets into `.run/keycloak/`,
which Keycloak imports at first start. Rules this file enforces:

- No password grant anywhere: every client has `directAccessGrantsEnabled`
  false, including the built-in `admin-cli` (D52; RFC 9700 section 2.4).
- People use the public `ui` client with PKCE (S256).
- Services and scripted mock users are confidential clients using client
  credentials. A mock user's service-account user carries that person's realm
  roles and `store_id`, so the API and OPA see a token shaped like the person's.
- Scopes add their audience: `it-data:read` -> it-data, `kb:read` -> knowledge,
  `itsm:write` and `itsm:run_fix` -> itsm-actions, `api` and `eval:replay` -> api.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from support_agent.platform.mock_secrets import mock_client_secret

REALM = "servewell"
REALM_ROLES = ("store_user", "l1_agent", "l2_engineer", "vendor_approver", "admin")
_STORE_ID = re.compile(r"^SW-\d{4}$")

Json = dict[str, Any]


@dataclass(frozen=True)
class ClientSpec:
    client_id: str
    scopes: tuple[str, ...]
    roles: tuple[str, ...] = ()
    store_id: str | None = None


def read_mock_stores(path: Path) -> list[str]:
    ids = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    bad = [i for i in ids if not _STORE_ID.match(i)]
    if bad:
        raise ValueError(f"Bad store ids in {path}: {bad}")
    if len(set(ids)) != len(ids):
        raise ValueError(f"Duplicate store ids in {path}")
    return ids


def stores_with_tickets(dataset_dir: Path) -> list[str]:
    """Store ids that have at least one ticket in `tickets/train/*.json`."""
    ids = {
        json.loads(p.read_text(encoding="utf-8"))["store_id"]
        for p in (dataset_dir / "tickets" / "train").glob("*.json")
    }
    return sorted(ids)


def write_mock_stores(dataset_dir: Path, path: Path) -> int:
    ids = stores_with_tickets(dataset_dir)
    header = (
        "# Pilot stores with at least one dataset ticket: one mock-store client each (D52).\n"
        "# Regenerate with: make mock-stores DATASET_DIR=<dataset>\n"
    )
    path.write_text(header + "\n".join(ids) + "\n", encoding="utf-8")
    return len(ids)


def mock_store_client_id(store_id: str) -> str:
    return f"mock-store-{store_id.lower()}"


def service_clients() -> list[ClientSpec]:
    return [
        ClientSpec("agent-reader", ("it-data:read", "kb:read")),
        ClientSpec("agent-actor", ("itsm:write", "itsm:run_fix")),
        ClientSpec("eval-runner", ("api", "eval:replay")),
    ]


def mock_user_clients(store_ids: list[str]) -> list[ClientSpec]:
    people = [
        ClientSpec("mock-l1", ("api",), roles=("l1_agent",)),
        ClientSpec("mock-l2", ("api",), roles=("l2_engineer",)),
        ClientSpec("mock-vendor", ("api",), roles=("vendor_approver",)),
        ClientSpec("mock-admin", ("api",), roles=("admin",)),
        # Holds both roles for the self-approval negative test (P3).
        ClientSpec(
            "mock-dual",
            ("api", "store"),
            roles=("store_user", "l2_engineer"),
            store_id=store_ids[0],
        ),
    ]
    stores = [
        ClientSpec(mock_store_client_id(s), ("api", "store"), roles=("store_user",), store_id=s)
        for s in store_ids
    ]
    return people + stores


def _mapper(name: str, mapper: str, config: dict[str, str]) -> Json:
    return {
        "name": name,
        "protocol": "openid-connect",
        "protocolMapper": mapper,
        "consentRequired": False,
        "config": config,
    }


def _audience(aud: str) -> Json:
    return _mapper(
        f"aud-{aud}",
        "oidc-audience-mapper",
        {
            "included.custom.audience": aud,
            "access.token.claim": "true",
            "id.token.claim": "false",
            "introspection.token.claim": "true",
        },
    )


def _scope(name: str, mappers: list[Json], in_scope_claim: bool = True) -> Json:
    return {
        "name": name,
        "protocol": "openid-connect",
        "attributes": {
            "include.in.token.scope": "true" if in_scope_claim else "false",
            "display.on.consent.screen": "false",
        },
        "protocolMappers": mappers,
    }


def client_scopes() -> list[Json]:
    token_claim = {
        "access.token.claim": "true",
        "id.token.claim": "true",
        "introspection.token.claim": "true",
        "userinfo.token.claim": "true",
    }
    return [
        _scope("basic", [_mapper("sub", "oidc-sub-mapper", token_claim)], in_scope_claim=False),
        _scope(
            "profile",
            [
                _mapper(
                    "username",
                    "oidc-usermodel-attribute-mapper",
                    {
                        **token_claim,
                        "user.attribute": "username",
                        "claim.name": "preferred_username",
                        "jsonType.label": "String",
                    },
                )
            ],
            in_scope_claim=False,
        ),
        _scope(
            "roles",
            [
                _mapper(
                    "realm roles",
                    "oidc-usermodel-realm-role-mapper",
                    {
                        "access.token.claim": "true",
                        "introspection.token.claim": "true",
                        "claim.name": "realm_access.roles",
                        "jsonType.label": "String",
                        "multivalued": "true",
                    },
                )
            ],
            in_scope_claim=False,
        ),
        _scope(
            "store",
            [
                _mapper(
                    "store_id",
                    "oidc-usermodel-attribute-mapper",
                    {
                        **token_claim,
                        "user.attribute": "store_id",
                        "claim.name": "store_id",
                        "jsonType.label": "String",
                    },
                )
            ],
            in_scope_claim=False,
        ),
        _scope("api", [_audience("api")]),
        _scope("it-data:read", [_audience("it-data")]),
        _scope("kb:read", [_audience("knowledge")]),
        _scope("itsm:write", [_audience("itsm-actions")]),
        _scope("itsm:run_fix", [_audience("itsm-actions")]),
        _scope("eval:replay", [_audience("api")]),
    ]


_BASE_SCOPES = ["basic", "profile", "roles"]


def _confidential(spec: ClientSpec, secret: str) -> Json:
    return {
        "clientId": spec.client_id,
        "enabled": True,
        "protocol": "openid-connect",
        "publicClient": False,
        "clientAuthenticatorType": "client-secret",
        "secret": secret,
        "serviceAccountsEnabled": True,
        "standardFlowEnabled": False,
        "implicitFlowEnabled": False,
        "directAccessGrantsEnabled": False,
        "frontchannelLogout": False,
        "fullScopeAllowed": True,
        "attributes": {"oauth2.device.authorization.grant.enabled": "false"},
        "defaultClientScopes": _BASE_SCOPES + list(spec.scopes),
        "optionalClientScopes": [],
    }


def _ui_client() -> Json:
    return {
        "clientId": "ui",
        "enabled": True,
        "protocol": "openid-connect",
        "publicClient": True,
        "standardFlowEnabled": True,
        "implicitFlowEnabled": False,
        "directAccessGrantsEnabled": False,
        "serviceAccountsEnabled": False,
        # S13 sets the real UI origin.
        "redirectUris": ["http://localhost:8000/*"],
        "webOrigins": ["http://localhost:8000"],
        "attributes": {
            "pkce.code.challenge.method": "S256",
            "oauth2.device.authorization.grant.enabled": "false",
            "post.logout.redirect.uris": "http://localhost:8000/*",
        },
        "defaultClientScopes": [*_BASE_SCOPES, "api", "store"],
        "optionalClientScopes": [],
    }


def _admin_cli() -> Json:
    # Built-in client, overridden so the password grant is off here too.
    return {
        "clientId": "admin-cli",
        "enabled": True,
        "publicClient": True,
        "standardFlowEnabled": False,
        "implicitFlowEnabled": False,
        "directAccessGrantsEnabled": False,
        "serviceAccountsEnabled": False,
        "defaultClientScopes": _BASE_SCOPES,
    }


def _service_account_user(spec: ClientSpec) -> Json:
    user: Json = {
        "username": f"service-account-{spec.client_id}",
        "enabled": True,
        "serviceAccountClientId": spec.client_id,
        "realmRoles": list(spec.roles),
    }
    if spec.store_id:
        user["attributes"] = {"store_id": [spec.store_id]}
    return user


def _user_profile() -> Json:
    admin_only = {"view": ["admin"], "edit": ["admin"]}
    config = {
        "unmanagedAttributePolicy": "ADMIN_VIEW",
        "attributes": [
            {
                "name": "username",
                "displayName": "${username}",
                "validations": {"length": {"min": 3, "max": 255}},
                "permissions": {"view": ["admin", "user"], "edit": ["admin"]},
                "multivalued": False,
            },
            {
                "name": "email",
                "displayName": "${email}",
                "validations": {"email": {}, "length": {"max": 255}},
                "permissions": {"view": ["admin", "user"], "edit": ["admin"]},
                "multivalued": False,
            },
            {
                "name": "store_id",
                "displayName": "Store",
                "validations": {"pattern": {"pattern": _STORE_ID.pattern}},
                "permissions": admin_only,
                "multivalued": False,
            },
        ],
        "groups": [],
    }
    return {
        "org.keycloak.userprofile.UserProfileProvider": [
            {
                "providerId": "declarative-user-profile",
                "subComponents": {},
                "config": {"kc.user.profile.config": [json.dumps(config)]},
            }
        ]
    }


def build_realm(
    store_ids: list[str],
    service_secrets: dict[str, str],
    mock_key: str,
) -> Json:
    services = service_clients()
    missing = [s.client_id for s in services if not service_secrets.get(s.client_id)]
    if missing:
        raise ValueError(f"No secret for service client(s): {missing}")
    mocks = mock_user_clients(store_ids)
    clients = [_ui_client(), _admin_cli()]
    clients += [_confidential(s, service_secrets[s.client_id]) for s in services]
    clients += [_confidential(m, mock_client_secret(mock_key, m.client_id)) for m in mocks]
    return {
        "realm": REALM,
        "enabled": True,
        "sslRequired": "external",
        "registrationAllowed": False,
        "loginWithEmailAllowed": False,
        "duplicateEmailsAllowed": False,
        "bruteForceProtected": True,
        "accessTokenLifespan": 300,
        "revokeRefreshToken": True,
        "roles": {"realm": [{"name": r} for r in REALM_ROLES]},
        "clientScopes": client_scopes(),
        "defaultDefaultClientScopes": _BASE_SCOPES,
        "defaultOptionalClientScopes": [],
        "clients": clients,
        "users": [_service_account_user(c) for c in services + mocks],
        "components": _user_profile(),
    }


def all_clients(store_ids: list[str]) -> list[ClientSpec]:
    """Every confidential client, for tests and the CLI."""
    return service_clients() + mock_user_clients(store_ids)
