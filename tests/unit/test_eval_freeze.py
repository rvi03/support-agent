"""CP14.7: the freeze manifest refuses held-out work after any change (D56)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from support_agent.eval import freeze, runner, score

pytestmark = pytest.mark.unit

FROZEN = {"rubrics": "sha256:aaa", "kb_rev": ["kb-1"], "model_ids": {"judge": "m1"}}


@pytest.fixture
def manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "frozen_settings.json"
    path.write_text(json.dumps({"hash": freeze.manifest_hash(FROZEN), "manifest": FROZEN}))
    monkeypatch.setattr(freeze, "MANIFEST", path)
    return path


def _now(**changed: Any) -> Any:
    return lambda settings, probe=True: {**FROZEN, **changed}


def test_unchanged_state_passes(manifest: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(freeze, "build", _now())
    assert freeze.check(settings=object()) == freeze.manifest_hash(FROZEN)  # type: ignore[arg-type]


def test_changed_rubric_or_model_refuses(manifest: Path, monkeypatch: pytest.MonkeyPatch,
                                         capsys: pytest.CaptureFixture[str]) -> None:  # fmt: skip
    monkeypatch.setattr(freeze, "build", _now(rubrics="sha256:bbb"))
    with pytest.raises(SystemExit):
        freeze.check(settings=object())  # type: ignore[arg-type]
    assert "rubrics" in capsys.readouterr().err
    monkeypatch.setattr(freeze, "build", _now(model_ids={"judge": "m2"}))
    with pytest.raises(SystemExit):
        freeze.check(settings=object())  # type: ignore[arg-type]


def test_no_manifest_refuses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(freeze, "MANIFEST", tmp_path / "missing.json")
    with pytest.raises(SystemExit, match="no eval/frozen_settings.json"):
        freeze.check(settings=object())  # type: ignore[arg-type]


class RefusedError(Exception):
    pass


def _refuse(*_: Any, **__: Any) -> str:
    raise RefusedError


@pytest.mark.parametrize("split", ["heldout", "all"])
def test_runner_checks_freeze_before_anything(split: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner, "get_settings", lambda cls: object())
    monkeypatch.setattr(freeze, "check", _refuse)
    monkeypatch.setattr(runner, "load_dataset_items", lambda s: pytest.fail("network reached"))
    with pytest.raises(RefusedError):
        asyncio.run(runner.run(split, set(), None, "x"))


def test_heldout_scoring_checks_freeze(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class Conn:
        def __enter__(self) -> Conn:
            return self

        def __exit__(self, *a: object) -> None:
            return None

    monkeypatch.setattr(score, "get_settings", lambda cls: type("S", (), {
        "database_url_eval": None, "db_host": None})())  # fmt: skip
    monkeypatch.setattr("psycopg.connect", lambda *a, **k: Conn())
    monkeypatch.setattr(score, "dsn", lambda *a: "")
    monkeypatch.setattr(score, "load_run", lambda name, conn: score.Run(
        name, {"split": "heldout", "items": [], "freeze_hash": "h"}, {}, {}, {}))  # fmt: skip
    monkeypatch.setattr(freeze, "check", _refuse)
    with pytest.raises(RefusedError):
        score.main(["--run", "heldout-x", "--no-judge", "--no-push"])
