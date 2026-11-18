"""Index step 6: document metadata (S6 step 1; rag-design.md section 4, step 6).

Categories come from the document's content (its title), never its file name
(A7). The result is checked against `expected_metadata.yaml`, which encodes the
A8 and A10 tables; any mismatch fails the run.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import cache
from importlib import resources
from typing import Any

import yaml

from support_agent.mcp.knowledge.tokenizer import is_version, version_form

DOC_TYPES = {"runbooks": "runbook", "sop": "sop", "faq": "faq", "system-specs": "spec"}

# Title keyword -> category (A7, A8). Order is the order categories are listed in.
CATEGORY_RULES: tuple[tuple[str, str], ...] = (
    ("POS", r"\bPOS\b|FoodTech|OrbitPOS"),
    ("Printers", r"printer"),
    ("Network", r"network|wi-?fi|\bVPN\b|router|bandwidth"),
    ("Online Orders", r"online orders|aggregator|zomato|swiggy"),
    ("Soft Serve", r"soft serve|creamtech|frostypro"),
    ("Kiosks", r"kiosk"),
    ("Payment", r"payment|PIN pad"),
    ("Scanner", r"scanner"),
    ("KDS", r"\bKDS\b"),
)
FAMILY = {
    "POS": "pos",
    "Printers": "printer",
    "Network": "network",
    "Online Orders": "online_orders",
    "Soft Serve": "soft_serve",
    "Kiosks": "kiosk",
    "Payment": "payment",
    "Scanner": "pos",
    "KDS": "online_orders",
}
FAMILIES = frozenset(FAMILY.values())


@dataclass
class DocMeta:
    doc_id: str
    doc_type: str
    title: str
    categories: list[str]
    device_family: list[str]
    covered_systems: list[dict[str, Any]] = field(default_factory=list)
    version_issues: list[dict[str, Any]] = field(default_factory=list)
    revision: str | None = None
    last_updated: str | None = None


def doc_type_of(doc_id: str) -> str:
    folder = doc_id.split("/", 1)[0]
    if folder not in DOC_TYPES:
        raise ValueError(f"{doc_id}: unknown KB folder {folder}")
    return DOC_TYPES[folder]


def title_of(text: str) -> str:
    m = re.search(r"^#\s+(.+?)\s*$", text, re.M)
    return m.group(1).strip() if m else ""


def categories_of(title: str) -> list[str]:
    return [cat for cat, rule in CATEGORY_RULES if re.search(rule, title, re.I)]


def families_of(categories: list[str]) -> list[str]:
    return list(dict.fromkeys(FAMILY[c] for c in categories))


def _section_body(text: str, heading: str) -> str:
    m = re.search(
        rf"^##\s+{re.escape(heading)}[^\n]*\n(?P<body>.*?)(?=^##\s|\Z)", text, re.M | re.S
    )
    return m.group("body") if m else ""


def covered_systems(doc_type: str, title: str, text: str) -> list[dict[str, Any]]:
    """Runbooks: one entry per "Affected Systems" bullet with the versions it names.
    Specs: the product in the title with every version the spec names."""
    found: list[dict[str, Any]] = []
    if doc_type == "runbook":
        for line in _section_body(text, "Affected Systems").splitlines():
            m = re.match(r"^\s*[-*]\s+(?:\*\*(?P<label>[^*]+?):?\*\*:?)?\s*(?P<text>.+)$", line)
            if not m:
                continue
            body = m.group("text").strip()
            versions = [
                version_form(v)
                for v in re.findall(r"[vV]?\d+(?:\.(?:\d+|[xX]))+", body)
                if is_version(v)
            ]
            found.append(
                {"label": (m.group("label") or "").strip(), "text": body, "versions": versions}
            )
    elif doc_type == "spec":
        versions = [version_form(v) for v in re.findall(r"\b[vV]\d+(?:\.(?:\d+|[xX]))+", text)]
        found.append({"label": "Product", "text": title, "versions": list(dict.fromkeys(versions))})
    return found


def revision_info(text: str) -> tuple[str | None, str | None]:
    """(revision, last_updated) from the Revision History table's newest row, or the
    `Version` / `Last Updated` lines."""
    hist = _section_body(text, "Revision History")
    rows = [
        [c.strip() for c in ln.strip().strip("|").split("|")]
        for ln in hist.splitlines()
        if ln.strip().startswith("|")
    ]
    data = [r for r in rows[2:] if len(r) >= 2 and re.match(r"v?\d", r[0])]
    if data:
        newest = max(data, key=lambda r: r[1])
        return newest[0], newest[1]
    version = re.search(r"\*\*(?:Document )?Version:?\*\*:?\s*([vV]?\d[^\s|]*)", text)
    updated = re.search(r"\*\*Last Updated:?\*\*:?\s*([^|\n]+?)\s*(?:\||$)", text, re.M)
    return (
        version.group(1) if version else None,
        updated.group(1).strip() if updated else None,
    )


@cache
def expected() -> dict[str, Any]:
    text = resources.files("support_agent.kb").joinpath("expected_metadata.yaml").read_text()
    data: dict[str, Any] = yaml.safe_load(text)
    return data


def build(doc_id: str, text: str) -> DocMeta:
    doc_type = doc_type_of(doc_id)
    title = title_of(text)
    cats = categories_of(title)
    revision, updated = revision_info(text)
    exp = expected()["documents"].get(doc_id, {})
    return DocMeta(
        doc_id=doc_id,
        doc_type=doc_type,
        title=title,
        categories=cats,
        device_family=families_of(cats),
        covered_systems=covered_systems(doc_type, title, text),
        version_issues=list(exp.get("version_issues", [])),
        revision=revision,
        last_updated=updated,
    )


def mismatches(metas: list[DocMeta]) -> list[str]:
    """Differences from the A7-A10 tables; any one fails the run."""
    exp = expected()["documents"]
    out: list[str] = []
    seen = {m.doc_id for m in metas}
    for doc_id in sorted(set(exp) - seen):
        out.append(f"{doc_id}: expected but not in the KB")
    for m in metas:
        e = exp.get(m.doc_id)
        if e is None:
            out.append(f"{m.doc_id}: no expected metadata (add it to expected_metadata.yaml)")
            continue
        if m.doc_type != e["doc_type"]:
            out.append(f"{m.doc_id}: doc_type {m.doc_type} != {e['doc_type']}")
        if sorted(m.categories) != sorted(e["categories"]):
            out.append(f"{m.doc_id}: categories {m.categories} != {e['categories']}")
        if sorted(m.device_family) != sorted(e["device_family"]):
            out.append(f"{m.doc_id}: device_family {m.device_family} != {e['device_family']}")
        if not m.title:
            out.append(f"{m.doc_id}: no title")
    return out
