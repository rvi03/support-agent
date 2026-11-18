"""Apply `db/sql/NNN_*.sql` in order with role passwords from `.env` (S2 step 3).

Passwords are taken from each service's DATABASE_URL_* (one source of truth)
and passed to psql as `\\set` lines on stdin, never on a command line.
`000_*` runs on database `postgres`; the rest run on `servewell`.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote, urlsplit

from support_agent.platform.envfile import EnvError, require

# psql variable -> .env variable holding a URL with that role's password
URL_ROLES = {
    "ingest_rw": "DATABASE_URL_INGEST",
    "intake_rw": "DATABASE_URL_INTAKE",
    "it_data_ro": "DATABASE_URL_IT_DATA",
    "knowledge_ro": "DATABASE_URL_KNOWLEDGE",
    "kb_index_rw": "DATABASE_URL_KB_INDEX",
    "itsm_rw": "DATABASE_URL_ITSM",
    "agent_actor": "DATABASE_URL_AGENT",
    "api_rw": "DATABASE_URL_API",
    "eval_ro": "DATABASE_URL_EVAL",
    "checker_ro": "DATABASE_URL_CHECKER",
}
PASSWORD_ROLES = {"langfuse": "LANGFUSE_DB_PASSWORD", "keycloak": "KEYCLOAK_DB_PASSWORD"}


def role_passwords(env: dict[str, str]) -> dict[str, str]:
    passwords: dict[str, str] = {}
    for role, var in URL_ROLES.items():
        (url,) = require(env, var)
        parts = urlsplit(url)
        if parts.username != role or not parts.password:
            raise EnvError(f"{var} must use role {role} with a password (got {parts.username})")
        passwords[role] = unquote(parts.password)
    for role, var in PASSWORD_ROLES.items():
        (passwords[role],) = require(env, var)
    return passwords


def _quote(value: str) -> str:
    # psql meta-command quoting: backslashes doubled, single quotes doubled.
    return "'" + value.replace("\\", "\\\\").replace("'", "''") + "'"


def psql_script(sql_file: Path, passwords: dict[str, str]) -> str:
    sets = "".join(f"\\set pw_{role} {_quote(pw)}\n" for role, pw in sorted(passwords.items()))
    return sets + "\\set ON_ERROR_STOP on\n" + sql_file.read_text(encoding="utf-8")


def sql_files(sql_dir: Path) -> list[tuple[str, Path]]:
    """(database, file) in apply order."""
    files = sorted(sql_dir.glob("[0-9][0-9][0-9]_*.sql"))
    if not files:
        raise FileNotFoundError(f"No SQL files in {sql_dir}")
    return [("postgres" if f.name.startswith("000_") else "servewell", f) for f in files]
