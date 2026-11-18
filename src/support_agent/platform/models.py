"""LiteLLM model slots and the Ollama model lock (S2 build steps 8 and 9).

- Every alias in `compose/litellm/config.yaml` must point at Ollama unless
  ALLOW_EXTERNAL_MODELS=true is set for that run (Codex P1, D21, D26).
- The Ollama models those aliases use are pulled if missing and pinned by
  digest in `compose/ollama-models.lock`; a later run fails on any drift.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

REQUIRED_ALIASES = ("agent", "embed", "moderation", "judge", "simulator")
OLLAMA_PREFIXES = ("ollama/", "ollama_chat/")

Fetch = Callable[[str, str, dict[str, Any] | None], dict[str, Any]]


class ModelError(RuntimeError):
    """A model slot, pull or digest check failed."""


def load_aliases(config_path: Path) -> dict[str, str]:
    """alias -> litellm model string, from the LiteLLM proxy config."""
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    aliases: dict[str, str] = {}
    for entry in config.get("model_list", []):
        aliases[str(entry["model_name"])] = str(entry["litellm_params"]["model"])
    missing = [a for a in REQUIRED_ALIASES if a not in aliases]
    if missing:
        raise ModelError(f"LiteLLM config has no alias for: {', '.join(missing)}")
    return aliases


def check_external(aliases: dict[str, str], allow_external: bool, openai_key: str = "") -> None:
    external = {a: m for a, m in aliases.items() if not m.startswith(OLLAMA_PREFIXES)}
    if external and not allow_external:
        listed = ", ".join(f"{a}={m}" for a, m in sorted(external.items()))
        raise ModelError(
            f"Non-Ollama model(s) in the LiteLLM config: {listed}. "
            "Set ALLOW_EXTERNAL_MODELS=true for this run to allow them."
        )
    if any(m.startswith("openai/") for m in external.values()) and not openai_key.strip():
        raise ModelError("OPENAI_API_KEY is empty in .env; add your key (D64).")


def normalize_tag(name: str) -> str:
    return name if ":" in name else f"{name}:latest"


def ollama_models(aliases: dict[str, str]) -> list[str]:
    """Ollama tags the aliases use, sorted and de-duplicated."""
    tags = {
        normalize_tag(model.split("/", 1)[1])
        for model in aliases.values()
        if model.startswith(OLLAMA_PREFIXES)
    }
    return sorted(tags)


def http_json(method: str, url: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(  # noqa: S310 - fixed local Ollama URL
        url, data=data, method=method, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=3600) as response:  # noqa: S310
        result: dict[str, Any] = json.loads(response.read() or b"{}")
        return result


def local_digests(base_url: str, fetch: Fetch = http_json) -> dict[str, str]:
    try:
        tags = fetch("GET", f"{base_url}/api/tags", None)
    except (urllib.error.URLError, OSError) as exc:
        raise ModelError(
            f"Ollama is not answering at {base_url} ({exc}). "
            "Start it: `brew services start ollama`."
        ) from exc
    return {normalize_tag(m["name"]): str(m["digest"]) for m in tags.get("models", [])}


def read_lock(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    data: dict[str, str] = json.loads(path.read_text(encoding="utf-8"))["models"]
    return data


def write_lock(path: Path, digests: dict[str, str]) -> None:
    body = {"models": dict(sorted(digests.items()))}
    path.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")


def ensure_models(
    wanted: list[str],
    lock_path: Path,
    base_url: str,
    fetch: Fetch = http_json,
    log: Callable[[str], None] = print,
) -> dict[str, str]:
    """Pull missing models, then check every digest against the lock.

    With no lock entry for a model, its digest is added to the lock. A lock
    entry that differs from the local digest is drift and fails the run.
    """
    local = local_digests(base_url, fetch)
    for tag in wanted:
        if tag not in local:
            log(f"Pulling {tag} ...")
            fetch("POST", f"{base_url}/api/pull", {"model": tag, "stream": False})
    local = local_digests(base_url, fetch)
    lock = read_lock(lock_path)
    drift = []
    for tag in wanted:
        if tag not in local:
            raise ModelError(f"{tag} is still missing after the pull")
        if tag in lock and lock[tag] != local[tag]:
            drift.append(f"{tag}: lock {lock[tag][:12]} != local {local[tag][:12]}")
    if drift:
        raise ModelError(
            "Model digest drift (re-pull the locked version, or update the lock on purpose): "
            + "; ".join(drift)
        )
    stale = sorted(set(lock) - set(wanted))
    if stale:
        raise ModelError(f"Lock lists models no alias uses: {', '.join(stale)}")
    pinned = {tag: local[tag] for tag in wanted}
    if pinned != lock:
        write_lock(lock_path, pinned)
        log(f"Wrote {lock_path}")
    return pinned
