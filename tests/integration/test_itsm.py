"""itsm-actions MCP server against the running platform (S7: CP7.1, CP7.2, CP7.3).

The server runs in-process (uvicorn thread) so each test can set
ACTION_AUTONOMY_RUNS, EVAL_MODE or a failing outcome; everything else is real: a
Keycloak `agent-actor` token (JWT, scope, audience), OPA P7/P8/P9/P5, Postgres as
`itsm_rw`. `test_container_smoke` repeats one call against the container on 8103.

Approvals and fixes bind to a section of the ticket's runbook and the exact
runbook words (S8a), so the module seeds fixture sections under its own KB
revisions (non-current) and removes them afterwards. The
autonomy rows of the test actions on the test device models are reset around
each test.
"""

from __future__ import annotations

import asyncio
import socket
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
import uvicorn
from psycopg.types.json import Jsonb

from support_agent.agent.bindings import Bindings, default_bindings
from support_agent.agent.tools import McpToolClient, TokenSource, ToolCallError
from support_agent.common.config import ItsmSettings
from support_agent.mcp.base.errors import ErrorCode
from support_agent.mcp.itsm.outcome import FaultCardOutcome, Outcome, OutcomeProvider
from support_agent.mcp.itsm.registry import RegistryAction, default_registry
from support_agent.mcp.itsm.server import build_service
from tests.integration.platform_env import ROOT, load_env, superuser_url

pytestmark = pytest.mark.integration

ISSUER = "http://localhost:8080/realms/servewell"
CONTAINER_URL = "http://localhost:8103/mcp"
TAG = uuid.uuid4().hex[:8]
KB_REV = f"kb-test-s7-{TAG}"
KB_OLD = f"kb-test-s7-old-{TAG}"
KB_DRIFT = f"kb-test-s7-drift-{TAG}"
DOC = "runbooks/test-s7-printer.md"
DOC_OTHER = "runbooks/test-s7-other.md"
ACTIONS = ("check_printer_status", "restart_print_spooler", "clear_print_queue")

# Old fixture step names -> (kb_rev, doc, section_id, section text). The quote the
# agent sends is the section text itself.
SECTIONS = {
    "res.status.1": (KB_REV, DOC, f"{DOC}#status",
                     "Check the printer status shown in the POS settings screen."),
    "res.spooler.1": (KB_REV, DOC, f"{DOC}#spooler",
                      "Restart the Windows Print Spooler service from services.msc."),
    "res.spooler.3": (KB_REV, DOC, f"{DOC}#spooler-again",
                      "If the printer is still offline, restart the Print Spooler again."),
    "res.queue.1": (KB_REV, DOC, f"{DOC}#queue",
                    "Clear every pending job from the POS print queue."),
    "res.only-other.1": (KB_REV, DOC_OTHER, f"{DOC_OTHER}#spooler",
                         "Restart the Windows Print Spooler as the other runbook says."),
    "res.old.1": (KB_OLD, DOC, f"{DOC}#old",
                  "Restart the spooler as the old revision of the runbook says."),
    "drift.spooler.1": (KB_DRIFT, DOC, f"{DOC}#spooler",
                        "Restart the Windows Print Spooler service from services.msc."),
}  # fmt: skip


# The fixture's approved IT steps (S12a): run_fix and create_approval accept only a
# (section, quote, action) that is a binding of the ticket's runbook.
FIXTURE_ACTIONS = {
    "res.status.1": "check_printer_status", "res.spooler.1": "restart_print_spooler",
    "res.spooler.3": "restart_print_spooler", "res.queue.1": "clear_print_queue",
    "res.only-other.1": "restart_print_spooler", "res.old.1": "restart_print_spooler",
}  # fmt: skip


def fixture_bindings() -> Bindings:
    runbooks: dict[str, list[dict[str, Any]]] = {}
    for i, (step, action) in enumerate(FIXTURE_ACTIONS.items()):
        _rev, doc, section_id, text = SECTIONS[step]
        runbooks.setdefault(doc, []).append({
            "id": f"fx-{i}-step", "section": section_id, "title": f"Fixture {step}",
            "span": text, "audience": "it", "action_id": action,
        })  # fmt: skip
    return Bindings.model_validate({"version": 1, "runbooks": runbooks})


def sec(step: str) -> dict[str, str]:
    _rev, _doc, section_id, text = SECTIONS[step]
    return {"section_id": section_id, "quote": text}


# ---- platform fixtures -----------------------------------------------------------------


@pytest.fixture(scope="module")
def env() -> dict[str, str]:
    return load_env()


@pytest.fixture(scope="module")
def db(env: dict[str, str]) -> Iterator[psycopg.Connection[Any]]:
    with psycopg.connect(superuser_url(env), autocommit=True) as conn:
        yield conn


@dataclass(frozen=True)
class Assets:
    store: str
    printer: str
    printer_model: str
    pos: str
    pos_model: str
    other_store: str
    other_printer: str


@pytest.fixture(scope="module")
def assets(db: psycopg.Connection[Any]) -> Assets:
    def first(store: str, kind: str) -> tuple[str, str]:
        row = db.execute(
            "SELECT asset_id, model FROM data.assets WHERE store_id = %s AND asset_type = %s "
            "ORDER BY asset_id LIMIT 1",
            (store, kind),
        ).fetchone()
        assert row, (store, kind)
        return str(row[0]), str(row[1])

    printer, pmodel = first("SW-0001", "Receipt Printer")
    pos, posmodel = first("SW-0001", "POS Terminal")
    other, _ = first("SW-0002", "Receipt Printer")
    return Assets("SW-0001", printer, pmodel, pos, posmodel, "SW-0002", other)


