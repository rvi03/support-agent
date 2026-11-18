"""Shared helpers for tests against the running platform (`make up`)."""

from __future__ import annotations

from functools import cache
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest

from support_agent.platform import envfile

ROOT = Path(__file__).resolve().parents[2]


@cache
def load_env() -> dict[str, str]:
    path = ROOT / ".env"
    if not path.exists():
        pytest.fail("No .env: run `make up` first")
    return envfile.load(path)


def superuser_url(env: dict[str, str], database: str = "servewell") -> str:
    return f"postgresql://postgres:{env['POSTGRES_PASSWORD']}@localhost:5432/{database}"


def with_database(url: str, database: str) -> str:
    parts = urlsplit(url)
    return urlunsplit(parts._replace(path=f"/{database}"))
