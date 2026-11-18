"""CP2.3: Keycloak tokens per client, no password grant, OPA default deny, S3 scoping.

Every mock-user and service client gets a token by client credentials; its
roles, store_id, audience and scopes are checked against the JWKS-verified
token. A password grant to any realm client is refused (D52). OPA denies an
unlisted action (P10). S3 keys are scoped below the bucket (D49), and no
container is given another service's credentials (D46).
"""

from __future__ import annotations

import json
import subprocess
import uuid
from collections.abc import Iterator
from typing import Any

import boto3
import httpx
import jwt
import pytest
from botocore.client import BaseClient
from botocore.config import Config
from botocore.exceptions import ClientError

from support_agent.platform import realm
from support_agent.platform.mock_secrets import mock_client_secret
from tests.integration.platform_env import ROOT, load_env

pytestmark = pytest.mark.integration

ISSUER = "http://localhost:8080/realms/servewell"
TOKEN_URL = f"{ISSUER}/protocol/openid-connect/token"
STORES = realm.read_mock_stores(ROOT / "compose" / "keycloak" / "mock-stores.txt")
JWKS = jwt.PyJWKClient(f"{ISSUER}/protocol/openid-connect/certs")
SERVICE_VARS = {
    "agent-reader": "KEYCLOAK_SECRET_AGENT_READER",
    "agent-actor": "KEYCLOAK_SECRET_AGENT_ACTOR",
    "eval-runner": "KEYCLOAK_SECRET_EVAL_RUNNER",
}
EXPECTED_AUD = {
    "it-data:read": "it-data",
    "kb:read": "knowledge",
    "itsm:write": "itsm-actions",
    "itsm:run_fix": "itsm-actions",
    "api": "api",
    "eval:replay": "api",
}


def _secret(client_id: str) -> str:
    env = load_env()
    if client_id in SERVICE_VARS:
        return env[SERVICE_VARS[client_id]]
    return mock_client_secret(env["MOCK_CLIENT_SECRET_KEY"], client_id)


def _token(client_id: str, secret: str) -> dict[str, Any]:
    response = httpx.post(
        TOKEN_URL,
        data={"grant_type": "client_credentials"},
        auth=(client_id, secret),
        timeout=10,
    )
    assert response.status_code == 200, (client_id, response.text)
    access = response.json()["access_token"]
    key = JWKS.get_signing_key_from_jwt(access).key
    claims: dict[str, Any] = jwt.decode(
        access,
        key,
        algorithms=["RS256"],
        issuer=ISSUER,
        # The Colima VM clock can run a fraction of a second ahead of the Mac.
        leeway=30,
        options={"verify_aud": False},
    )
    return claims


def _aud(claims: dict[str, Any]) -> set[str]:
    aud = claims.get("aud", [])
    return {aud} if isinstance(aud, str) else set(aud)


@pytest.mark.parametrize("spec", realm.all_clients(STORES), ids=lambda s: s.client_id)
def test_each_client_gets_its_token(spec: realm.ClientSpec) -> None:
    claims = _token(spec.client_id, _secret(spec.client_id))

    assert claims["azp"] == spec.client_id
    roles = set(claims.get("realm_access", {}).get("roles", []))
    assert roles & set(realm.REALM_ROLES) == set(spec.roles)
    assert claims.get("store_id") == spec.store_id
    scopes = set(claims["scope"].split())
    custom = scopes & set(EXPECTED_AUD)
    assert custom == {s for s in spec.scopes if s in EXPECTED_AUD}
    assert _aud(claims) == {EXPECTED_AUD[s] for s in custom}


def test_wrong_secret_is_refused() -> None:
    response = httpx.post(
        TOKEN_URL, data={"grant_type": "client_credentials"}, auth=("mock-l2", "wrong"), timeout=10
    )
    assert response.status_code == 401


def _admin_token() -> str:
    response = httpx.post(
        "http://localhost:8080/realms/master/protocol/openid-connect/token",
        data={"grant_type": "client_credentials"},
        auth=("servewell-admin", load_env()["KEYCLOAK_ADMIN_CLIENT_SECRET"]),
        timeout=10,
    )
    assert response.status_code == 200, response.text
    token: str = response.json()["access_token"]
    return token


