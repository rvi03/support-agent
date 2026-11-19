"""Index step 6 (S6): metadata from document content only (S8a: no hand-written list)."""

from __future__ import annotations

import pytest

from support_agent.kb import metadata
from tests.kb_data import kb_files

pytestmark = pytest.mark.unit


def test_every_real_document_gets_type_category_and_family() -> None:
    metas = [metadata.build(d, t) for d, t in kb_files().items()]
    assert len(metas) == 48  # every markdown document in the KB
    assert all(m.doc_type and m.title for m in metas)
    runbooks = [m for m in metas if m.doc_type == "runbook"]
    assert all(m.categories and m.device_family for m in runbooks)


def test_categories_come_from_the_title_not_the_file_name() -> None:
    meta = metadata.build("runbooks/printer-offline.md", "# POS Barcode Scanner Not Reading\n")
    assert meta.categories == ["POS", "Scanner"] and meta.device_family == ["pos"]


def test_revision_and_covered_systems() -> None:
    meta = metadata.build("runbooks/printer-offline.md", kb_files()["runbooks/printer-offline.md"])
    assert (meta.revision, meta.last_updated) == ("1.2", "2025-09-15")
    assert any("v8.x" in s["versions"] for s in meta.covered_systems)
