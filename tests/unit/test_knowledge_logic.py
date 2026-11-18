"""Knowledge server logic with no services (S6): RRF, roll-up, code promotion, budget,
run-scoped exclusions."""

from __future__ import annotations

import asyncio
import uuid

import pytest

from support_agent.mcp.base.server import _CALL, CallContext
from support_agent.mcp.knowledge import search
from support_agent.mcp.knowledge.server import Knowledge, kb_tokens
from support_agent.mcp.knowledge.state import MemoryStore, budget_key

pytestmark = pytest.mark.unit


def test_rrf_adds_both_lists() -> None:
    hits = search.fuse(
        {"bm25": [("a#1", "a"), ("b#1", "b")], "vector": [("b#1", "b"), ("c#1", "c")]}
    )
    assert hits["b#1"].score == pytest.approx(1 / 62 + 1 / 61)
    assert hits["a#1"].score == pytest.approx(1 / 61)
    assert hits["b#1"].ranks == {"bm25": 2, "vector": 1}


def test_roll_up_section_first_and_promotion_wins() -> None:
    hits = search.fuse({"bm25": [("a#1", "a"), ("a#2", "a"), ("b#1", "b"), ("c#1", "c")]})
    docs = search.roll_up(hits, 3, "section")
    assert [d.doc_id for d in docs] == ["a", "b", "c"]
    hits["c#1"].promoted = True
    docs = search.roll_up(hits, 2, "section")
    assert [d.doc_id for d in docs] == ["c", "a"]
    assert docs[1].sections[0].section_id == "a#1"


def test_document_first_sums_top_sections() -> None:
    hits = search.fuse({"bm25": [("a#1", "a"), ("b#1", "b"), ("b#2", "b"), ("b#3", "b")]})
    assert [d.doc_id for d in search.roll_up(hits, 2, "section")][0] == "a"
    assert [d.doc_id for d in search.roll_up(hits, 2, "document")][0] == "b"


def test_where_clause_holds_every_filter() -> None:
    params: dict[str, object] = {}
    where = search._where(
        search.Filters("runbook", "printer", "Printers", ("runbooks/x.md",)), params
    )
    assert "doc_type" in where and "device_family &&" in where and "categories" in where
    assert "NOT (doc_id = ANY" in where and params["excl"] == ["runbooks/x.md"]


def _with_call(
    run_id: uuid.UUID | None, ticket: str | None, client: str = "agent-reader"
) -> object:
    return _CALL.set(CallContext(client, ticket, run_id))


def test_budget_is_per_run_and_ticket_and_refuses_over_limit() -> None:
    kn = Knowledge(MemoryStore(), None, budget=100)
    run = uuid.uuid4()

    async def go() -> list[tuple[bool, int]]:
        token = _with_call(run, "INC-1")
        try:
            out = [await kn.charge(60), await kn.charge(50)]  # second would pass 100
        finally:
            _CALL.reset(token)  # type: ignore[arg-type]
        token = _with_call(run, "INC-2")
        try:
            out.append(await kn.charge(60))  # another ticket: its own budget
        finally:
            _CALL.reset(token)  # type: ignore[arg-type]
        return out

    assert asyncio.run(go()) == [(True, 60), (False, 60), (True, 60)]
    assert budget_key(None, None) is None
    assert kb_tokens("x" * 9) == 3


def test_exclusions_apply_only_to_their_run() -> None:
    store = MemoryStore()
    kn = Knowledge(store, None, budget=100)
    run_a, run_b = uuid.uuid4(), uuid.uuid4()

    async def go() -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
        await store.add_exclusions(run_a, ["runbooks/printer-offline.md"])
        results = []
        for run in (run_a, run_b, None):
            token = _with_call(run, "INC-1")
            try:
                results.append(await kn.excluded())
            finally:
                _CALL.reset(token)  # type: ignore[arg-type]
        return results[0], results[1], results[2]

    a, b, none = asyncio.run(go())
    assert a == ("runbooks/printer-offline.md",)
    assert b == () and none == ()


def test_snippet_is_flat_and_bounded() -> None:
    assert search.snippet("a\n\n b") == "a b"
    long = search.snippet("word " * 200)
    assert len(long) == search.SNIPPET_CHARS and long.endswith("…")
