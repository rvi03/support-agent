"""S2 platform tooling: .env creation, realm, S3 identities, DB init, model slots."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from support_agent.platform import dbinit, envfile, models, realm, s3config
from support_agent.platform.mock_secrets import mock_client_secret

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / ".env.example"


@pytest.fixture
def env() -> dict[str, str]:
    return envfile.parse(envfile.fill_placeholders(EXAMPLE.read_text()))


# --- .env ------------------------------------------------------------------


def test_fill_replaces_every_placeholder_with_a_distinct_value() -> None:
    filled = envfile.fill_placeholders(EXAMPLE.read_text())
    assert envfile.PLACEHOLDER not in filled
    values = envfile.parse(filled)
    secrets = [v for v in values.values() if len(v) >= 32]
    assert len(secrets) == len(set(secrets)) > 20


def test_fill_keeps_prefixes_and_makes_hex_keys(env: dict[str, str]) -> None:
    assert env["LANGFUSE_PUBLIC_KEY"].startswith("pk-lf-")
    assert env["LANGFUSE_SECRET_KEY"].startswith("sk-lf-")
    assert env["LITELLM_MASTER_KEY"].startswith("sk-")
    assert re.fullmatch(r"[0-9a-f]{64}", env["LANGFUSE_ENCRYPTION_KEY"])


def test_init_env_never_overwrites(tmp_path: Path) -> None:
    target = tmp_path / ".env"
    assert envfile.init_env(EXAMPLE, target) is True
    first = target.read_text()
    assert envfile.init_env(EXAMPLE, target) is False
    assert target.read_text() == first
    assert target.stat().st_mode & 0o777 == 0o600


def test_require_rejects_placeholder_and_missing() -> None:
    with pytest.raises(envfile.EnvError, match="A, B"):
        envfile.require({"A": "x-change-me", "C": "ok"}, "A", "B", "C")


# --- Keycloak realm --------------------------------------------------------

STORES = ["SW-0001", "SW-0002"]
SERVICE_SECRETS = {"agent-reader": "r", "agent-actor": "a", "eval-runner": "e"}


@pytest.fixture
def built() -> dict[str, Any]:
    return realm.build_realm(STORES, SERVICE_SECRETS, "mock-key")


def _clients(built: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {c["clientId"]: c for c in built["clients"]}


def test_no_client_allows_the_password_grant(built: dict[str, Any]) -> None:
    clients = _clients(built)
    assert "admin-cli" in clients
    assert all(c["directAccessGrantsEnabled"] is False for c in clients.values())
    assert all(c.get("implicitFlowEnabled", False) is False for c in clients.values())


def test_ui_is_public_with_pkce(built: dict[str, Any]) -> None:
    ui = _clients(built)["ui"]
    assert ui["publicClient"] is True
    assert ui["attributes"]["pkce.code.challenge.method"] == "S256"
    assert ui["serviceAccountsEnabled"] is False


def test_service_clients_get_only_their_scopes(built: dict[str, Any]) -> None:
    clients = _clients(built)
    reader = set(clients["agent-reader"]["defaultClientScopes"])
    actor = set(clients["agent-actor"]["defaultClientScopes"])
    assert {"it-data:read", "kb:read"} <= reader
    assert not reader & {"itsm:write", "itsm:run_fix", "eval:replay", "api"}
    assert {"itsm:write", "itsm:run_fix"} <= actor
    assert not actor & {"it-data:read", "kb:read", "eval:replay"}
    for scope in ("eval:replay", "kb:eval"):
        holders = {cid for cid, c in clients.items() if scope in c["defaultClientScopes"]}
        assert holders == {"eval-runner"}, scope
    assert "kb:eval" not in reader


def test_mock_users_carry_roles_and_store(built: dict[str, Any]) -> None:
    users = {u["serviceAccountClientId"]: u for u in built["users"]}
    store = users["mock-store-sw-0002"]
    assert store["realmRoles"] == ["store_user"]
    assert store["attributes"] == {"store_id": ["SW-0002"]}
    assert set(users["mock-dual"]["realmRoles"]) == {"store_user", "l2_engineer"}
    assert users["mock-l2"]["realmRoles"] == ["l2_engineer"]
    assert users["agent-reader"]["realmRoles"] == []
    # One mock-store client per listed store, each with its own derived secret.
    clients = _clients(built)
    assert clients["mock-store-sw-0001"]["secret"] == mock_client_secret(
        "mock-key", "mock-store-sw-0001"
    )
    assert clients["mock-store-sw-0001"]["secret"] != clients["mock-store-sw-0002"]["secret"]


def test_scopes_add_their_audience(built: dict[str, Any]) -> None:
    scopes = {s["name"]: s for s in built["clientScopes"]}
    expected = {
        "it-data:read": "it-data",
        "kb:read": "knowledge",
        "itsm:write": "itsm-actions",
        "itsm:run_fix": "itsm-actions",
        "api": "api",
        "eval:replay": "api",
        "kb:eval": "knowledge",
    }
    for scope, aud in expected.items():
        (mapper,) = scopes[scope]["protocolMappers"]
        assert mapper["config"]["included.custom.audience"] == aud


def test_realm_needs_every_service_secret() -> None:
    with pytest.raises(ValueError, match="eval-runner"):
        realm.build_realm(STORES, {"agent-reader": "r", "agent-actor": "a"}, "k")


def test_mock_store_list_is_valid() -> None:
    ids = realm.read_mock_stores(ROOT / "compose" / "keycloak" / "mock-stores.txt")
    assert len(ids) == 108
    assert ids == sorted(ids)


def test_mock_store_list_rejects_bad_ids(tmp_path: Path) -> None:
    path = tmp_path / "stores.txt"
    path.write_text("SW-0001\nnot-a-store\n")
    with pytest.raises(ValueError, match="not-a-store"):
        realm.read_mock_stores(path)
    path.write_text("SW-0001\nSW-0001\n")
    with pytest.raises(ValueError, match="Duplicate"):
        realm.read_mock_stores(path)


def test_stores_with_tickets_reads_ticket_files(tmp_path: Path) -> None:
    train = tmp_path / "tickets" / "train"
    train.mkdir(parents=True)
    for i, store in enumerate(["SW-0002", "SW-0001", "SW-0002"]):
        (train / f"INC-{i}.json").write_text(json.dumps({"store_id": store}))
    out = tmp_path / "mock-stores.txt"
    assert realm.write_mock_stores(tmp_path, out) == 2
    assert realm.read_mock_stores(out) == ["SW-0001", "SW-0002"]


def test_mock_secret_needs_a_key() -> None:
    with pytest.raises(ValueError):
        mock_client_secret("", "mock-l2")


# --- S3 identities ---------------------------------------------------------


def test_s3_identities_are_least_privilege(env: dict[str, str]) -> None:
    ids = {i["name"]: i for i in s3config.build_s3_config(env)["identities"]}
    assert set(ids) == {"ingest", "kb-index", "api", "eval", "langfuse"}
    assert ids["api"]["actions"] == ["Write:servewell/raw/tickets/incoming/*"]
    assert not any("labels" in a for a in ids["kb-index"]["actions"])
    assert all(a.endswith(":langfuse") for a in ids["langfuse"]["actions"])
    assert not any("Admin" in a for i in ids.values() for a in i["actions"])
    keys = [c["accessKey"] for i in ids.values() for c in i["credentials"]]
    assert len(keys) == len(set(keys))


# --- DB init ---------------------------------------------------------------


def test_role_passwords_come_from_each_service_url(env: dict[str, str]) -> None:
    passwords = dbinit.role_passwords(env)
    assert set(passwords) == set(dbinit.URL_ROLES) | set(dbinit.PASSWORD_ROLES)
    assert passwords["agent_actor"] in env["DATABASE_URL_AGENT"]


def test_role_passwords_reject_a_url_with_the_wrong_role(env: dict[str, str]) -> None:
    env["DATABASE_URL_AGENT"] = "postgresql://postgres:pw@localhost:5432/servewell"
    with pytest.raises(envfile.EnvError, match="agent_actor"):
        dbinit.role_passwords(env)


def test_psql_script_quotes_passwords(tmp_path: Path) -> None:
    sql = tmp_path / "001_x.sql"
    sql.write_text("SELECT 1;")
    script = dbinit.psql_script(sql, {"a": "it's\\x"})
    assert script.splitlines()[0] == "\\set pw_a 'it''s\\\\x'"
    assert script.endswith("SELECT 1;")


def test_sql_files_run_in_order_on_the_right_database() -> None:
    files = dbinit.sql_files(ROOT / "db" / "sql")
    assert [f.name[:3] for _, f in files] == sorted(f.name[:3] for _, f in files)
    assert files[0][0] == "postgres"
    assert {db for db, _ in files[1:]} == {"servewell"}


def test_sql_files_missing_dir(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        dbinit.sql_files(tmp_path)


# --- Model slots and the Ollama lock ---------------------------------------

CONFIG = ROOT / "compose" / "litellm" / "config.yaml"


def test_config_maps_every_alias_to_its_openai_model() -> None:
    aliases = models.load_aliases(CONFIG)
    assert aliases == {
        "agent": "openai/gpt-6-luna",
        "embed": "openai/text-embedding-3-small",
        "moderation": "openai/gpt-6-luna",
        "judge": "openai/gpt-6-luna",
        "simulator": "openai/gpt-6-luna",
        "agent-terra": "openai/gpt-6.1-terra",  # CP8.4 comparison alias only
    }
    assert models.ollama_models(aliases) == []
    models.check_external(aliases, allow_external=True, openai_key="sk-test")


def test_embed_alias_keeps_embed_dim() -> None:
    import yaml

    config = yaml.safe_load(CONFIG.read_text())
    embed = next(m for m in config["model_list"] if m["model_name"] == "embed")
    assert embed["litellm_params"]["dimensions"] == 768


def test_openai_alias_needs_a_key() -> None:
    aliases = {"agent": "openai/gpt-6-luna"}
    with pytest.raises(models.ModelError, match="OPENAI_API_KEY"):
        models.check_external(aliases, allow_external=True, openai_key=" ")


def test_ollama_fallback_tags() -> None:
    aliases = {"agent": "ollama_chat/qwen3:8b", "embed": "ollama/nomic-embed-text"}
    models.check_external(aliases, allow_external=False)
    assert models.ollama_models(aliases) == ["nomic-embed-text:latest", "qwen3:8b"]


def test_external_model_refused_unless_allowed() -> None:
    aliases = {"agent": "anthropic/claude-x", "embed": "ollama/nomic-embed-text"}
    with pytest.raises(models.ModelError, match="agent=anthropic/claude-x"):
        models.check_external(aliases, allow_external=False)
    models.check_external(aliases, allow_external=True)


def test_missing_alias_refused(tmp_path: Path) -> None:
    cfg = tmp_path / "c.yaml"
    cfg.write_text("model_list:\n  - model_name: agent\n    litellm_params: {model: ollama/x}\n")
    with pytest.raises(models.ModelError, match="embed"):
        models.load_aliases(cfg)


class FakeOllama:
    def __init__(self, local: dict[str, str], registry: dict[str, str]) -> None:
        self.local = dict(local)
        self.registry = registry
        self.pulled: list[str] = []

    def __call__(self, method: str, url: str, body: dict[str, Any] | None) -> dict[str, Any]:
        if url.endswith("/api/tags"):
            return {"models": [{"name": n, "digest": d} for n, d in self.local.items()]}
        assert body is not None
        self.pulled.append(body["model"])
        self.local[body["model"]] = self.registry[body["model"]]
        return {"status": "success"}


def test_first_run_pulls_missing_and_writes_lock(tmp_path: Path) -> None:
    lock = tmp_path / "lock"
    fake = FakeOllama({"a:1": "d1"}, {"b:2": "d2"})
    pinned = models.ensure_models(["a:1", "b:2"], lock, "http://x", fake, log=lambda _: None)
    assert fake.pulled == ["b:2"]
    assert pinned == {"a:1": "d1", "b:2": "d2"}
    assert models.read_lock(lock) == pinned


def test_digest_drift_fails(tmp_path: Path) -> None:
    lock = tmp_path / "lock"
    models.write_lock(lock, {"a:1": "d1"})
    fake = FakeOllama({"a:1": "other"}, {})
    with pytest.raises(models.ModelError, match="drift"):
        models.ensure_models(["a:1"], lock, "http://x", fake, log=lambda _: None)


def test_stale_lock_entry_fails(tmp_path: Path) -> None:
    lock = tmp_path / "lock"
    models.write_lock(lock, {"a:1": "d1", "old:1": "d0"})
    fake = FakeOllama({"a:1": "d1"}, {})
    with pytest.raises(models.ModelError, match="old:1"):
        models.ensure_models(["a:1"], lock, "http://x", fake, log=lambda _: None)


def test_ollama_down_names_the_fix() -> None:
    def down(method: str, url: str, body: dict[str, Any] | None) -> dict[str, Any]:
        raise OSError("connection refused")

    with pytest.raises(models.ModelError, match="brew services start ollama"):
        models.local_digests("http://x", down)