def _realm_clients() -> list[dict[str, Any]]:
    response = httpx.get(
        f"http://localhost:8080/admin/realms/{realm.REALM}/clients",
        params={"max": 1000},
        headers={"Authorization": f"Bearer {_admin_token()}"},
        timeout=10,
    )
    response.raise_for_status()
    clients: list[dict[str, Any]] = response.json()
    return clients


def test_no_realm_client_accepts_the_password_grant() -> None:
    clients = _realm_clients()
    # Built-in clients plus ours: ui, admin-cli, 3 services, 5 people, one per store.
    assert len(clients) >= 2 + 3 + 5 + len(STORES)
    for client in clients:
        client_id = client["clientId"]
        assert client.get("directAccessGrantsEnabled") is False, client_id
        auth = None if client.get("publicClient") else (client_id, _secret(client_id))
        data = {"grant_type": "password", "username": "nobody", "password": "x"}
        if auth is None:
            data["client_id"] = client_id
        response = httpx.post(TOKEN_URL, data=data, auth=auth, timeout=10)
        assert response.status_code in (400, 401), (client_id, response.text)
        assert response.json()["error"] in ("unauthorized_client", "invalid_client"), client_id


# --- OPA ---------------------------------------------------------------------


def _opa(action: str, subject: dict[str, Any]) -> dict[str, Any]:
    response = httpx.post(
        f"{load_env()['OPA_URL']}/v1/data/servewell/p10_default_deny",
        json={"input": {"action": action, "subject": subject}},
        timeout=5,
    )
    response.raise_for_status()
    result: dict[str, Any] = response.json()["result"]
    return result


def test_opa_denies_an_unlisted_action_and_allows_a_listed_one() -> None:
    claims = _token("agent-reader", _secret("agent-reader"))
    subject = {
        "client_id": claims["azp"],
        "scopes": claims["scope"].split(),
        "aud": sorted(_aud(claims)),
    }
    denied = _opa("itsm.delete_everything", subject)
    assert denied["allow"] is False
    assert denied["reason"] == "unknown action"
    allowed = _opa("it_data.get_asset", subject)
    assert allowed["allow"] is True
    assert _opa("itsm.update_ticket", subject)["allow"] is False


# --- S3 identities -----------------------------------------------------------


def _s3(identity: str) -> BaseClient:
    return boto3.client(
        "s3",
        endpoint_url=load_env()["S3_ENDPOINT_URL"],
        aws_access_key_id=load_env()[f"S3_ACCESS_KEY_{identity}"],
        aws_secret_access_key=load_env()[f"S3_SECRET_KEY_{identity}"],
        region_name="us-east-1",
        config=Config(s3={"addressing_style": "path"}, retries={"max_attempts": 1}),
    )


@pytest.fixture(scope="module")
def probes() -> Iterator[dict[str, str]]:
    tag = uuid.uuid4().hex[:8]
    keys = {
        "labels": f"raw/labels/cp23-{tag}.json",
        "kb": f"raw/kb/cp23-{tag}.md",
        "train": f"raw/tickets/train/cp23-{tag}.json",
    }
    ingest = _s3("INGEST")
    for key in keys.values():
        ingest.put_object(Bucket="servewell", Key=key, Body=b"{}")
    yield keys
    for key in [*keys.values(), f"raw/tickets/incoming/cp23-{tag}.json"]:
        ingest.delete_object(Bucket="servewell", Key=key)


def _status(call: Any) -> int:
    try:
        call()
    except ClientError as exc:
        return int(exc.response["ResponseMetadata"]["HTTPStatusCode"])
    return 200


def test_api_key_is_write_only_to_incoming(probes: dict[str, str]) -> None:
    api = _s3("API")
    for key in (probes["labels"], probes["kb"], probes["train"]):
        assert _status(lambda k=key: api.get_object(Bucket="servewell", Key=k)) == 403, key
    incoming = probes["labels"].replace("raw/labels/", "raw/tickets/incoming/")
    assert _status(lambda: api.put_object(Bucket="servewell", Key=incoming, Body=b"{}")) == 200
    assert _status(lambda: api.get_object(Bucket="servewell", Key=incoming)) == 403
    put_labels = _status(
        lambda: api.put_object(Bucket="servewell", Key="raw/labels/evil.json", Body=b"{}")
    )
    assert put_labels == 403


