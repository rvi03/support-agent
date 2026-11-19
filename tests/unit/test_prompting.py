"""Skills and few-shot examples (S9, CP9.1).

The four skills and the Triage examples load into their node prompts with
versions; the examples come from the tune half only and stay out of the CP9.2
model-check and abstention sets (D39); each verdict is a valid TriageOutput and
each evidence quote is in the ticket text the example shows.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from support_agent.agent.grounding import normalize
from support_agent.agent.nodes import triage as triage_node
from support_agent.agent.prompting import (
    NODE_SKILL,
    SKILLS,
    load_examples,
    load_skill,
    system_prompt,
)
from support_agent.agent.state import TriageOutput

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
CASES = {
    "plain L1 fix",
    "guide first, then L2 (cause looks like hardware)",
    "escalate-now trigger",
    "device not at the store (E2/E3)",
    "fake asset (E4)",
    "unknown system (E5)",
    "wrong category (E8)",
    "not IT (redirect to HR)",
    "too vague (clarify)",
    "documents disagree (error code)",
}


def _examples() -> tuple[dict, ...]:
    return load_examples("triage")[1]


@pytest.mark.parametrize("name", SKILLS)
def test_each_skill_has_a_version_and_loads_into_its_node(name: str) -> None:
    skill = load_skill(name)
    assert skill.version.startswith(f"{name} v")
    node = next(n for n, s in NODE_SKILL.items() if s == name)
    prompt = system_prompt(node)
    assert skill.text in prompt.text
    assert skill.version in prompt.version


def test_triage_prompt_holds_base_skill_and_every_example() -> None:
    prompt = system_prompt("triage")
    assert prompt.version == "triage v11; handle-ticket v3; triage-examples v2"
    assert triage_node.PROMPT_VERSION == prompt.version
    assert prompt.text.startswith("<!-- triage prompt v11")
    assert prompt.text.index("# Skill: handle a ticket") < prompt.text.index("# Worked examples")
    for n, ex in enumerate(_examples(), start=1):
        assert f"## Example {n}: {ex['case']}" in prompt.text
        assert ex["ticket"]["subject"] in prompt.text


def test_ten_examples_one_per_case() -> None:
    examples = _examples()
    assert len(examples) == 10
    assert {ex["case"] for ex in examples} == CASES
    assert len({ex["id"] for ex in examples}) == 10


def test_examples_are_tune_only_and_outside_the_check_sets() -> None:
    split = json.loads((ROOT / "eval/split.json").read_text())
    tune = set(split["tune"]["labelled"]) | set(split["tune"]["tricky"])
    held = set(split["heldout"]["labelled"]) | set(split["heldout"]["tricky"])
    check = json.loads((ROOT / "eval/model_check.json").read_text())
    abst = json.loads((ROOT / "eval/abstention.json").read_text())["tickets"]
    ids = {ex["id"] for ex in _examples()}
    assert ids <= tune
    assert not ids & held
    assert not ids & set(check["group_a"] + check["mixed"] + abst)


def test_held_out_guard_scans_the_examples() -> None:
    """The repo-wide guard also reads every example file, by id pattern."""
    from tests.unit.test_no_heldout_in_tests import PROMPT_DIRS

    assert "src/support_agent/agent/examples" in PROMPT_DIRS
    assert (ROOT / "src/support_agent/agent/examples/triage.yaml").is_file()


@pytest.mark.parametrize("ex", _examples(), ids=lambda e: e["id"])
def test_verdict_is_valid_and_evidence_is_in_the_shown_ticket(ex: dict) -> None:
    out = TriageOutput.model_validate(ex["verdict"])
    shown = normalize(ex["ticket"]["subject"] + " " + ex["ticket"]["description"])
    for hit in out.sop_triggers:
        assert normalize(hit.evidence) in shown, hit.trigger
    if out.runbook_id:
        assert out.runbook_evidence is not None
        assert out.runbook_evidence.section_id.startswith(out.runbook_id + "#")
        assert len(out.runbook_evidence.quote) >= 20
        assert any(f'get_document("{out.runbook_id}")' in lk for lk in ex["lookups"])
    else:
        assert out.runbook_evidence is None
