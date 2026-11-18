"""KB facts read from the local dataset for the S6 tests (read-only, no services)."""

from __future__ import annotations

import csv
import os
import re
from functools import cache
from pathlib import Path

import pytest

from support_agent.kb.codes import table_codes

ROOT = Path(__file__).resolve().parents[1]
DATASET = (ROOT / os.environ.get("DATASET_DIR", "../../references/assignment/dataset")).resolve()
KB = DATASET / "kb"


@cache
def error_table_codes() -> dict[str, set[str]]:
    """doc_id -> codes in the KB error tables (see support_agent.kb.codes)."""
    return table_codes(kb_files())


def kb_files() -> dict[str, str]:
    if not KB.is_dir():
        pytest.fail(f"KB not found at {KB}")
    return {p.relative_to(KB).as_posix(): p.read_text() for p in sorted(KB.rglob("*.md"))}


@cache
def asset_versions() -> set[str]:
    """Every version in assets.csv `system_version` (v4.2.1, 15.2.1, ...)."""
    with (DATASET / "data" / "assets.csv").open() as f:
        values = {row["system_version"] for row in csv.DictReader(f)}
    return {v for value in values for v in re.findall(r"[vV]?\d+(?:\.\d+)+", value)}
