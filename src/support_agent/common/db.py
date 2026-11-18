"""Connection strings for services that may run in a container (S5)."""

from __future__ import annotations

from psycopg.conninfo import conninfo_to_dict, make_conninfo
from pydantic import SecretStr


def dsn(url: SecretStr, db_host: str | None = None) -> str:
    """The service's DSN, with the host replaced when `DB_HOST` is set (compose sets
    `postgres`, so one `.env` serves the host and the containers)."""
    raw = url.get_secret_value()
    if not db_host:
        return raw
    parts = conninfo_to_dict(raw)
    parts["host"] = db_host
    return make_conninfo("", **{k: str(v) for k, v in parts.items() if v is not None})
