"""Index step 6 (S6): metadata from content, checked against A7-A10; conflict register."""

from __future__ import annotations

import pytest

from support_agent.kb import conflicts, metadata
from tests.kb_data import kb_files

pytestmark = pytest.mark.unit


def test_real_kb_matches_a7_to_a10() -> None:
    metas = [metadata.build(d, t) for d, t in kb_files().items()]
    assert metadata.mismatches(metas) == []
    assert sum(len(m.version_issues) for m in metas) == 10


def test_categories_come_from_the_title_not_the_file_name() -> None:
    meta = metadata.build("runbooks/printer-offline.md", "# POS Barcode Scanner Not Reading\n")
    assert meta.categories == ["POS", "Scanner"] and meta.device_family == ["pos"]


def test_a_changed_document_fails_the_check() -> None:
    files = kb_files()
    metas = [metadata.build(d, t) for d, t in files.items()]
    metas[0] = metadata.build(metas[0].doc_id, "# Kiosk Printer Notes\n")
    assert metadata.mismatches(metas)


def test_revision_and_covered_systems() -> None:
    meta = metadata.build("runbooks/printer-offline.md", kb_files()["runbooks/printer-offline.md"])
    assert (meta.revision, meta.last_updated) == ("1.2", "2025-09-15")
    assert any("v8.x" in s["versions"] for s in meta.covered_systems)


def test_register_loads_and_every_rule_hits_its_document() -> None:
    version, rows = conflicts.load()
    assert version and len(rows) == 20
    files = kb_files()
    for row in rows:
        assert row.resolution in ("flag_and_handoff", "sop_wins")
        for doc_id, rx in row.attach.items():
            assert rx.search(files[doc_id]), (row.conflict_id, doc_id)
    sop_wins = {r.conflict_id for r in rows if r.resolution == "sop_wins"}
    assert sop_wins == {"A14", "A15", "A16", "A29.3"}


def test_duplicate_conflict_id_is_refused() -> None:
    text = conflicts.register_text().replace("id: A13", "id: A12")
    with pytest.raises(ValueError, match="duplicate"):
        conflicts.load(text)