def test_kb_index_reads_kb_but_not_labels(probes: dict[str, str]) -> None:
    kb = _s3("KB_INDEX")
    assert _status(lambda: kb.get_object(Bucket="servewell", Key=probes["kb"])) == 200
    assert _status(lambda: kb.get_object(Bucket="servewell", Key=probes["labels"])) == 403
    write = _status(lambda: kb.put_object(Bucket="servewell", Key=probes["kb"], Body=b"x"))
    assert write == 403


def test_eval_reads_labels_and_train_but_not_kb(probes: dict[str, str]) -> None:
    ev = _s3("EVAL")
    assert _status(lambda: ev.get_object(Bucket="servewell", Key=probes["labels"])) == 200
    assert _status(lambda: ev.get_object(Bucket="servewell", Key=probes["train"])) == 200
    assert _status(lambda: ev.get_object(Bucket="servewell", Key=probes["kb"])) == 403


def test_langfuse_key_cannot_touch_servewell(probes: dict[str, str]) -> None:
    lf = _s3("LANGFUSE")
    assert _status(lambda: lf.get_object(Bucket="servewell", Key=probes["kb"])) == 403


# --- D46: each container gets only its own credentials -----------------------

# container -> .env variables whose values it may hold
ALLOWED: dict[str, set[str]] = {
    "postgres": {"POSTGRES_PASSWORD"},
    "seaweedfs": set(),
    "keycloak": {"KEYCLOAK_DB_PASSWORD", "KEYCLOAK_ADMIN_PASSWORD", "KEYCLOAK_ADMIN_CLIENT_SECRET"},
    "opa": set(),
    "valkey": {"VALKEY_PASSWORD"},
    "clickhouse": {"CLICKHOUSE_PASSWORD"},
    "litellm": {
        "LITELLM_MASTER_KEY",
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_SECRET_KEY",
        "OPENAI_API_KEY",
    },
    "prometheus": set(),
    "grafana": {"GRAFANA_ADMIN_PASSWORD"},
    # S5: its own read-only DB role only; no S3 key (D49), no Keycloak secret.
    "it-data": {"DATABASE_URL_IT_DATA"},
}
_LANGFUSE = {
    "LANGFUSE_DB_PASSWORD",
    "LANGFUSE_SALT",
    "LANGFUSE_ENCRYPTION_KEY",
    "CLICKHOUSE_PASSWORD",
    "VALKEY_PASSWORD",
    "S3_ACCESS_KEY_LANGFUSE",
    "S3_SECRET_KEY_LANGFUSE",
}
ALLOWED["langfuse-worker"] = _LANGFUSE
ALLOWED["langfuse-web"] = _LANGFUSE | {
    "LANGFUSE_NEXTAUTH_SECRET",
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
    "LANGFUSE_ADMIN_PASSWORD",
}


def test_no_container_holds_another_services_credentials() -> None:
    out = subprocess.run(
        [
            "docker",
            "compose",
            "--project-name",
            "servewell",
            "--env-file",
            str(ROOT / ".env"),
            "-f",
            str(ROOT / "compose" / "compose.yaml"),
            "--profile",
            "observability",
            "config",
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    services = json.loads(out)["services"]
    assert set(services) == set(ALLOWED)
    secret_names = ("PASSWORD", "SECRET", "KEY", "SALT", "DATABASE_URL")
    # Public values whose names merely contain "KEY" (KEYCLOAK_...).
    public = {"KEYCLOAK_ISSUER", "KEYCLOAK_JWKS_URL"}
    secrets = {
        k: v
        for k, v in load_env().items()
        if any(n in k for n in secret_names) and len(v) >= 16 and k not in public
    }
    for name, svc in services.items():
        blob = json.dumps(svc.get("environment", {})) + json.dumps(svc.get("command", ""))
        held = {k for k, v in secrets.items() if v in blob}
        assert held <= ALLOWED[name], (name, sorted(held - ALLOWED[name]))
