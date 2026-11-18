"""The fixed eval split (D39; S3 build step 5).

220 labelled tickets -> tune 110 + held-out 110, stratified by (category,
should_escalate); 36 tricky tickets -> 18 + 18 stratified by `chaos_type`.

Within a stratum the ids are sorted, shuffled with one seeded RNG, and halved.
The odd one left in an odd-sized stratum goes to tune, then held-out, then
tune ... in sorted stratum order, so each cohort splits exactly in half when it
has an even number of odd strata (true for both cohorts).

The labels file holds no category: the ticket's own `category` (train_index)
is used. Miscategorized tickets are all unlabelled tricky ones, so for a
labelled ticket the ticket category is the correct one.
"""

from __future__ import annotations

import hashlib
import json
import random
from collections import Counter, defaultdict
from collections.abc import Hashable, Mapping, Sequence
from typing import Any

SEED = 20261118
HALVES = ("tune", "heldout")
COHORTS = ("labelled", "tricky")


class SplitError(ValueError):
    """The inputs or the split break a split rule."""


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _stratified[K: Hashable](
    strata: Mapping[K, Sequence[str]], rng: random.Random, key_order: Sequence[K]
) -> tuple[list[str], list[str]]:
    tune: list[str] = []
    heldout: list[str] = []
    odd_seen = 0
    for key in key_order:
        ids = sorted(strata[key])
        rng.shuffle(ids)
        half = len(ids) // 2
        tune += ids[:half]
        heldout += ids[half : 2 * half]
        if len(ids) % 2:
            (tune if odd_seen % 2 == 0 else heldout).append(ids[-1])
            odd_seen += 1
    return sorted(tune), sorted(heldout)


def make_split(
    index_rows: Sequence[Mapping[str, Any]],
    labels: Sequence[Mapping[str, Any]],
    *,
    seed: int,
    labels_sha256: str,
    index_sha256: str,
) -> dict[str, Any]:
    """Build the split document from cleaned train_index rows and the labels."""
    by_id = {row["ticket_id"]: row for row in index_rows}
    if len(by_id) != len(index_rows):
        raise SplitError("duplicate ticket_id in train_index")
    label_ids = {label["ticket_id"] for label in labels}
    if len(label_ids) != len(labels):
        raise SplitError("duplicate ticket_id in labels")
    if not label_ids <= by_id.keys():
        raise SplitError(f"labels for unknown tickets: {sorted(label_ids - by_id.keys())}")
    tricky_ids = {tid for tid, row in by_id.items() if row["chaos_type"]}
    if label_ids & tricky_ids:
        raise SplitError(f"tricky tickets with labels: {sorted(label_ids & tricky_ids)}")
    if label_ids | tricky_ids != by_id.keys():
        missing = sorted(by_id.keys() - label_ids - tricky_ids)
        raise SplitError(f"tickets neither labelled nor tricky: {missing}")

    labelled: dict[tuple[str, bool], list[str]] = defaultdict(list)
    for label in labels:
        tid = label["ticket_id"]
        labelled[(by_id[tid]["category"], bool(label["should_escalate"]))].append(tid)
    tricky: dict[str, list[str]] = defaultdict(list)
    for tid in tricky_ids:
        tricky[by_id[tid]["chaos_type"]].append(tid)

    rng = random.Random(seed)  # noqa: S311 - a reproducible split, not a secret
    lab_tune, lab_held = _stratified(labelled, rng, sorted(labelled))
    trk_tune, trk_held = _stratified(tricky, rng, sorted(tricky))
    return {
        "seed": seed,
        "labels_sha256": labels_sha256,
        "index_sha256": index_sha256,
        "tune": {"labelled": lab_tune, "tricky": trk_tune},
        "heldout": {"labelled": lab_held, "tricky": trk_held},
    }


def dumps(split: Mapping[str, Any]) -> bytes:
    """The one byte form of a split file (sorted keys, 2-space indent, final newline)."""
    return (json.dumps(split, indent=2, sort_keys=True) + "\n").encode("utf-8")


def rows(split: Mapping[str, Any]) -> list[tuple[str, str, str]]:
    """(ticket_id, half, cohort) for every ticket in the split."""
    return [
        (tid, half, cohort) for half in HALVES for cohort in COHORTS for tid in split[half][cohort]
    ]


def summary(
    split: Mapping[str, Any],
    index_rows: Sequence[Mapping[str, Any]],
    labels: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Per half: counts, category shares and escalate share (labelled), trick types."""
    by_id = {row["ticket_id"]: row for row in index_rows}
    escalate = {label["ticket_id"]: bool(label["should_escalate"]) for label in labels}
    out: dict[str, dict[str, Any]] = {}
    groups = {"all": (list(escalate), [t for t, r in by_id.items() if r["chaos_type"]])}
    for half in HALVES:
        groups[half] = (split[half]["labelled"], split[half]["tricky"])
    for name, (lab, trk) in groups.items():
        cats = Counter(by_id[t]["category"] for t in lab)
        out[name] = {
            "labelled": len(lab),
            "tricky": len(trk),
            "category_share": {c: cats[c] / len(lab) for c in sorted(cats)},
            "escalate_share": sum(escalate[t] for t in lab) / len(lab),
            "chaos_types": dict(sorted(Counter(by_id[t]["chaos_type"] for t in trk).items())),
        }
    return out
