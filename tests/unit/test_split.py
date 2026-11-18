"""CP3.5: the committed split is right, balanced and reproducible.

Reads the local dataset (DATASET_DIR, read-only); no services needed.
"""

from __future__ import annotations

import json
import random
from functools import cache
from pathlib import Path
from typing import Any

import pytest

from support_agent.ingest import csv_clean, split

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "../../references/assignment/dataset"
SPLIT_FILE = ROOT / "eval" / "split.json"
TOLERANCE = 0.05


@cache
def _inputs() -> tuple[list[dict[str, Any]], list[dict[str, Any]], str, str]:
    if not DATASET.is_dir():
        pytest.fail(f"Dataset not found at {DATASET}")
    index_bytes = (DATASET / "tickets/train_index.csv").read_bytes()
    labels_bytes = (DATASET / "labels/train_labels.json").read_bytes()
    return (
        csv_clean.parse_ticket_index(index_bytes.decode("utf-8")),
        json.loads(labels_bytes),
        split.sha256_hex(labels_bytes),
        split.sha256_hex(index_bytes),
    )


def _build(seed: int = split.SEED) -> dict[str, Any]:
    index_rows, labels, labels_sha, index_sha = _inputs()
    return split.make_split(
        index_rows, labels, seed=seed, labels_sha256=labels_sha, index_sha256=index_sha
    )


def _committed() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(SPLIT_FILE.read_bytes())
    return data


def test_committed_file_is_the_seeded_split_byte_for_byte() -> None:
    assert split.dumps(_build()) == SPLIT_FILE.read_bytes()
    assert _committed()["seed"] == split.SEED == 20261118


def test_same_seed_same_bytes_other_seed_other_split() -> None:
    assert split.dumps(_build()) == split.dumps(_build())
    assert _build(seed=1)["tune"] != _build()["tune"]


def test_counts() -> None:
    s = _committed()
    assert [len(s[h][c]) for h in split.HALVES for c in split.COHORTS] == [110, 18, 110, 18]


def test_four_cohorts_partition_the_256_tickets() -> None:
    index_rows, labels, _, _ = _inputs()
    ids = [t for t, _, _ in split.rows(_committed())]
    assert len(ids) == len(set(ids)) == 256
    assert set(ids) == {row["ticket_id"] for row in index_rows}
    s = _committed()
    assert not set(s["tune"]["labelled"] + s["tune"]["tricky"]) & set(
        s["heldout"]["labelled"] + s["heldout"]["tricky"]
    )
    labelled = set(s["tune"]["labelled"] + s["heldout"]["labelled"])
    assert labelled == {label["ticket_id"] for label in labels}


def test_shares_within_5_points_of_the_full_set() -> None:
    index_rows, labels, _, _ = _inputs()
    info = split.summary(_committed(), index_rows, labels)
    full = info["all"]
    for half in split.HALVES:
        for category, share in full["category_share"].items():
            got = info[half]["category_share"].get(category, 0.0)
            assert abs(got - share) <= TOLERANCE, (half, category, got, share)
        assert abs(info[half]["escalate_share"] - full["escalate_share"]) <= TOLERANCE, half


def test_every_trick_type_is_in_both_halves() -> None:
    index_rows, labels, _, _ = _inputs()
    info = split.summary(_committed(), index_rows, labels)
    assert set(info["tune"]["chaos_types"]) == set(info["all"]["chaos_types"])
    assert set(info["heldout"]["chaos_types"]) == set(info["all"]["chaos_types"])


def test_labels_hash_is_recorded() -> None:
    _, _, labels_sha, index_sha = _inputs()
    assert _committed()["labels_sha256"] == labels_sha
    assert _committed()["index_sha256"] == index_sha


def _index(tid: str, category: str = "POS", chaos: str | None = None) -> dict[str, Any]:
    return {"ticket_id": tid, "category": category, "chaos_type": chaos}


@pytest.mark.parametrize(
    ("index_rows", "labels", "message"),
    [
        ([_index("A"), _index("A")], [], "duplicate ticket_id in train_index"),
        ([_index("A")], [{"ticket_id": "A"}, {"ticket_id": "A"}], "duplicate ticket_id in labels"),
        ([_index("A")], [{"ticket_id": "B"}], "unknown tickets"),
        ([_index("A", chaos="vague")], [{"ticket_id": "A"}], "tricky tickets with labels"),
        ([_index("A"), _index("B")], [{"ticket_id": "A"}], "neither labelled nor tricky"),
    ],
)
def test_bad_inputs_are_refused(
    index_rows: list[dict[str, Any]], labels: list[dict[str, Any]], message: str
) -> None:
    with pytest.raises(split.SplitError, match=message):
        split.make_split(index_rows, labels, seed=1, labels_sha256="x", index_sha256="y")


def test_odd_strata_alternate() -> None:
    tune, held = split._stratified(
        {"a": ["1", "2", "3"], "b": ["4", "5", "6"]},
        random.Random(0),  # noqa: S311
        ["a", "b"],
    )
    assert len(tune) == len(held) == 3
