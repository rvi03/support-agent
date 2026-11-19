"""S14 revision and resume suite (step 8): a KB reindex during a pause hands the walk
off as `kb_rev_changed` before anything is dispatched (D18)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from support_agent.agent.nodes import resolver
from support_agent.agent.state import WalkState

pytestmark = pytest.mark.unit

PO = "runbooks/printer-offline.md"


class Kb:
    def __init__(self, rev: str) -> None:
        self.rev = rev
        self.calls = 0

    async def get_document(self, doc_id: str) -> Any:
        self.calls += 1
        return SimpleNamespace(status="found", document=SimpleNamespace(doc_id=doc_id),
                               kb_rev=self.rev)  # fmt: skip


def _run(walk_rev: str, published: str) -> tuple[Any, str | None]:
    state = SimpleNamespace(walk=WalkState(runbook_id=PO, kb_rev=walk_rev))
    ctx = SimpleNamespace(kb=Kb(published))
    return asyncio.run(resolver._runbook(state, ctx))  # type: ignore[arg-type]


def test_reindex_during_a_pause_hands_off() -> None:
    doc, reason = _run("kb-before", "kb-after")
    assert doc is None
    assert reason == "kb_rev_changed"


def test_same_revision_continues() -> None:
    doc, reason = _run("kb-same", "kb-same")
    assert reason is None and doc is not None
