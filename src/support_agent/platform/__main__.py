"""`python -m support_agent.platform <command>`: the steps behind `make up / status`.

Commands (run from the repo root):
  env           create .env from .env.example with fresh secrets, if missing
  colima-check  Colima is running with COLIMA_MEMORY GB, else print the fix
  model-check   every LiteLLM alias points at Ollama unless ALLOW_EXTERNAL_MODELS=true
  render        write .run/keycloak/realm-servewell.json and .run/seaweedfs/s3.json
  db-init       apply db/sql/*.sql in order (idempotent)
  buckets       create the S3 buckets if missing
  models        Ollama is up; pull missing models; check digests against the lock
  status        health of every container, model digests, Keycloak and OPA ping
  mock-stores   regenerate compose/keycloak/mock-stores.txt (needs DATASET_DIR)
  realm-reload  re-render the realm, delete it in Keycloak and restart Keycloak so it
                imports the new one (Keycloak skips an import when the realm exists)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path

from support_agent.platform import dbinit, envfile, models, realm, s3config

ROOT = Path.cwd()
ENV_FILE = ROOT / ".env"
RUN_DIR = ROOT / ".run"
LITELLM_CONFIG = ROOT / "compose" / "litellm" / "config.yaml"
MODEL_LOCK = ROOT / "compose" / "ollama-models.lock"
MOCK_STORES = ROOT / "compose" / "keycloak" / "mock-stores.txt"
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
COMPOSE = [
    "docker",
    "compose",
    "--project-name",
    "servewell",
    "--env-file",
    str(ENV_FILE),
    "-f",
    str(ROOT / "compose" / "compose.yaml"),
]


class PlatformError(RuntimeError):
    pass


def _env() -> dict[str, str]:
    if not ENV_FILE.exists():
        raise PlatformError("No .env; run `make up` (or `make env`) to create it")
    return envfile.load(ENV_FILE)


def _write_private(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    # Containers read these through a bind mount as their own user.
    path.chmod(0o644)


def cmd_env() -> None:
    if envfile.init_env(ROOT / ".env.example", ENV_FILE):
        print("Created .env with new random secrets (mode 600)")
    else:
        print(".env exists; left unchanged")


def cmd_colima_check() -> None:
    want_gb = int(_env().get("COLIMA_MEMORY", "8"))
    fix = f"colima start --cpu 6 --memory {want_gb} --disk 100 --vm-type vz --mount-type virtiofs"
    try:
        out = subprocess.run(
            ["colima", "list", "--json"], capture_output=True, text=True, check=True
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise PlatformError(f"Colima not found or failed ({exc}). Install it, then: {fix}") from exc
    profiles = [json.loads(line) for line in out.splitlines() if line.strip()]
    default = next((p for p in profiles if p.get("name") == "default"), None)
    if not default or default.get("status") != "Running":
        raise PlatformError(f"Colima is not running. Start it: {fix}")
    have_gb = round(int(default.get("memory", 0)) / 2**30)
    if have_gb != want_gb:
        raise PlatformError(
            f"Colima has {have_gb} GB but COLIMA_MEMORY={want_gb} (A30). Fix: colima stop && {fix}"
        )
    print(f"Colima running with {have_gb} GB")


def cmd_model_check() -> None:
    env = _env()
    aliases = models.load_aliases(LITELLM_CONFIG)
    models.check_external(
        aliases,
        env.get("ALLOW_EXTERNAL_MODELS", "false").lower() == "true",
        env.get("OPENAI_API_KEY", ""),
    )
    print("LiteLLM aliases: " + ", ".join(f"{a}={m}" for a, m in sorted(aliases.items())))


def cmd_render() -> None:
    env = _env()
    secrets = dict(
        zip(
            ("agent-reader", "agent-actor", "eval-runner"),
            envfile.require(
                env,
                "KEYCLOAK_SECRET_AGENT_READER",
                "KEYCLOAK_SECRET_AGENT_ACTOR",
                "KEYCLOAK_SECRET_EVAL_RUNNER",
            ),
            strict=True,
        )
    )
    (mock_key,) = envfile.require(env, "MOCK_CLIENT_SECRET_KEY")
    realm_json = realm.build_realm(realm.read_mock_stores(MOCK_STORES), secrets, mock_key)
    _write_private(RUN_DIR / "keycloak" / "realm-servewell.json", json.dumps(realm_json, indent=1))
    s3 = s3config.build_s3_config(env)
    _write_private(RUN_DIR / "seaweedfs" / "s3.json", json.dumps(s3, indent=1))
    (ROOT / env.get("LOG_DIR", "logs")).mkdir(exist_ok=True)
    print(f"Rendered {RUN_DIR}/keycloak/realm-servewell.json and {RUN_DIR}/seaweedfs/s3.json")


def cmd_db_init() -> None:
    passwords = dbinit.role_passwords(_env())
    for database, sql_file in dbinit.sql_files(ROOT / "db" / "sql"):
        script = dbinit.psql_script(sql_file, passwords)
        result = subprocess.run(
            [
                *COMPOSE,
                "exec",
                "-T",
                "postgres",
                "psql",
                "-X",
                "-q",
                "-U",
                "postgres",
                "-d",
                database,
                "-f",
                "-",
            ],
            input=script,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise PlatformError(f"{sql_file.name} failed:\n{result.stderr.strip()}")
        print(f"Applied {sql_file.name} on {database}")


def _weed_shell(commands: str) -> str:
    result = subprocess.run(
        [*COMPOSE, "exec", "-T", "seaweedfs", "weed", "shell", "-master=localhost:9333"],
        input=commands + "\nexit\n",
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise PlatformError(f"weed shell failed: {result.stderr.strip()}")
    return result.stdout


def cmd_buckets() -> None:
    existing = _weed_shell("s3.bucket.list")
    for bucket in s3config.BUCKETS:
        if any(line.strip().startswith(bucket) for line in existing.splitlines()):
            print(f"Bucket {bucket} exists")
            continue
        _weed_shell(f"s3.bucket.create -name {bucket}")
        print(f"Created bucket {bucket}")


def cmd_models() -> None:
    aliases = models.load_aliases(LITELLM_CONFIG)
    wanted = models.ollama_models(aliases)
    if not wanted:
        # D64: no Ollama alias, so nothing to pull or pin; list what each alias uses.
        for alias, model in sorted(aliases.items()):
            print(f"  {alias:<12} {model}")
        return
    pinned = models.ensure_models(wanted, MODEL_LOCK, OLLAMA_URL)
    for tag, digest in pinned.items():
        print(f"  {tag:<24} {digest[:12]}  matches lock")


def _ping(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:  # noqa: S310 - local URLs
            return bool(response.status == 200)
    except (urllib.error.URLError, OSError):
        return False


def cmd_status() -> None:
    env = _env()
    out = subprocess.run(
        [*COMPOSE, "ps", "--all", "--format", "json"], capture_output=True, text=True, check=True
    ).stdout
    rows = [json.loads(line) for line in out.splitlines() if line.strip()]
    failed = False
    print(f"{'SERVICE':<18} {'STATE':<10} HEALTH")
    for row in sorted(rows, key=lambda r: str(r["Service"])):
        health = row.get("Health") or "-"
        ok = row["State"] == "running" and health in ("healthy", "-")
        failed |= not ok
        print(f"{row['Service']:<18} {row['State']:<10} {health}{'' if ok else '  <-- FAIL'}")
    if not rows:
        print("(no containers)")
        failed = True
    aliases = models.load_aliases(LITELLM_CONFIG)
    print("\nLiteLLM aliases:")
    for alias, model in sorted(aliases.items()):
        print(f"  {alias:<12} {model}")
    if models.ollama_models(aliases):
        print("Ollama models (digest vs compose/ollama-models.lock):")
        lock = models.read_lock(MODEL_LOCK)
        try:
            local = models.local_digests(OLLAMA_URL)
        except models.ModelError as exc:
            print(f"  {exc}")
            local, failed = {}, True
        for tag, digest in sorted(lock.items()):
            ok = local.get(tag) == digest
            failed |= not ok
            print(f"  {tag:<24} {digest[:12]}  {'ok' if ok else 'MISSING OR DRIFT'}")
    checks: list[tuple[str, Callable[[], bool]]] = [
        (
            "Keycloak realm",
            lambda: _ping(env["KEYCLOAK_ISSUER"] + "/.well-known/openid-configuration"),
        ),
        ("OPA", lambda: _ping(env["OPA_URL"] + "/health")),
        (
            "it-data MCP",
            lambda: _ping(f"http://localhost:{env.get('IT_DATA_PORT', '8101')}/health"),
        ),
        (
            "knowledge MCP",
            lambda: _ping(f"http://localhost:{env.get('KNOWLEDGE_PORT', '8102')}/health"),
        ),
        (
            "itsm-actions MCP",
            lambda: _ping(f"http://localhost:{env.get('ITSM_PORT', '8103')}/health"),
        ),
    ]
    print()
    for name, check in checks:
        ok = check()
        failed |= not ok
        print(f"{name:<18} {'ok' if ok else 'FAIL'}")
    if failed:
        raise PlatformError("Platform is not healthy (see FAIL lines above)")


def cmd_mock_stores() -> None:
    dataset = os.environ.get("DATASET_DIR")
    if not dataset:
        raise PlatformError("Set DATASET_DIR to the dataset folder")
    count = realm.write_mock_stores(Path(dataset), MOCK_STORES)
    print(f"Wrote {count} store ids to {MOCK_STORES}")


def cmd_realm_reload() -> None:
    """Every realm object comes from the rendered file (clients, scopes, mock users), so
    deleting the realm and re-importing it loses nothing."""
    cmd_render()
    env = _env()
    (secret,) = envfile.require(env, "KEYCLOAK_ADMIN_CLIENT_SECRET")
    base = "http://localhost:8080"
    form = urllib.parse.urlencode(
        {
            "grant_type": "client_credentials",
            "client_id": "servewell-admin",
            "client_secret": secret,
        }
    ).encode()
    req = urllib.request.Request(  # noqa: S310 - fixed local URL
        f"{base}/realms/master/protocol/openid-connect/token", data=form, method="POST"
    )
    with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
        token = json.loads(resp.read())["access_token"]
    req = urllib.request.Request(  # noqa: S310 - fixed local URL
        f"{base}/admin/realms/servewell",
        method="DELETE",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        urllib.request.urlopen(req, timeout=30)  # noqa: S310
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise PlatformError(f"Keycloak realm delete failed: HTTP {exc.code}") from exc
    subprocess.run([*COMPOSE, "restart", "keycloak"], check=True)
    subprocess.run([*COMPOSE, "up", "-d", "--wait", "keycloak"], check=True)
    print("Realm servewell re-imported")


COMMANDS: dict[str, Callable[[], None]] = {
    "env": cmd_env,
    "colima-check": cmd_colima_check,
    "model-check": cmd_model_check,
    "render": cmd_render,
    "db-init": cmd_db_init,
    "buckets": cmd_buckets,
    "models": cmd_models,
    "status": cmd_status,
    "mock-stores": cmd_mock_stores,
    "realm-reload": cmd_realm_reload,
}


def main(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] not in COMMANDS:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        COMMANDS[argv[0]]()
    except (
        PlatformError,
        envfile.EnvError,
        models.ModelError,
        ValueError,
        FileNotFoundError,
    ) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
