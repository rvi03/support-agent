"""Index step 9: the conflict register and conflict ids on sections (rag-design.md section 9).

The register is `conflicts.yaml` (code, versioned; no sign-off, D38). Each row's
`attach` rules put its id on the sections that hold its claim, so search
results and the Resolver see it (D17).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from importlib import resources
from typing import Any

import yaml


@dataclass(frozen=True)
class Conflict:
    conflict_id: str
    topic: str
    resolution: str
    docs: list[str]
    claims: dict[str, str]
    affects: dict[str, Any]
    attach: dict[str, re.Pattern[str]]


def register_text() -> str:
    return resources.files("support_agent.kb").joinpath("conflicts.yaml").read_text()


def load(text: str | None = None) -> tuple[str, list[Conflict]]:
    data = yaml.safe_load(text if text is not None else register_text())
    rows: list[Conflict] = []
    for row in data["conflicts"]:
        if row["resolution"] not in ("flag_and_handoff", "sop_wins"):
            raise ValueError(f"{row['id']}: bad resolution {row['resolution']}")
        rows.append(
            Conflict(
                conflict_id=row["id"],
                topic=row["topic"],
                resolution=row["resolution"],
                docs=list(row["claims"]),
                claims=dict(row["claims"]),
                affects=dict(row.get("affects", {})),
                attach={doc: re.compile(rx) for doc, rx in row.get("attach", {}).items()},
            )
        )
    ids = [r.conflict_id for r in rows]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate conflict ids")
    return str(data["version"]), rows


def ids_for(doc_id: str, text: str, rows: list[Conflict]) -> list[str]:
    return [r.conflict_id for r in rows if doc_id in r.attach and r.attach[doc_id].search(text)]
