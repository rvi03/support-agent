"""CP1.2: a missing required setting exits with a clear error naming it."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from support_agent.common import config

pytestmark = pytest.mark.unit

AGENT_REQUIRED = {"DATABASE_URL_AGENT", "ACTION_AUTONOMY_RUNS"}
SHARED_REQUIRED = {"KEYCLOAK_ISSUER", "OPA_URL", "LITELLM_BASE_URL"}


def _run_config(service: str, env: dict[str, str], cwd: Path) -> subprocess.CompletedProcess[str]:
    base = {"PATH": os.environ["PATH"], "PYTHONPATH": os.pathsep.join(sys.path)}
    return subprocess.run(
        [sys.executable, "-m", "support_agent.common.config", service],
        env={**base, **env},
        cwd=cwd,  # an empty folder, so no .env is read
        capture_output=True,
        text=True,
        check=False,
    )


def _missing(stderr: str) -> set[str]:
    prefix = "Missing setting: "
    return {line[len(prefix) :] for line in stderr.splitlines() if line.startswith(prefix)}


def test_empty_env_exits_2_naming_only_agent_settings(tmp_path: Path) -> None:
    result = _run_config("agent", {}, tmp_path)

    assert result.returncode == 2
    assert _missing(result.stderr) == AGENT_REQUIRED | SHARED_REQUIRED
    for other in ("INGEST", "INTAKE", "IT_DATA", "KNOWLEDGE", "ITSM", "API", "EVAL", "CHECKER"):
        assert f"_{other}" not in result.stderr


def test_one_missing_setting_is_named_alone(tmp_path: Path) -> None:
    env = {
        "KEYCLOAK_ISSUER": "http://localhost:8080/realms/servewell",
        "OPA_URL": "http://localhost:8181",
        "LITELLM_BASE_URL": "http://localhost:4000",
        "DATABASE_URL_AGENT": "postgresql://agent:x@localhost/servewell",
    }
    result = _run_config("agent", env, tmp_path)

    assert result.returncode == 2
    assert result.stderr.strip() == "Missing setting: ACTION_AUTONOMY_RUNS"


def test_invalid_value_is_named(tmp_path: Path) -> None:
    env = {
        "KEYCLOAK_ISSUER": "k",
        "OPA_URL": "o",
        "LITELLM_BASE_URL": "l",
        "DATABASE_URL_AGENT": "d",
        "ACTION_AUTONOMY_RUNS": "0",
    }
    result = _run_config("agent", env, tmp_path)

    assert result.returncode == 2
    assert result.stderr.startswith("Invalid setting: ACTION_AUTONOMY_RUNS:")


def test_complete_env_loads_without_printing_secrets(tmp_path: Path) -> None:
    env = {
        "KEYCLOAK_ISSUER": "k",
        "OPA_URL": "o",
        "LITELLM_BASE_URL": "l",
        "DATABASE_URL_AGENT": "postgresql://agent:topsecret@localhost/db",
        "ACTION_AUTONOMY_RUNS": "1",
    }
    result = _run_config("agent", env, tmp_path)

    assert result.returncode == 0, result.stderr
    assert "topsecret" not in result.stdout + result.stderr


def test_unknown_service_exits_2(tmp_path: Path) -> None:
    result = _run_config("nope", {}, tmp_path)

    assert result.returncode == 2
    assert result.stderr.startswith("Usage:")


@pytest.mark.parametrize("cls", [config.AgentSettings, config.ApiSettings])
def test_agent_and_api_hold_no_eval_checker_or_ingest_field(
    cls: type[config.BaseServiceSettings],
) -> None:
    fields = set(cls.model_fields)
    assert not {f for f in fields if f.endswith(("_eval", "_checker", "_ingest"))}
    assert not fields & {"model_judge", "model_simulator"}  # eval-only settings


def test_each_service_owns_only_its_credentials() -> None:
    for name, cls in config.SERVICES.items():
        secret_fields = {
            f for f, info in cls.model_fields.items() if info.annotation is config.SecretStr
        }
        assert secret_fields, name
        assert all(f.endswith(f"_{name}") for f in secret_fields), (name, secret_fields)


def test_get_settings_in_process(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    for key in ("KEYCLOAK_ISSUER", "OPA_URL", "LITELLM_BASE_URL"):
        monkeypatch.setenv(key, "x")
    monkeypatch.setenv("DATABASE_URL_CHECKER", "postgresql://c")

    settings = config.get_settings(config.CheckerSettings)

    assert settings.database_url_checker.get_secret_value() == "postgresql://c"
    assert settings.clock_mode is config.ClockMode.LIVE
    assert config.main(["checker"]) == 0


def test_env_example_lists_every_setting_and_nothing_else() -> None:
    example = Path(__file__).resolve().parents[2] / ".env.example"
    keys = {
        line.split("=", 1)[0]
        for line in example.read_text().splitlines()
        if line and not line.startswith("#")
    }
    fields = {f.upper() for cls in config.SERVICES.values() for f in cls.model_fields}
    assert keys == fields


def test_get_settings_in_process_exits_2(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    for key in list(os.environ):
        monkeypatch.delenv(key)
    monkeypatch.setenv("EMBED_DIM", "zero")

    with pytest.raises(SystemExit) as exc:
        config.main(["knowledge"])
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "Missing setting: DATABASE_URL_KNOWLEDGE" in err
    assert "Invalid setting: EMBED_DIM:" in err

    with pytest.raises(SystemExit):
        config.main([])
