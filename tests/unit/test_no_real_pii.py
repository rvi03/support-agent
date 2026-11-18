"""No real personal data anywhere in the repo: tests, fixtures, docs, code, comments.

Every name and phone the dataset holds (submitters, contact phones, L1 staff
in ticket histories, region managers, store phones) is read from DATASET_DIR
and searched for in every tracked or new file. Tests and examples must use
obviously fake values instead, e.g. "Testa Mockwell", "+91-90000-00001".
"""

from __future__ import annotations

import csv
import json
import os
import re
import subprocess
from functools import cache
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
DATASET = (ROOT / os.environ.get("DATASET_DIR", "../../references/assignment/dataset")).resolve()
SKIP_SUFFIXES = {".lock"}
_ACTOR_RE = re.compile(r"^L\d\s+Agent\s*-\s*(?P<name>\S.*)$")


def _last10(phone: str) -> str:
    return re.sub(r"\D", "", phone)[-10:]


@cache
def real_values() -> tuple[frozenset[str], frozenset[str]]:
    names: set[str] = set()
    phones: set[str] = set()
    with (DATASET / "data/stores.csv").open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            names.add(row["region_manager"].strip())
            phones.add(_last10(row["support_phone"]))
    for path in (DATASET / "tickets/train").glob("*.json"):
        ticket = json.loads(path.read_text(encoding="utf-8"))
        if ticket.get("submitted_by"):
            names.add(ticket["submitted_by"].strip())
        if ticket.get("contact_phone"):
            phones.add(_last10(ticket["contact_phone"]))
        for entry in ticket.get("ticket_history") or []:
            m = _ACTOR_RE.match(str(entry.get("actor") or "").strip())
            if m:
                names.add(m.group("name").strip())
    return frozenset(n for n in names if n), frozenset(p for p in phones if len(p) == 10)


def repo_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split("\n")
    return [ROOT / f for f in out if f and Path(f).suffix not in SKIP_SUFFIXES]


def find_real_pii(text: str, names: frozenset[str], phones: frozenset[str]) -> list[str]:
    """`kind:line` for every real name (whole words, any case) or phone (any separators)."""
    found = []
    name_re = re.compile(
        r"(?<![\w-])(?:"
        + "|".join(r"\s+".join(map(re.escape, n.split())) for n in sorted(names, key=len)[::-1])
        + r")(?![\w-])",
        re.IGNORECASE,
    )
    for i, line in enumerate(text.splitlines(), 1):
        if name_re.search(line):
            found.append(f"name:{i}")
        digits = re.sub(r"[\s().+-]", "", line)
        if any(p in digits for p in phones):
            found.append(f"phone:{i}")
    return found


@pytest.fixture(scope="module")
def values() -> tuple[frozenset[str], frozenset[str]]:
    if not (DATASET / "data/stores.csv").is_file():
        pytest.skip(f"dataset not found at {DATASET}")
    names, phones = real_values()
    assert len(names) > 100 and len(phones) > 100  # the dataset was really read
    return names, phones


def test_no_real_name_or_phone_in_any_repo_file(
    values: tuple[frozenset[str], frozenset[str]],
) -> None:
    names, phones = values
    leaks = []
    for path in repo_files():
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        # The value is never printed, only where it is.
        leaks += [f"{path.relative_to(ROOT)} {hit}" for hit in find_real_pii(text, names, phones)]
    assert leaks == [], "real personal data in the repo; use mock values:\n" + "\n".join(leaks)


def test_the_scan_catches_a_planted_value(
    values: tuple[frozenset[str], frozenset[str]],
) -> None:
    names, phones = values
    name, phone = sorted(names)[0], sorted(phones)[0]
    spaced = f"{phone[:5]} {phone[5:]}"
    assert find_real_pii(f"x\nhello {name.upper()}\ncall {spaced}", names, phones) == [
        "name:2",
        "phone:3",
    ]
    assert find_real_pii("Testa Mockwell +91-90000-00001", names, phones) == []