@pytest.fixture(scope="module", autouse=True)
def kb_fixture(db: psycopg.Connection[Any]) -> Iterator[None]:
    version = default_registry().version
    revs = {KB_REV: version, KB_OLD: version, KB_DRIFT: "reg-0000000000000000"}
    for rev, reg in revs.items():
        db.execute(
            "INSERT INTO kb.revisions (kb_rev, source_hashes, pipeline_version, rule_versions, "
            "report, is_current) VALUES (%s, '{}', 'test-s7', %s, '{}', false)",
            (rev, Jsonb({"action_registry": reg})),
        )
    vector = "[" + ",".join(["0.01"] * 768) + "]"
    for ord_, (rev, doc, section_id, text) in enumerate(SECTIONS.values()):
        db.execute(
            "INSERT INTO kb.sections (kb_rev, section_id, parent_section_id, doc_id, doc_type, "
            "device_family, categories, path, ord, masked_text, index_text, bm25_tokens, "
            "token_count, embedding) VALUES (%s, %s, NULL, %s, 'runbook', '{printer}', "
            "'{Printers}', 'Fixture', %s, %s, %s, '{fixture}', 10, %s::vector)",
            (rev, section_id, doc, ord_, text, text, vector),
        )
    yield
    db.execute("DELETE FROM kb.sections WHERE kb_rev = ANY(%s)", (list(revs),))
    db.execute("DELETE FROM kb.revisions WHERE kb_rev = ANY(%s)", (list(revs),))


@pytest.fixture(autouse=True)
def reset_autonomy(db: psycopg.Connection[Any], assets: Assets) -> Iterator[None]:
    def reset() -> None:
        db.execute(
            "DELETE FROM itsm.action_autonomy WHERE action_id = ANY(%s) AND device_model = ANY(%s)",
            (list(ACTIONS), [assets.printer_model, assets.pos_model]),
        )

    reset()
    yield
    reset()


# ---- an in-process server --------------------------------------------------------------


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class FailOutcome:
    async def outcome(
        self, action: RegistryAction, *, ticket_id: str, asset_id: str,
        source_ticket_id: str | None = None,
    ) -> Outcome:  # fmt: skip
        return Outcome("failed", f"{action.action_id} failed (simulated)")


