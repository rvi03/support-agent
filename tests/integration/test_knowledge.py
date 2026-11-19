"""knowledge MCP server against the running platform (S6: CP6.3, CP6.4).

Calls go through the agent-side client with real Keycloak tokens, so each call
also passes the JWT check, the scope, OPA P7 and the audit write.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest

from support_agent.agent.tools import McpToolClient, TokenSource, ToolCallError
from support_agent.kb import metadata
from support_agent.mcp.base.errors import ErrorCode
from support_agent.mcp.knowledge import tokenizer
from tests.integration.platform_env import load_env, superuser_url
from tests.kb_data import error_table_codes

pytestmark = pytest.mark.integration

ISSUER = "http://localhost:8080/realms/servewell"
URL = "http://localhost:8102/mcp"
DOC = "runbooks/printer-offline.md"


@pytest.fixture(scope="module")
def env() -> dict[str, str]:
    return load_env()


@pytest.fixture(scope="module")
def db(env: dict[str, str]) -> Iterator[psycopg.Connection[Any]]:
    with psycopg.connect(superuser_url(env), autocommit=True) as conn:
        yield conn


def client(env: dict[str, str], who: str = "agent-reader") -> McpToolClient:
    secret = {
        "agent-reader": env["KEYCLOAK_SECRET_AGENT_READER"],
        "agent-actor": env["KEYCLOAK_SECRET_AGENT_ACTOR"],
        "eval-runner": env["KEYCLOAK_SECRET_EVAL_RUNNER"],
    }[who]
    return McpToolClient(URL, TokenSource(ISSUER, who, secret), lambda data, _t: data)


def call(c: McpToolClient, tool: str, run: uuid.UUID | None = None, **args: Any) -> Any:
    """`run` goes in the request _meta (a fresh one per call unless given, so the per-run
    KB budget never carries over); tool arguments (even one named run_id) go in args."""
    return asyncio.run(c.call(tool, args, ticket_id="INC-TEST", run_id=run or uuid.uuid4()))


def families(db: psycopg.Connection[Any]) -> dict[str, list[str]]:
    return dict(db.execute("SELECT doc_id, device_family FROM kb.documents").fetchall())


def audit_since(db: psycopg.Connection[Any], since: int) -> list[tuple[Any, ...]]:
    return db.execute(
        "SELECT actor, action, result, reason FROM audit.events "
        "WHERE id > %s AND step = 'mcp.knowledge' ORDER BY id",
        (since,),
    ).fetchall()


def last_audit_id(db: psycopg.Connection[Any]) -> int:
    return int(db.execute("SELECT coalesce(max(id), 0) FROM audit.events").fetchone()[0])  # type: ignore[index]


# ---- CP6.3 filters, scope, exclusions -------------------------------------------------------


def test_doc_type_filter_returns_only_sops(env: dict[str, str]) -> None:
    out = call(client(env), "search_kb", query="escalate to L2 response time", doc_type="sop", k=10)
    assert out["status"] == "found" and out["documents"]
    assert {d["doc_type"] for d in out["documents"]} == {"sop"}


def test_device_family_filter_returns_only_printer_sections(
    env: dict[str, str], db: psycopg.Connection[Any]
) -> None:
    out = call(
        client(env),
        "search_kb",
        query="device offline not responding",
        device_family="printer",
        k=10,
    )
    fams = families(db)
    assert out["documents"]
    for d in out["documents"]:
        assert "printer" in fams[d["doc_id"]], d["doc_id"]
    sids = [s["section_id"] for d in out["documents"] for s in d["sections"]]
    rows = db.execute(
        "SELECT device_family FROM kb.sections WHERE section_id = ANY(%s)", (sids,)
    ).fetchall()
    assert rows and all("printer" in r[0] for r in rows)


def test_get_document_returns_the_whole_sanitized_document(env: dict[str, str]) -> None:
    out = call(client(env), "get_document", doc_id="runbooks/pos-startup-failure.md")
    doc = out["document"]
    assert out["status"] == "found" and doc["truncated"] is True
    assert doc["sections"] and doc["sections"][0]["ord"] == 0
    assert "[missing doc:" in doc["masked_text"]
    assert "conflicts" not in doc and "conflict_ids" not in doc["sections"][0]
    assert call(client(env), "get_document", doc_id="runbooks/no-such.md")["status"] == "not_found"


def test_token_without_kb_read_is_refused_and_audited(
    env: dict[str, str], db: psycopg.Connection[Any]
) -> None:
    since = last_audit_id(db)
    # eval-runner reaches the server (audience knowledge, scope kb:eval) but has no kb:read.
    with pytest.raises(ToolCallError) as exc:
        call(client(env, "eval-runner"), "search_kb", query="printer offline")
    assert exc.value.code is ErrorCode.DENIED
    # agent-actor has no knowledge audience: refused before any tool code.
    with pytest.raises(ToolCallError):
        call(client(env, "agent-actor"), "search_kb", query="printer offline")
    rows = audit_since(db, since)
    assert ("eval-runner", "search_kb", "denied", "missing_scope:kb:read") in rows
    assert any(r[1] == "auth" and r[2] == "denied" for r in rows)


def test_only_eval_runner_registers_exclusions(
    env: dict[str, str], db: psycopg.Connection[Any]
) -> None:
    run = uuid.uuid4()
    since = last_audit_id(db)
    for tool, args in (
        ("register_exclusions", {"run_id": str(run), "doc_ids": [DOC]}),
        ("is_excluded", {"run_id": str(run), "doc_id": DOC}),
    ):
        with pytest.raises(ToolCallError) as exc:
            call(client(env), tool, **args)
        assert exc.value.code is ErrorCode.DENIED
    rows = audit_since(db, since)
    assert [(r[0], r[2]) for r in rows] == [("agent-reader", "denied")] * 2


def test_exclusion_applies_only_to_its_own_run(env: dict[str, str]) -> None:
    run_a, run_b = uuid.uuid4(), uuid.uuid4()
    evaluator, reader = client(env, "eval-runner"), client(env)
    out = call(evaluator, "register_exclusions", run_id=str(run_a), doc_ids=[DOC])
    assert out == {"status": "registered", "run_id": str(run_a), "excluded": [DOC]}
    assert call(evaluator, "is_excluded", run_id=str(run_a), doc_id=DOC)["status"] == "excluded"
    assert call(evaluator, "is_excluded", run_id=str(run_b), doc_id=DOC)["status"] == "not_excluded"
    # Within run A the document is gone from get_document and from search.
    assert call(reader, "get_document", run_a, doc_id=DOC)["status"] == "not_found"
    query = "Epson printer offline USB not detected"
    hit_a = call(reader, "search_kb", run_a, query=query, doc_type="runbook", k=10)
    assert DOC not in [d["doc_id"] for d in hit_a["documents"]]
    # Positive control: another run sees it (Codex §2).
    assert call(reader, "get_document", run_b, doc_id=DOC)["status"] == "found"
    hit_b = call(reader, "search_kb", run_b, query=query, doc_type="runbook", k=10)
    assert hit_b["documents"][0]["doc_id"] == DOC


def test_budget_runs_out_with_a_typed_result(env: dict[str, str]) -> None:
    run, reader = uuid.uuid4(), client(env)
    statuses = [
        call(reader, "get_document", run, doc_id=d)["status"]
        for d in ("runbooks/pos-startup-failure.md", "runbooks/printer-offline.md",
                  "runbooks/pos-screen-frozen.md", "runbooks/pos-payment-error.md",
                  "runbooks/printer-wrong-output.md", "runbooks/pos-cash-drawer.md")
    ]  # fmt: skip
    assert statuses[0] == "found" and "budget_exceeded" in statuses


# ---- CP6.4 every KB code ranks its section first ---------------------------------------------


def _code_cases() -> list[tuple[str, str, str]]:
    cases = []
    for doc_id, codes in sorted(error_table_codes().items()):
        fams = metadata.families_of(metadata.categories_of(metadata.title_of(_title(doc_id))))
        for code in sorted(codes):
            if tokenizer.codes_in(code):
                cases.append((code, fams[0], doc_id))
    return cases


def _title(doc_id: str) -> str:
    from tests.kb_data import kb_files

    return kb_files()[doc_id]


def test_every_kb_code_ranks_a_section_holding_it_first(
    env: dict[str, str], db: psycopg.Connection[Any]
) -> None:
    cases = _code_cases()
    assert len(cases) >= 80
    reader = client(env)

    async def run_all() -> list[tuple[str, str, str]]:
        failures = []
        for code, family, _doc in cases:
            out = await reader.call(
                "search_kb", {"query": f"error {code}", "device_family": family, "k": 3}
            )
            top = out["documents"][0]["sections"][0] if out["documents"] else None
            if top is None or not top["promoted"]:
                failures.append((code, family, "not promoted"))
                continue
            row = db.execute(
                "SELECT bm25_tokens FROM kb.sections WHERE section_id = %s", (top["section_id"],)
            ).fetchone()
            if row is None or tokenizer.term(tokenizer.normalize_code(code)) not in row[0]:
                failures.append((code, family, top["section_id"]))
        return failures

    assert asyncio.run(run_all()) == []
