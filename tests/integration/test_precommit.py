"""CP1.4: the installed pre-commit hook blocks a lint error or a .env file.

Runs a real `git commit` in a temp repo that has this repo's hook config and
project files (Codex S1: test the installed hook, not the config alone).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]
PROJECT_FILES = [".pre-commit-config.yaml", "pyproject.toml", "uv.lock", ".python-version"]


def _env(home: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "VIRTUAL_ENV"))}
    env.update(
        GIT_CONFIG_GLOBAL=str(home / "gitconfig"),  # no user hooksPath or templates
        GIT_CONFIG_NOSYSTEM="1",
        GIT_AUTHOR_NAME="test",
        GIT_AUTHOR_EMAIL="test@example.invalid",
        GIT_COMMITTER_NAME="test",
        GIT_COMMITTER_EMAIL="test@example.invalid",
        PRE_COMMIT_HOME=str(home / "pre-commit"),
    )
    return env


def _run(args: list[str], repo: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=repo, env=env, capture_output=True, text=True, check=False)


@pytest.fixture
def repo(tmp_path: Path) -> Iterator[tuple[Path, dict[str, str]]]:
    if shutil.which("git") is None or shutil.which("uv") is None:
        pytest.fail("git and uv are required for the pre-commit hook test")
    repo = tmp_path / "repo"
    (repo / "src" / "support_agent").mkdir(parents=True)
    for name in PROJECT_FILES:
        shutil.copy2(ROOT / name, repo / name)
    (repo / "README.md").write_text("test\n")
    (repo / "src" / "support_agent" / "__init__.py").write_text("")
    env = _env(tmp_path)
    for args in (
        ["git", "init", "--quiet", "--initial-branch=main"],
        ["git", "add", "."],
        ["git", "commit", "--quiet", "--no-verify", "-m", "base"],
        [sys.executable, "-m", "pre_commit", "install"],
    ):
        result = _run(args, repo, env)
        assert result.returncode == 0, result.stdout + result.stderr
    assert (repo / ".git" / "hooks" / "pre-commit").exists()
    yield repo, env


def _commit(repo: Path, env: dict[str, str], name: str, text: str) -> tuple[int, str]:
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    assert _run(["git", "add", "--", name], repo, env).returncode == 0
    result = _run(["git", "commit", "--quiet", "-m", f"add {name}"], repo, env)
    if result.returncode != 0:
        _run(["git", "reset", "--quiet", "--", name], repo, env)
        path.unlink()
    return result.returncode, result.stdout + result.stderr


@pytest.mark.parametrize(
    ("name", "text", "failed_hook"),
    [
        ("src/support_agent/bad.py", "import os\n", "ruff lint"),  # F401 unused import
        (".env", "DATABASE_URL_AGENT=postgresql://agent:real@db/servewell\n", "block .env"),
        (".env.local", "OPA_URL=http://opa\n", "block .env"),
        ("config/.env.prod", "OPA_URL=http://opa\n", "block .env"),
        (
            "key.txt",
            "-----BEGIN RSA PRIVATE KEY-----\nabc\n-----END RSA PRIVATE KEY-----\n",
            "detect private key",
        ),
    ],
)
def test_commit_is_refused(
    repo: tuple[Path, dict[str, str]], name: str, text: str, failed_hook: str
) -> None:
    path, env = repo
    code, output = _commit(path, env, name, text)
    assert code != 0
    failed = [line for line in output.splitlines() if line.endswith("Failed")]
    assert len(failed) == 1 and failed[0].startswith(failed_hook), output
    log = _run(["git", "log", "--oneline"], path, env).stdout
    assert len(log.splitlines()) == 1  # only the base commit


def test_clean_file_and_env_example_commit(repo: tuple[Path, dict[str, str]]) -> None:
    path, env = repo
    code, output = _commit(path, env, "src/support_agent/ok.py", '"""Fine."""\n\nVALUE = 1\n')
    assert code == 0, output
    code, output = _commit(path, env, ".env.example", "OPA_URL=http://localhost:8181\n")
    assert code == 0, output