@contextmanager
def serve(
    runs: int = 1, *, eval_mode: bool = False, outcome: OutcomeProvider | None = None
) -> Iterator[str]:
    settings = ItsmSettings(_env_file=ROOT / ".env").model_copy(  # type: ignore[call-arg]
        update={"action_autonomy_runs": runs, "eval_mode": eval_mode, "db_host": None}
    )
    port = _free_port()
    app = build_service(settings, outcome=outcome, bindings=fixture_bindings()).app()
    server = uvicorn.Server(uvicorn.Config(app, port=port, log_config=None, lifespan="on"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 15
    while not server.started:
        if time.time() > deadline:
            raise RuntimeError("itsm server did not start")
        time.sleep(0.05)
    try:
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
        server.should_exit = True
        thread.join(5)


@pytest.fixture(scope="module")
def tokens(env: dict[str, str]) -> TokenSource:
    return TokenSource(ISSUER, "agent-actor", env["KEYCLOAK_SECRET_AGENT_ACTOR"])


@pytest.fixture
def url() -> Iterator[str]:
    with serve() as u:
        yield u


# ---- calls -----------------------------------------------------------------------------


@dataclass(frozen=True)
class Ctx:
    run_id: uuid.UUID
    ticket_id: str
    store_id: str

    def key(self, node: str, step: str = "0") -> str:
        return f"{self.run_id}:{self.ticket_id}:{node}:{step}"


def new_ctx(store: str) -> Ctx:
    return Ctx(uuid.uuid4(), f"INC-T{uuid.uuid4().hex[:8].upper()}", store)


def call(url: str, tokens: TokenSource, ctx: Ctx, tool: str, **args: Any) -> dict[str, Any]:
    client = McpToolClient(url, tokens, lambda d, _t: d, retries=0)
    clean = {
        k: (str(v) if isinstance(v, uuid.UUID) else v.isoformat() if isinstance(v, datetime) else v)
        for k, v in args.items()
    }
    return asyncio.run(
        client.call(tool, clean, ticket_id=ctx.ticket_id, run_id=ctx.run_id, store_id=ctx.store_id)
    )


def refused(fn: Callable[[], Any], code: ErrorCode = ErrorCode.DENIED) -> str:
    with pytest.raises(ToolCallError) as info:
        fn()
    assert info.value.code == code, info.value
    return info.value.reason


def ticket(
    url: str,
    tokens: TokenSource,
    ctx: Ctx,
    asset: str,
    *,
    kb_rev: str = KB_REV,
    doc: str = DOC,
    source: str | None = None,
) -> None:
    extra = {"source_ticket_id": source} if source else {}
    call(url, tokens, ctx, "create_ticket", idem_key=ctx.key("intake"),
         date_opened=datetime(2026, 11, 19, 9, 0, tzinfo=UTC), asset_id=asset, priority="P3",
         category="Printer", submitted_by_user="mock-store-sw-0001", **extra)  # fmt: skip
    call(url, tokens, ctx, "update_ticket", idem_key=ctx.key("triage"), route="resolver",
         runbook_id=doc, kb_rev=kb_rev, status="in_progress")  # fmt: skip


def approve(
    url: str, tokens: TokenSource, ctx: Ctx, asset: str, step: str, action: str, n: int = 0
) -> str:
    req = call(url, tokens, ctx, "create_approval", idem_key=ctx.key("approval", f"{step}.{n}"),
               asset_id=asset, **sec(step), action_id=action, approver_role="l2_engineer",
               requested_by="agent-actor")  # fmt: skip
    call(url, tokens, ctx, "decide_approval", idem_key=ctx.key("decide", f"{step}.{n}"),
         approval_id=req["approval_id"], decision="approve", decided_by="mock-l2")  # fmt: skip
    return str(req["approval_id"])


def fix(
    url: str, tokens: TokenSource, ctx: Ctx, asset: str, step: str, action: str,
    approval: str | None = None, n: int = 0,
) -> dict[str, Any]:  # fmt: skip
    args: dict[str, Any] = {"asset_id": asset, **sec(step), "action_id": action}
    if approval:
        args["approval_id"] = approval
    return call(url, tokens, ctx, "run_fix", idem_key=ctx.key("fix", f"{step}.{n}"), **args)


def domain_events(db: psycopg.Connection[Any], key: str) -> int:
    row = db.execute(
        "SELECT count(*) FROM audit.events WHERE step = 'itsm' AND payload->>'idem_key' = %s",
        (key,),
    ).fetchone()
    return int(row[0]) if row else 0


def denied_events(db: psycopg.Connection[Any], ctx: Ctx) -> list[str]:
    rows = db.execute(
        "SELECT reason FROM audit.events WHERE step = 'itsm' AND action = 'run_fix' "
        "AND result = 'denied' AND run_id = %s ORDER BY id",
        (ctx.run_id,),
    ).fetchall()
    return [str(r[0]) for r in rows]


def autonomy_row(db: psycopg.Connection[Any], action: str, model: str) -> tuple[str, int] | None:
    row = db.execute(
        "SELECT state, runs_in_a_row FROM itsm.action_autonomy "
        "WHERE action_id = %s AND device_model = %s",
        (action, model),
    ).fetchone()
    return (str(row[0]), int(row[1])) if row else None


# ---- CP7.1 idempotent writes ------------------------------------------------------------


def test_each_tool_writes_once_per_key(
    url: str, tokens: TokenSource, db: psycopg.Connection[Any], assets: Assets
) -> None:
    ctx = new_ctx(assets.store)
    created = datetime(2026, 11, 19, 9, 0, tzinfo=UTC)
    approval_holder: dict[str, str] = {}

    def approval_id() -> str:
        if "id" not in approval_holder:
            row = db.execute(
                "SELECT id FROM itsm.approvals WHERE idem_key = %s", (ctx.key("approval"),)
            ).fetchone()
            assert row
            approval_holder["id"] = str(row[0])
        return approval_holder["id"]

    # (tool, key, args, table holding the row)
    calls: list[tuple[str, str, Callable[[], dict[str, Any]], str]] = [
        ("create_ticket", ctx.key("intake"), lambda: {
            "date_opened": created, "asset_id": assets.printer, "priority": "P3",
            "category": "Printer"}, "tickets"),
        ("update_ticket", ctx.key("triage"), lambda: {
            "runbook_id": DOC, "kb_rev": KB_REV, "route": "resolver"}, "idempotency"),
        ("add_comment", ctx.key("triage", "note"), lambda: {
            "kind": "note", "body": "Triage picked the printer runbook."}, "ticket_comments"),
        ("message_store", ctx.key("communicate", "res.status.1"), lambda: {
            "kind": "step", "body": "Please check the printer cable.",
            "section_id": sec("res.status.1")["section_id"]}, "store_messages"),
        ("create_approval", ctx.key("approval"), lambda: {
            "asset_id": assets.printer, **sec("res.spooler.1"),
            "action_id": "restart_print_spooler", "approver_role": "l2_engineer",
            "requested_by": "agent-actor"}, "approvals"),
        ("decide_approval", ctx.key("decide"), lambda: {
            "approval_id": approval_id(), "decision": "approve",
            "decided_by": "mock-l2"}, "idempotency"),
        ("create_l2_task", ctx.key("resolver", "res.l2only.1"), lambda: {
            "section_id": sec("res.queue.1")["section_id"], "reason": "l2_only",
            "note": "L2 to run this step."}, "l2_tasks"),
        ("run_fix", ctx.key("fix", "res.status.1"), lambda: {
            "asset_id": assets.printer, **sec("res.status.1"),
            "action_id": "check_printer_status"}, "actions"),
        ("escalate_to_l2", ctx.key("handoff"), lambda: {
            "queue": "l2", "reason_code": "no_kb_match",
            "note": "Printer still offline after status check."}, "ticket_comments"),
    ]  # fmt: skip
    for tool, key, args_fn, table in calls:
        args = args_fn()
        first = call(url, tokens, ctx, tool, idem_key=key, **args)
        second = call(url, tokens, ctx, tool, idem_key=key, **args)
        assert first == second, tool
        rows = db.execute(
            f"SELECT count(*) FROM itsm.{table} WHERE idem_key = %s",  # noqa: S608 - fixed names
            (key,),
        ).fetchone()
        assert rows and rows[0] == 1, tool
        assert domain_events(db, key) == 1, tool
    # The approval was consumed by nothing (read_only ran without it); the ticket escalated.
    status = db.execute(
        "SELECT status, assignee_queue FROM itsm.tickets WHERE run_id = %s AND ticket_id = %s",
        (ctx.run_id, ctx.ticket_id),
    ).fetchone()
    assert status == ("escalated", "l2")


def test_same_key_other_arguments_is_conflict(
    url: str, tokens: TokenSource, assets: Assets
) -> None:
    ctx = new_ctx(assets.store)
    ticket(url, tokens, ctx, assets.printer)
    key = ctx.key("triage", "note")
    call(url, tokens, ctx, "add_comment", idem_key=key, kind="note", body="first")
    reason = refused(
        lambda: call(url, tokens, ctx, "add_comment", idem_key=key, kind="note", body="second"),
        ErrorCode.CONFLICT,
    )
    assert reason == "idem_key_reused_with_other_arguments"


def test_create_ticket_is_idempotent_on_run_and_ticket(
    url: str, tokens: TokenSource, db: psycopg.Connection[Any], assets: Assets
) -> None:
    ctx = new_ctx(assets.store)
    opened = datetime(2026, 11, 19, 9, 0, tzinfo=UTC)
    a = call(url, tokens, ctx, "create_ticket", idem_key=ctx.key("intake"), date_opened=opened,
             asset_id=assets.printer)  # fmt: skip
    # Another key with the same payload returns the same ticket and writes nothing.
    b = call(url, tokens, ctx, "create_ticket", idem_key=ctx.key("intake", "retry"),
             date_opened=opened, asset_id=assets.printer)  # fmt: skip
    assert a == b
    # Another key with another payload is refused.
    refused(
        lambda: call(url, tokens, ctx, "create_ticket", idem_key=ctx.key("intake", "other"),
                     date_opened=opened, asset_id=assets.pos),
        ErrorCode.CONFLICT,
    )  # fmt: skip
    # The same ticket id under a second run is a new row (run isolation, B1).
    ctx2 = Ctx(uuid.uuid4(), ctx.ticket_id, ctx.store_id)
    call(url, tokens, ctx2, "create_ticket", idem_key=ctx2.key("intake"), date_opened=opened,
         asset_id=assets.printer)  # fmt: skip
    rows = db.execute(
        "SELECT count(*) FROM itsm.tickets WHERE ticket_id = %s", (ctx.ticket_id,)
    ).fetchone()
    assert rows and rows[0] == 2
    events = db.execute(
        "SELECT count(*) FROM audit.events WHERE step = 'itsm' AND action = 'create_ticket' "
        "AND ticket_id = %s",
        (ctx.ticket_id,),
    ).fetchone()
    assert events and events[0] == 2


def test_runbook_and_kb_rev_are_set_once(url: str, tokens: TokenSource, assets: Assets) -> None:
    ctx = new_ctx(assets.store)
    ticket(url, tokens, ctx, assets.printer)
    reason = refused(
        lambda: call(url, tokens, ctx, "update_ticket", idem_key=ctx.key("triage", "2"),
                     kb_rev=KB_OLD),
        ErrorCode.CONFLICT,
    )  # fmt: skip
    assert reason == "kb_rev_already_set"


def test_key_and_context_must_be_bound(url: str, tokens: TokenSource, assets: Assets) -> None:
    ctx = new_ctx(assets.store)
    other = new_ctx(assets.store)
    opened = datetime(2026, 11, 19, 9, 0, tzinfo=UTC)
    reason = refused(
        lambda: call(url, tokens, ctx, "create_ticket", idem_key=other.key("intake"),
                     date_opened=opened),
        ErrorCode.INVALID,
    )  # fmt: skip
    assert reason == "idem_key_not_bound_to_run_and_ticket"
    unbound = Ctx(ctx.run_id, ctx.ticket_id, "")
    assert (
        refused(
            lambda: call(
                url,
                tokens,
                unbound,
                "create_ticket",
                idem_key=ctx.key("intake"),
                date_opened=opened,
            )
        )  # fmt: skip
        == "unbound_call"
    )


# ---- CP7.2 approvals and own store -----------------------------------------------------


def test_supervised_fix_needs_a_valid_approval(
    url: str, tokens: TokenSource, db: psycopg.Connection[Any], assets: Assets
) -> None:
    ctx = new_ctx(assets.store)
    ticket(url, tokens, ctx, assets.printer)
    p, spool = assets.printer, "restart_print_spooler"
    # 1 no approval
    assert "approval_missing" in refused(lambda: fix(url, tokens, ctx, p, "res.spooler.1", spool))
    # 2 expired (wall time)
    expired = approve(url, tokens, ctx, p, "res.spooler.1", spool, n=1)
    db.execute(
        "UPDATE itsm.approvals SET expires_at = now() - interval '1 minute' WHERE id = %s",
        (expired,),
    )
    assert "approval_expired" in refused(
        lambda: fix(url, tokens, ctx, p, "res.spooler.1", spool, expired, n=2)
    )
    # 3a approval for another runbook section
    other_step = approve(url, tokens, ctx, p, "res.spooler.3", spool, n=3)
    assert "approval_binding:section_id" in refused(
        lambda: fix(url, tokens, ctx, p, "res.spooler.1", spool, other_step, n=3)
    )
    # 3b approval for another kb_rev
    other_rev = approve(url, tokens, ctx, p, "res.spooler.1", spool, n=4)
    db.execute("UPDATE itsm.approvals SET kb_rev = %s WHERE id = %s", (KB_OLD, other_rev))
    assert "approval_binding:kb_rev" in refused(
        lambda: fix(url, tokens, ctx, p, "res.spooler.1", spool, other_rev, n=4)
    )
    # 4 used approval
    good = approve(url, tokens, ctx, p, "res.spooler.1", spool, n=5)
    assert fix(url, tokens, ctx, p, "res.spooler.1", spool, good, n=5)["status"] == "ran"
    db.execute(  # back to supervised so the approval is the only thing that could allow it
        "DELETE FROM itsm.action_autonomy WHERE action_id = %s AND device_model = %s",
        (spool, assets.printer_model),
    )
    assert "approval_used" in refused(
        lambda: fix(url, tokens, ctx, p, "res.spooler.1", spool, good, n=6)
    )
    assert len(denied_events(db, ctx)) == 5


def test_other_store_ticket_and_asset_are_refused(
    url: str, tokens: TokenSource, db: psycopg.Connection[Any], assets: Assets
) -> None:
    ctx = new_ctx(assets.store)
    ticket(url, tokens, ctx, assets.printer)
    # The same run and ticket, bound to another store: every write is refused.
    stranger = Ctx(ctx.run_id, ctx.ticket_id, assets.other_store)
    assert (
        refused(lambda: call(url, tokens, stranger, "add_comment",
                             idem_key=ctx.key("x", "1"), kind="note", body="x"))
        == "other_store"
    )  # fmt: skip
    assert "other_store" in refused(
        lambda: fix(url, tokens, stranger, assets.printer, "res.status.1", "check_printer_status")
    )
    # A ticket whose asset is another store's printer.
    ctx2 = new_ctx(assets.store)
    ticket(url, tokens, ctx2, assets.other_printer)
    assert "asset_other_store" in refused(
        lambda: fix(url, tokens, ctx2, assets.other_printer, "res.status.1",
                    "check_printer_status")
    )  # fmt: skip
    # An asset that is not the ticket's asset.
    assert "not_ticket_asset" in refused(
        lambda: fix(url, tokens, ctx, assets.pos, "res.status.1", "check_printer_status")
    )
    assert len(denied_events(db, stranger)) == 2  # same run id as ctx: both run_fix denials


def test_quote_binding_is_checked(
    url: str, tokens: TokenSource, db: psycopg.Connection[Any], assets: Assets
) -> None:
    ctx = new_ctx(assets.store)
    ticket(url, tokens, ctx, assets.printer)
    p = assets.printer
    # Words that are not in the cited section of the ticket's runbook (S8a).
    made_up = {**sec("res.spooler.1"), "quote": "Format the POS disk and reinstall Windows now."}
    assert "quote_not_in_section" in refused(
        lambda: call(url, tokens, ctx, "run_fix", idem_key=ctx.key("fix", "made-up"),
                     asset_id=p, action_id="check_printer_status", **made_up)
    )  # fmt: skip
    # A section of another runbook, and a section of another kb_rev: not this ticket's.
    assert "section_not_in_runbook" in refused(
        lambda: fix(url, tokens, ctx, p, "res.only-other.1", "restart_print_spooler")
    )
    assert "section_not_in_runbook" in refused(
        lambda: fix(url, tokens, ctx, p, "res.old.1", "restart_print_spooler")
    )
    # The server never creates an approval for made-up words either.
    assert refused(
        lambda: call(url, tokens, ctx, "create_approval", idem_key=ctx.key("approval", "m"),
                     asset_id=p, action_id="restart_print_spooler", approver_role="l2_engineer",
                     requested_by="agent-actor", **made_up)
    ) == "quote_not_in_section"  # fmt: skip
    # An action whose device families exclude the asset (printer check on a POS ticket).
    pos = new_ctx(assets.store)
    ticket(url, tokens, pos, assets.pos)
    assert "device_family" in refused(
        lambda: fix(url, tokens, pos, assets.pos, "res.status.1", "check_printer_status")
    )
    # A ticket triaged on a revision whose registry version differs (drift).
    drift = new_ctx(assets.store)
    ticket(url, tokens, drift, p, kb_rev=KB_DRIFT)
    assert "registry_drift" in refused(
        lambda: fix(url, tokens, drift, p, "drift.spooler.1", "restart_print_spooler")
    )
    assert len(denied_events(db, ctx)) == 3


def test_one_approval_runs_once_under_concurrency(
    url: str, tokens: TokenSource, db: psycopg.Connection[Any], assets: Assets
) -> None:
    ctx = new_ctx(assets.store)
    ticket(url, tokens, ctx, assets.printer)
    p, spool = assets.printer, "restart_print_spooler"
    approval = approve(url, tokens, ctx, p, "res.spooler.3", spool)
    client = McpToolClient(url, tokens, lambda d, _t: d, retries=0)
    args = {"asset_id": p, **sec("res.spooler.3"), "action_id": spool, "approval_id": approval}

    async def both() -> list[Any]:
        return await asyncio.gather(
            *(
                client.call("run_fix", {**args, "idem_key": ctx.key("fix", f"race.{i}")},
                            ticket_id=ctx.ticket_id, run_id=ctx.run_id, store_id=ctx.store_id)
                for i in range(2)
            ),
            return_exceptions=True,
        )  # fmt: skip

    results = asyncio.run(both())
    ok = [r for r in results if isinstance(r, dict)]
    errors = [r for r in results if isinstance(r, ToolCallError)]
    assert len(ok) == 1 and len(errors) == 1, results
    assert errors[0].code == ErrorCode.DENIED and "approval_used" in errors[0].reason
    rows = db.execute(
        "SELECT count(*) FROM itsm.actions WHERE approval_id = %s", (approval,)
    ).fetchone()
    assert rows and rows[0] == 1
    assert len(denied_events(db, ctx)) == 1


# ---- CP7.3 registry, tier and autonomy -------------------------------------------------


def test_unknown_action_is_refused_and_audited(
    url: str, tokens: TokenSource, db: psycopg.Connection[Any], assets: Assets
) -> None:
    ctx = new_ctx(assets.store)
    ticket(url, tokens, ctx, assets.printer)
    assert "unknown_action" in refused(
        lambda: fix(url, tokens, ctx, assets.printer, "res.spooler.1", "format_disk")
    )
    assert any("unknown_action" in r for r in denied_events(db, ctx))
    calls = db.execute(
        "SELECT count(*) FROM audit.events WHERE step = 'mcp.itsm' AND action = 'run_fix' "
        "AND result = 'denied' AND run_id = %s",
        (ctx.run_id,),
    ).fetchone()
    assert calls and calls[0] == 1


def test_read_only_runs_without_approval(url: str, tokens: TokenSource, assets: Assets) -> None:
    ctx = new_ctx(assets.store)
    ticket(url, tokens, ctx, assets.printer)
    out = fix(url, tokens, ctx, assets.printer, "res.status.1", "check_printer_status")
    assert (out["status"], out["tier"], out["approval_id"]) == ("ran", "read_only", None)


@pytest.mark.parametrize("runs", [1, 3])
def test_reversible_needs_approval_until_promoted(
    runs: int, tokens: TokenSource, db: psycopg.Connection[Any], assets: Assets
) -> None:
    p, spool, model = assets.printer, "restart_print_spooler", assets.printer_model
    with serve(runs) as url:
        ctx = new_ctx(assets.store)
        ticket(url, tokens, ctx, p)
        for n in range(runs):
            assert "approval_missing" in refused(
                lambda n=n: fix(url, tokens, ctx, p, "res.spooler.1", spool, n=100 + n)
            )
            approval = approve(url, tokens, ctx, p, "res.spooler.1", spool, n=n)
            out = fix(url, tokens, ctx, p, "res.spooler.1", spool, approval, n=n)
            assert out["autonomy_state_at_run"] == "supervised"
        assert autonomy_row(db, spool, model) == ("autonomous", runs)
        alone = fix(url, tokens, ctx, p, "res.spooler.1", spool, n=999)
        assert (alone["autonomy_state_at_run"], alone["approval_id"]) == ("autonomous", None)
    promoted = db.execute(
        "SELECT count(*) FROM audit.events WHERE action = 'action_promoted' AND run_id = %s",
        (ctx.run_id,),
    ).fetchone()
    assert promoted and promoted[0] == 1


def test_reject_demotes(tokens: TokenSource, db: psycopg.Connection[Any], assets: Assets) -> None:
    p, spool, model = assets.printer, "restart_print_spooler", assets.printer_model
    with serve(3) as url:
        ctx = new_ctx(assets.store)
        ticket(url, tokens, ctx, p)
        for n in range(2):
            fix(url, tokens, ctx, p, "res.spooler.1", spool,
                approve(url, tokens, ctx, p, "res.spooler.1", spool, n=n), n=n)  # fmt: skip
        assert autonomy_row(db, spool, model) == ("supervised", 2)
        req = call(url, tokens, ctx, "create_approval", idem_key=ctx.key("approval", "r"),
                   asset_id=p, **sec("res.spooler.1"), action_id=spool,
                   approver_role="l2_engineer", requested_by="agent-actor")  # fmt: skip
        assert refused(
            lambda: call(url, tokens, ctx, "decide_approval", idem_key=ctx.key("decide", "r0"),
                         approval_id=req["approval_id"], decision="reject",
                         decided_by="mock-l2"),
            ErrorCode.INVALID,
        ) == "reject_needs_reason"  # fmt: skip
        out = call(url, tokens, ctx, "decide_approval", idem_key=ctx.key("decide", "r"),
                   approval_id=req["approval_id"], decision="reject", decided_by="mock-l2",
                   reason="Not during lunch peak.")  # fmt: skip
        assert (out["status"], out["autonomy_state"]) == ("rejected", "supervised")
        assert autonomy_row(db, spool, model) == ("supervised", 0)
        assert "approval_not_approved" in refused(
            lambda: fix(url, tokens, ctx, p, "res.spooler.1", spool, str(req["approval_id"]), n=7)
        )
    demoted = db.execute(
        "SELECT count(*) FROM audit.events WHERE action = 'action_demoted' AND run_id = %s",
        (ctx.run_id,),
    ).fetchone()
    assert demoted and demoted[0] == 1


def test_self_approval_and_double_decision_are_refused(
    url: str, tokens: TokenSource, assets: Assets
) -> None:
    ctx = new_ctx(assets.store)
    ticket(url, tokens, ctx, assets.printer)
    req = call(url, tokens, ctx, "create_approval", idem_key=ctx.key("approval"),
               asset_id=assets.printer, **sec("res.spooler.1"),
               action_id="restart_print_spooler", approver_role="l2_engineer",
               requested_by="mock-l2")  # fmt: skip
    assert refused(
        lambda: call(url, tokens, ctx, "decide_approval", idem_key=ctx.key("decide", "self"),
                     approval_id=req["approval_id"], decision="approve", decided_by="mock-l2")
    ) == "approver_is_requester"  # fmt: skip
    call(url, tokens, ctx, "decide_approval", idem_key=ctx.key("decide"),
         approval_id=req["approval_id"], decision="approve", decided_by="mock-vendor")  # fmt: skip
    assert refused(
        lambda: call(url, tokens, ctx, "decide_approval", idem_key=ctx.key("decide", "again"),
                     approval_id=req["approval_id"], decision="approve", decided_by="mock-l1"),
        ErrorCode.CONFLICT,
    ) == "approval_already_decided"  # fmt: skip


def test_failed_autonomous_run_demotes(
    tokens: TokenSource, db: psycopg.Connection[Any], assets: Assets
) -> None:
    p, spool, model = assets.printer, "restart_print_spooler", assets.printer_model
    ctx = new_ctx(assets.store)
    with serve(1) as url:
        ticket(url, tokens, ctx, p)
        fix(url, tokens, ctx, p, "res.spooler.1", spool,
            approve(url, tokens, ctx, p, "res.spooler.1", spool), n=0)  # fmt: skip
        assert autonomy_row(db, spool, model) == ("autonomous", 1)
    with serve(1, outcome=FailOutcome()) as url:
        out = fix(url, tokens, ctx, p, "res.spooler.1", spool, n=1)
        assert (out["outcome"], out["autonomy_state_at_run"], out["autonomy_state_after"]) == (
            "failed", "autonomous", "supervised",
        )  # fmt: skip
        assert autonomy_row(db, spool, model) == ("supervised", 0)
        assert "approval_missing" in refused(
            lambda: fix(url, tokens, ctx, p, "res.spooler.1", spool, n=2)
        )


def test_destructive_always_needs_approval(
    url: str, tokens: TokenSource, db: psycopg.Connection[Any], assets: Assets
) -> None:
    p, queue = assets.printer, "clear_print_queue"
    ctx = new_ctx(assets.store)
    ticket(url, tokens, ctx, p)
    for n in range(3):
        out = fix(url, tokens, ctx, p, "res.queue.1", queue,
                  approve(url, tokens, ctx, p, "res.queue.1", queue, n=n), n=n)  # fmt: skip
        assert out["autonomy_state_after"] == "supervised"
    assert autonomy_row(db, queue, assets.printer_model) == ("supervised", 3)
    assert "approval_missing" in refused(
        lambda: fix(url, tokens, ctx, p, "res.queue.1", queue, n=9)
    )


def test_eval_mode_never_promotes(
    tokens: TokenSource, db: psycopg.Connection[Any], assets: Assets
) -> None:
    p, spool = assets.printer, "restart_print_spooler"
    with serve(1, eval_mode=True, outcome=FaultCardOutcome({})) as url:
        ctx = new_ctx(assets.store)
        ticket(url, tokens, ctx, p)
        for n in range(2):
            out = fix(url, tokens, ctx, p, "res.spooler.1", spool,
                      approve(url, tokens, ctx, p, "res.spooler.1", spool, n=n), n=n)  # fmt: skip
            # No fault card loaded: an eval action changes nothing (D40).
            assert (out["outcome"], out["autonomy_state_after"]) == ("no_change", "supervised")
        assert "approval_missing" in refused(
            lambda: fix(url, tokens, ctx, p, "res.spooler.1", spool, n=9)
        )
    history = db.execute(
        "SELECT count(*), bool_and(eval_mode), bool_and(state_after = 'supervised') "
        "FROM itsm.action_autonomy_history WHERE run_id = %s",
        (ctx.run_id,),
    ).fetchone()
    assert history == (2, True, True)


def test_eval_replay_is_scored_by_its_source_ticket_card(
    tokens: TokenSource, db: psycopg.Connection[Any], assets: Assets
) -> None:
    """S12a: a replayed ticket has a fresh operational id; the card is found by its
    source_ticket_id, a matching action is "fixed" and another is "no change"."""
    p, spool = assets.printer, "restart_print_spooler"
    cards = FaultCardOutcome({"INC-99042": frozenset({spool})})
    with serve(1, eval_mode=True, outcome=cards) as url:
        ctx = new_ctx(assets.store)
        ticket(url, tokens, ctx, p, source="INC-99042")
        hit = fix(url, tokens, ctx, p, "res.spooler.1", spool,
                  approve(url, tokens, ctx, p, "res.spooler.1", spool))  # fmt: skip
        miss = fix(url, tokens, ctx, p, "res.status.1", "check_printer_status")
        other = new_ctx(assets.store)
        ticket(url, tokens, other, p, source="INC-99099")
        no_card = fix(url, tokens, other, p, "res.spooler.1", spool,
                      approve(url, tokens, other, p, "res.spooler.1", spool))  # fmt: skip
    assert (hit["outcome"], miss["outcome"], no_card["outcome"]) == (
        "fixed", "no_change", "no_change")  # fmt: skip
    stored = db.execute("SELECT outcome FROM itsm.actions WHERE run_id = %s ORDER BY id",
                        (ctx.run_id,)).fetchall()  # fmt: skip
    assert stored == [("fixed",), ("no_change",)]


# ---- S12a: approved binding and ticket state ----------------------------------------


def test_real_quote_with_another_action_is_refused(
    url: str, tokens: TokenSource, assets: Assets
) -> None:
    ctx = new_ctx(assets.store)
    ticket(url, tokens, ctx, assets.printer)
    p = assets.printer
    # The spooler quote is real, but its approved action is restart_print_spooler.
    assert "no_binding" in refused(lambda: fix(url, tokens, ctx, p, "res.spooler.1",
                                               "clear_print_queue"))  # fmt: skip
    assert refused(
        lambda: call(url, tokens, ctx, "create_approval", idem_key=ctx.key("approval", "x"),
                     asset_id=p, **sec("res.spooler.1"), action_id="clear_print_queue",
                     approver_role="l2_engineer", requested_by="agent-actor")
    ) == "no_binding"  # fmt: skip


def test_closed_ticket_runs_nothing(url: str, tokens: TokenSource, assets: Assets) -> None:
    ctx = new_ctx(assets.store)
    ticket(url, tokens, ctx, assets.printer)
    call(url, tokens, ctx, "update_ticket", idem_key=ctx.key("close"), status="resolved")
    assert "ticket_not_open" in refused(
        lambda: fix(url, tokens, ctx, assets.printer, "res.status.1", "check_printer_status")
    )
    assert refused(
        lambda: call(url, tokens, ctx, "create_approval", idem_key=ctx.key("approval", "c"),
                     asset_id=assets.printer, **sec("res.spooler.1"),
                     action_id="restart_print_spooler", approver_role="l2_engineer",
                     requested_by="agent-actor")
    ) == "ticket_not_open"  # fmt: skip


def test_deadline_crossed_after_approval_runs_nothing(
    url: str, tokens: TokenSource, db: psycopg.Connection[Any], assets: Assets
) -> None:
    ctx = new_ctx(assets.store)
    ticket(url, tokens, ctx, assets.printer)
    p = assets.printer
    db.execute("DELETE FROM itsm.action_autonomy WHERE action_id = %s AND device_model = %s",
               ("restart_print_spooler", assets.printer_model))  # fmt: skip
    appr = approve(url, tokens, ctx, p, "res.spooler.1", "restart_print_spooler")
    # escalate-by passes in ticket time after the approval was given (D48)
    past = datetime.now(UTC) - timedelta(minutes=1)
    call(url, tokens, ctx, "update_ticket", idem_key=ctx.key("sla"), escalate_by=past)
    assert "sla_passed" in refused(
        lambda: fix(url, tokens, ctx, p, "res.spooler.1", "restart_print_spooler", appr)
    )
    assert db.execute("SELECT count(*) FROM itsm.actions WHERE run_id = %s",
                      (ctx.run_id,)).fetchone() == (0,)  # fmt: skip


# ---- the container ---------------------------------------------------------------------


def test_container_smoke(tokens: TokenSource, db: psycopg.Connection[Any], assets: Assets) -> None:
    # The container loads the real bindings.yaml, so the fixture runbook has no
    # approved IT step (S12a) and a real printer-offline read-only step runs.
    ctx = new_ctx(assets.store)
    ticket(CONTAINER_URL, tokens, ctx, assets.printer)
    assert "no_binding" in refused(
        lambda: fix(CONTAINER_URL, tokens, ctx, assets.printer, "res.status.1",
                    "check_printer_status")
    )  # fmt: skip
    row = db.execute("SELECT kb_rev FROM kb.revisions WHERE is_current").fetchone()
    assert row, "no current kb revision"
    real = next(b for b in default_bindings().for_runbook("runbooks/printer-offline.md")
                if b.action_id == "check_printer_recognition")  # fmt: skip
    live = new_ctx(assets.store)
    ticket(CONTAINER_URL, tokens, live, assets.printer, kb_rev=str(row[0]), doc=real.doc_id)
    out = call(CONTAINER_URL, tokens, live, "run_fix", idem_key=live.key("fix", "real"),
               asset_id=assets.printer, section_id=real.section, quote=real.span,
               action_id="check_printer_recognition")  # fmt: skip
    assert out["status"] == "ran"
    # agent-reader has no itsm scope or audience: refused before any tool code.
    reader = TokenSource(ISSUER, "agent-reader", load_env()["KEYCLOAK_SECRET_AGENT_READER"])
    reason = refused(
        lambda: call(CONTAINER_URL, reader, ctx, "add_comment", idem_key=ctx.key("x"),
                     kind="note", body="x")
    )  # fmt: skip
    assert reason.startswith("http_")


# ---- S12a: make demote ------------------------------------------------------------------


def test_demote_resets_a_promoted_action_with_history(
    tokens: TokenSource, db: psycopg.Connection[Any], assets: Assets
) -> None:
    from support_agent.common.db import dsn
    from support_agent.mcp.base.opa import OpaClient
    from support_agent.mcp.itsm.demote import demote_all

    p, spool = assets.printer, "restart_print_spooler"
    with serve(1) as url:  # one approved, successful run promotes it (N = 1)
        ctx = new_ctx(assets.store)
        ticket(url, tokens, ctx, p)
        fix(url, tokens, ctx, p, "res.spooler.1", spool,
            approve(url, tokens, ctx, p, "res.spooler.1", spool))  # fmt: skip
    assert autonomy_row(db, spool, assets.printer_model) == ("autonomous", 1)
    s = ItsmSettings(_env_file=ROOT / ".env").model_copy(update={"db_host": None})  # type: ignore[call-arg]
    done = asyncio.run(demote_all(dsn(s.database_url_itsm, None), OpaClient(s.opa_url),
                                  spool, eval_mode=False))  # fmt: skip
    assert (assets.printer_model, "supervised") in done
    assert autonomy_row(db, spool, assets.printer_model) == ("supervised", 0)
    last = db.execute(
        "SELECT event, state_before, state_after, why FROM itsm.action_autonomy_history "
        "WHERE action_id = %s AND device_model = %s ORDER BY id DESC LIMIT 1",
        (spool, assets.printer_model),
    ).fetchone()
    assert last == (
        "admin_demote",
        "autonomous",
        "supervised",
        "admin_demote: make demote (demo reset)",
    )
