"""Read `.env` and create it from `.env.example` with fresh random secrets."""

from __future__ import annotations

import re
import secrets
from pathlib import Path

PLACEHOLDER = "change-me"
HEX_PLACEHOLDER = "change-me-hex32"
_LINE = re.compile(r"^([A-Z][A-Z0-9_]*)=(.*)$")


class EnvError(RuntimeError):
    """A required variable is missing or still a placeholder."""


def parse(text: str) -> dict[str, str]:
    """Parse KEY=VALUE lines; comments and blank lines are skipped."""
    values: dict[str, str] = {}
    for raw in text.splitlines():
        match = _LINE.match(raw.strip())
        if match:
            values[match.group(1)] = match.group(2)
    return values


def load(path: Path) -> dict[str, str]:
    return parse(path.read_text(encoding="utf-8"))


def fill_placeholders(example: str) -> str:
    """Replace every placeholder with a new random value, one per occurrence."""
    text = example.replace(HEX_PLACEHOLDER, "\0HEX\0")
    while PLACEHOLDER in text:
        text = text.replace(PLACEHOLDER, secrets.token_urlsafe(24).replace("-", "x"), 1)
    while "\0HEX\0" in text:
        text = text.replace("\0HEX\0", secrets.token_hex(32), 1)
    return text


def init_env(example: Path, target: Path) -> bool:
    """Create `target` from `example` if it does not exist. Returns True if created."""
    if target.exists():
        return False
    target.write_text(fill_placeholders(example.read_text(encoding="utf-8")), encoding="utf-8")
    target.chmod(0o600)
    return True


def require(env: dict[str, str], *names: str) -> list[str]:
    """Return the values of `names`, failing on a missing value or a placeholder."""
    bad = [n for n in names if not env.get(n) or PLACEHOLDER in env[n]]
    if bad:
        raise EnvError("Missing or placeholder setting(s) in .env: " + ", ".join(bad))
    return [env[n] for n in names]
