"""Skills and few-shot examples loaded into node prompts (S9, D105).

- A skill is a versioned markdown playbook in `agent/skills/` whose first line is
  `<!-- skill <name> v<n> ... -->`.
- Few-shot examples are versioned YAML in `agent/examples/<node>.yaml`, taken from
  the tune half only (D39; `tests/unit/test_no_heldout_in_tests.py`).
- `system_prompt(node)` builds the fixed part of a node's prompt: the node's base
  prompt (if any), its skill, then its rendered examples. The version string names
  every part, so a trace shows exactly what the model saw.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import cache
from importlib import resources
from typing import Any

import yaml

from support_agent.agent.state import TriageOutput

SKILLS = ("handle-ticket", "walk-runbook", "write-l2-note", "write-l1-pack")
NODE_SKILL = {
    "triage": "handle-ticket",
    "resolver": "walk-runbook",
    "handoff": "write-l2-note",
    "l1_pack": "write-l1-pack",
}
NODE_BASE = {"triage": "triage.md"}  # nodes with a base prompt in agent/prompts/
NODE_EXAMPLES = {"triage": "triage.yaml"}
_HEADER = re.compile(r"<!--\s*(?:skill\s+)?(?P<name>[\w-]+)(?:\s+prompt)?\s+(?P<ver>v\d+)\b")


def _version(first_line: str, kind: str) -> str:
    m = _HEADER.match(first_line.strip())
    if m is None:
        raise ValueError(f"{kind} has no version header: {first_line!r}")
    return f"{m['name']} {m['ver']}"


@dataclass(frozen=True)
class Part:
    text: str
    version: str


@cache
def load_skill(name: str) -> Part:
    if name not in SKILLS:
        raise KeyError(name)
    text = resources.files("support_agent.agent.skills").joinpath(f"{name}.md").read_text()
    return Part(text, _version(text.splitlines()[0], f"skill {name}"))


@cache
def load_base(node: str) -> Part:
    text = resources.files("support_agent.agent.prompts").joinpath(NODE_BASE[node]).read_text()
    return Part(text, _version(text.splitlines()[0], f"prompt {node}"))


@cache
def load_examples(node: str) -> tuple[str, tuple[dict[str, Any], ...]]:
    """(version, examples); each Triage verdict must be a valid `TriageOutput`."""
    raw = resources.files("support_agent.agent.examples").joinpath(NODE_EXAMPLES[node]).read_text()
    data = yaml.safe_load(raw)
    examples = tuple(data["examples"])
    if node == "triage":
        for ex in examples:
            TriageOutput.model_validate(ex["verdict"])
    return str(data["version"]), examples


def render_examples(examples: tuple[dict[str, Any], ...]) -> str:
    out = ["# Worked examples"]
    for n, ex in enumerate(examples, start=1):
        t = ex["ticket"]
        history = "\n".join(f"  - {h}" for h in t.get("history") or []) or "  (none)"
        lookups = "\n".join(f"  {i}. {lk}" for i, lk in enumerate(ex["lookups"], 1)) or "  (none)"
        out.append(
            f"## Example {n}: {ex['case']}\n"
            f"Ticket: category {t['category']}, asset {t['asset_id']}, "
            f"version {t['system_version']}\n"
            f"Subject: {t['subject']}\n"
            f"Description: {t['description']}\n"
            f"History:\n{history}\n"
            f"Facts: {ex['facts']}\n"
            f"Lookups:\n{lookups}\n"
            f"Verdict: {json.dumps(ex['verdict'], ensure_ascii=False)}\n"
            f"Why: {ex['why']}"
        )
    return "\n\n".join(out) + "\n"


def system_prompt(node: str) -> Part:
    """The fixed prompt for a node: base prompt, skill, examples (each if present)."""
    parts: list[Part] = []
    if node in NODE_BASE:
        parts.append(load_base(node))
    parts.append(load_skill(NODE_SKILL[node]))
    if node in NODE_EXAMPLES:
        version, examples = load_examples(node)
        parts.append(Part(render_examples(examples), version))
    return Part("\n".join(p.text for p in parts), "; ".join(p.version for p in parts))
