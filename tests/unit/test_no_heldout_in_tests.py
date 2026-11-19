"""Held-out leakage guard (S8 risks, review M8, D39).

No held-out ticket id may appear under tests/ or in the fixed eval lists, so no
prompt, rule or threshold is tuned against the held-out half. The allow-list
holds only the earlier tests that assert code facts (seed, masking, it-data
outcomes; CP3.x, CP4.2, CP5.2), never agent behaviour.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
ALLOWED = {
    "tests/fixtures/pii_marked.yaml",  # CP4.2 masking fixture
    "tests/integration/test_intake_seed.py",  # CP4.x leak-line drop on the seeded set
    "tests/integration/test_it_data.py",  # CP5.2 it-data outcomes
    "tests/unit/test_csv_clean.py",  # CP3.x path cleaning
    "tests/unit/test_intake_leak_schema.py",  # CP4.x leak-line rule
    "tests/unit/test_pii_filter.py",  # CP4.x log filter
    "tests/unit/test_seed.py",  # CP3.x seed
}
EVAL_LISTS = ("eval/model_check.json", "eval/abstention.json")


def _heldout() -> set[str]:
    split = json.loads((ROOT / "eval" / "split.json").read_text())
    return set(split["heldout"]["labelled"]) | set(split["heldout"]["tricky"])


def test_no_heldout_ids_in_tests_or_eval_lists() -> None:
    held = _heldout()
    files = [p for p in (ROOT / "tests").rglob("*") if p.suffix in (".py", ".yaml", ".json")]
    files += [ROOT / p for p in EVAL_LISTS]
    leaks = {}
    for path in files:
        rel = path.relative_to(ROOT).as_posix()
        if rel in ALLOWED:
            continue
        ids = set(re.findall(r"INC-\d{5}", path.read_text())) & held
        if ids:
            leaks[rel] = sorted(ids)
    assert leaks == {}


def test_eval_lists_hold_only_tune_ids() -> None:
    split = json.loads((ROOT / "eval" / "split.json").read_text())
    tune = set(split["tune"]["labelled"])
    check = json.loads((ROOT / "eval" / "model_check.json").read_text())
    ids = check["group_a"] + check["mixed"]
    assert len(ids) == 40 and len(set(ids)) == 40 and set(ids) <= tune
    abst = json.loads((ROOT / "eval" / "abstention.json").read_text())["tickets"]
    assert len(abst) == 20 and set(abst) <= tune
