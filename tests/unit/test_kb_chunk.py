"""Index step 7 (S6): sections and chunks."""

from __future__ import annotations

import pytest

from support_agent.kb import chunk, clean, metadata
from tests.kb_data import kb_files

pytestmark = pytest.mark.unit


def words(text: str) -> int:
    return len(text.split())


def test_headings_bold_steps_and_fences() -> None:
    text = (
        "# Title\n\nIntro line.\n\n## Overview\n\nAbout it.\n\n## L1 Diagnosis Steps\n\n"
        "### For USB Printers\n\n**Step 1: Check cable**\n\n1. Reseat it.\n\n"
        "**Step 2: Check power**\n\n```bash\n# not a heading\nsudo ls\n```\n"
    )
    title, secs = chunk.sections("runbooks/x.md", "runbook", text, count=words)
    assert title == "Title"
    assert [s.path for s in secs] == [
        "Introduction",
        "Overview",
        "L1 Diagnosis Steps > For USB Printers > Step 1: Check cable",
        "L1 Diagnosis Steps > For USB Printers > Step 2: Check power",
    ]
    assert "# not a heading" in secs[-1].text
    assert secs[1].index_text.startswith("Title > Overview\n")
    assert len({s.section_id for s in secs}) == len(secs)


def test_faq_one_question_per_chunk() -> None:
    text = "# FAQ\n\n## General\n\n**Q: One?**\nA: Yes.\n\n**Q: Two?**\nA: No.\n"
    _, secs = chunk.sections("faq/x.md", "faq", text, count=words)
    assert [s.path for s in secs] == ["General > Q: One?", "General > Q: Two?"]


def test_oversized_section_splits_with_parent_and_table_header() -> None:
    rows = "".join(f"| E{n:02d} | meaning number {n} here |\n" for n in range(40))
    text = f"# Spec\n\n## Codes\n\n| Code | Meaning |\n|---|---|\n{rows}"
    _, secs = chunk.sections("system-specs/x.md", "spec", text, budget=60, count=words)
    assert len(secs) > 1
    assert {s.parent_section_id for s in secs} == {"system-specs/x.md#codes"}
    for s in secs:
        assert "| Code | Meaning |\n|---|---|\n| E" in s.text
        assert s.token_count <= 60
    assert sum(s.text.count("| E") for s in secs) == 40


def test_count_includes_the_prefix() -> None:
    text = "# A Long Title Here\n\n## Section\n\none two three\n"
    _, (sec,) = chunk.sections("faq/x.md", "faq", text, count=words)
    assert sec.token_count == words(sec.index_text) > words(sec.text)


def test_real_kb_fits_the_budget_with_tiktoken() -> None:
    total = 0
    for doc_id, text in kb_files().items():
        doc_type = metadata.doc_type_of(doc_id)
        _, secs = chunk.sections(doc_id, doc_type, clean.strip_table_padding(text))
        assert secs, doc_id
        assert all(s.token_count <= chunk.CHUNK_BUDGET for s in secs), doc_id
        total += len(secs)
    assert total > 500
