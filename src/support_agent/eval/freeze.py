"""S14 build step 9: the freeze manifest (D56, CP14.7).

`make freeze` writes `eval/frozen_settings.json`; every entry point that runs or
scores a held-out id calls `check()`, which rebuilds the manifest and refuses
(exit) when anything differs, naming the keys.

The manifest holds content hashes, not a git commit, so it is exact even before
the work is committed: the agent code (`src/`, prompts, skills, examples and
bindings included), the eval code and data (eval package, rubrics, fault cards,
split, adversarial cases), the action registry, the OPA policies, the LiteLLM
alias table (which model each alias names), the tuned settings from `.env`, the
published `kb_rev`, the model id each chat alias answers with (a probe call), the
no-promotion rule and the starting autonomy rule.

Freeze refuses without a passed judge calibration (`eval/hand/calibration.csv`,
>= 80% agreement on 10 tune items, CP14.3), because the judge must be checked
against a human before held-out scores mean anything.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import psycopg
from dotenv import dotenv_values

from support_agent.common.config import EvalSettings, get_settings
from support_agent.common.db import dsn

ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / "eval" / "frozen_settings.json"
CALIBRATION = ROOT / "eval" / "hand" / "calibration.csv"
CALIBRATION_MIN = 0.8
TUNED_ENV = (
    "CONFIDENCE_MIN", "TOKEN_BUDGET_PER_TICKET", "ACTION_AUTONOMY_RUNS",
    "REPLAY_REPLY_DELAY_MIN", "APPROVAL_TTL_MIN", "KB_BUDGET_TOKENS",
)  # fmt: skip
CHAT_ALIASES = ("agent", "moderation", "judge", "simulator")
SKIP_PARTS = {"__pycache__", "runs", "reports", "hand", ".pytest_cache"}
SKIP_FILES = {"frozen_settings.json"}


def tree_hash(paths: Iterable[Path]) -> str:
    h = hashlib.sha256()
    files: list[Path] = []
    for p in paths:
        if p.is_file():
            files.append(p)
        elif p.is_dir():
            files += [f for f in p.rglob("*") if f.is_file()]
    for f in sorted(set(files)):
        rel = f.relative_to(ROOT)
        if SKIP_PARTS & set(rel.parts) or f.name in SKIP_FILES or f.suffix == ".pyc":
            continue
        h.update(str(rel).encode() + b"\0" + f.read_bytes() + b"\0")
    return "sha256:" + h.hexdigest()


def calibration_agreement(path: Path = CALIBRATION) -> tuple[int, int]:
    """(agreeing, scored) rows of the tune calibration form (`human` vs `judge`)."""
    import csv

    if not path.is_file():
        return 0, 0
    rows = [r for r in csv.DictReader(path.open()) if (r.get("human") or "").strip()]
    agree = sum(1 for r in rows if r["human"].strip().lower() == r["judge"].strip().lower())
    return agree, len(rows)


async def _probe_models(settings: EvalSettings) -> dict[str, str | None]:
    from support_agent.agent.llm import ChatClient, TicketBudget

    out: dict[str, str | None] = {}
    for alias in CHAT_ALIASES:
        llm = ChatClient(settings.litellm_base_url,
                         settings.litellm_master_key.get_secret_value(), model=alias)  # fmt: skip
        try:
            r = await llm.complete([{"role": "user", "content": "Reply with: ok"}],
                                   TicketBudget(1, 2_000))  # fmt: skip
            out[alias] = r.model
        finally:
            await llm.aclose()
    return out


def build(settings: EvalSettings, *, probe: bool = True) -> dict[str, Any]:
    env = dotenv_values(ROOT / ".env")
    with psycopg.connect(dsn(settings.database_url_eval, settings.db_host)) as conn:
        revs = sorted(r[0] for r in conn.execute("SELECT DISTINCT kb_rev FROM kb.documents"))
    src = ROOT / "src" / "support_agent"
    m: dict[str, Any] = {
        "agent_code": tree_hash([src / p for p in ("agent", "api", "intake", "mcp", "kb",
                                                   "common", "cli")]),  # fmt: skip
        "prompts": tree_hash([src / "agent" / "prompts", src / "agent" / "skills",
                              src / "agent" / "examples"]),  # fmt: skip
        "bindings": tree_hash([src / "agent" / "bindings.yaml"]),
        "registry": tree_hash([src / "mcp" / "itsm" / "registry.yaml"]),
        "eval_code": tree_hash([src / "eval"]),
        "rubrics": tree_hash([ROOT / "eval" / "rubrics"]),
        "fault_cards": tree_hash([ROOT / "eval" / "fault_cards"]),
        "split": tree_hash([ROOT / "eval" / "split.json"]),
        "adversarial": tree_hash([ROOT / "eval" / "adversarial"]),
        "opa_policies": tree_hash([ROOT / "compose" / "opa" / "policies"]),
        "litellm_aliases": tree_hash([ROOT / "compose" / "litellm" / "config.yaml"]),
        "settings": {k: env.get(k) for k in TUNED_ENV},
        "model_aliases": {"agent": "agent", "judge": settings.model_judge,
                          "simulator": settings.model_simulator, "embed": settings.model_embed},
        "kb_rev": revs,
        "eval_mode_no_promotion": True,  # D47: itsm never promotes in EVAL_MODE
        "starting_autonomy": "every reversible action supervised (make eval-mode)",
    }  # fmt: skip
    if probe:
        m["model_ids"] = asyncio.run(_probe_models(settings))
    return m


def manifest_hash(m: dict[str, Any]) -> str:
    raw = json.dumps(m, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode()).hexdigest()


def diff(a: dict[str, Any], b: dict[str, Any]) -> list[str]:
    return sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))


def check(settings: EvalSettings | None = None) -> str:
    """Refuse (exit 3) unless the current state equals the frozen manifest."""
    if not MANIFEST.is_file():
        raise SystemExit("held-out refused: no eval/frozen_settings.json (run `make freeze`)")
    frozen = json.loads(MANIFEST.read_text())
    now = build(settings or get_settings(EvalSettings))
    changed = diff(frozen["manifest"], now)
    if changed:
        print(f"held-out refused: changed since freeze: {', '.join(changed)}", file=sys.stderr)
        raise SystemExit(3)
    return str(frozen["hash"])


def main(argv: list[str]) -> int:
    settings = get_settings(EvalSettings)
    if argv and argv[0] == "check":
        print(check(settings))
        return 0
    agree, scored = calibration_agreement()
    if scored < 10 or agree / scored < CALIBRATION_MIN:
        raise SystemExit(
            f"freeze refused: judge calibration {agree}/{scored} on the tune form "
            f"(needs 10 scored rows and >= {CALIBRATION_MIN:.0%}; `make hand-forms`, fill "
            "eval/hand/calibration.csv)"
        )
    m = build(settings)
    MANIFEST.write_text(json.dumps({"hash": manifest_hash(m), "calibration": f"{agree}/{scored}",
                                    "manifest": m}, indent=1) + "\n")  # fmt: skip
    print(f"frozen: {manifest_hash(m)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
