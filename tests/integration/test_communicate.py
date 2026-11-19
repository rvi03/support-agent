"""CP10.3, live (`make up`, real model on the `agent` alias).

After a run, the itsm rows exist, starting with the `create_ticket` row. The real
name is in `itsm.store_messages` only: a scan of comments (L1 pack, L2 note),
the itsm ticket row, the run's audit events, the `LOG_DIR` logs and the run's
Langfuse trace (every observation, the reply-sender span included) finds no
vault value (D43: full name, each name part of 3+ letters as a whole word,
case-insensitive; phone by its last 10 digits). The same ticket under a second
`run_id` gets a fresh thread and fresh rows (D45, review B1).
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from pathlib import Path

import psycopg
import pytest

from support_agent.agent.app import build_agent
from support_agent.agent.graph import thread
from support_agent.cli.ticket_local import main_async
from support_agent.common.config import AgentSettings, get_settings
from support_agent.eval.traces import LangfuseReader
from tests.integration.platform_env import ROOT, load_env, superuser_url

pytestmark = pytest.mark.integration
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "tickets"


def _vault(ticket_id: str) -> tuple[str, str]:
    with psycopg.connect(superuser_url(load_env())) as c:
        row = c.execute(
            "SELECT full_name, phone FROM pii.vault WHERE ticket_id = %s", (ticket_id,)
        ).fetchone()
    assert row and row[0] and row[1], "no vault row"
    return str(row[0]), str(row[1])


def _hits(text: str, name: str, phone: str) -> list[str]:
    """The D43 exact match: name parts as whole words, phone by its last 10 digits."""
    found = []
    for part in [name, *(p for p in name.split() if len(p) >= 3)]:
        if re.search(rf"(?i)\b{re.escape(part)}\b", text):
            found.append(f"name:{part}")
    digits = re.sub(r"\D", "", phone)[-10:]
    if digits in re.sub(r"[\s\-().+]", "", text):
        found.append("phone")
    return found


def _rows(run_id: str, ticket_id: str) -> dict[str, list[str]]:
    q = {
        "ticket": "SELECT row_to_json(t)::text FROM itsm.tickets t "
        "WHERE run_id = %s AND ticket_id = %s",
        "comments": "SELECT kind || ': ' || body FROM itsm.ticket_comments "
        "WHERE run_id = %s AND ticket_id = %s ORDER BY id",
        "messages": "SELECT body FROM itsm.store_messages "
        "WHERE run_id = %s AND ticket_id = %s ORDER BY id",
        "audit": "SELECT row_to_json(e)::text FROM audit.events e "
        "WHERE run_id = %s AND ticket_id = %s ORDER BY id",
        "idem": "SELECT idem_key FROM itsm.idempotency WHERE run_id = %s AND ticket_id = %s",
    }
    with psycopg.connect(superuser_url(load_env())) as c:
        return {
            k: [str(r[0]) for r in c.execute(sql, (run_id, ticket_id)).fetchall()]  # type: ignore[arg-type]
            for k, sql in q.items()
        }


def _trace(run_id: str, ticket_id: str) -> str:
    """Every observation of the run's trace, with input, output and metadata, as text."""
    env = load_env()
    reader = LangfuseReader(
        env["LANGFUSE_HOST"], env["LANGFUSE_PUBLIC_KEY"], env["LANGFUSE_SECRET_KEY"]
    )
    rows = reader.observations(run_id, ticket_id, wait_for="communicate")
    assert {"open", "triage", "communicate"} <= {r["name"] for r in rows}
    return json.dumps(rows)


def _logs() -> str:
    log_dir = ROOT / load_env().get("LOG_DIR", "logs")
    return "\n".join(
        p.read_text(errors="replace") for p in sorted(log_dir.glob("*")) if p.is_file()
    )


async def _fresh_thread(run_a: str, run_b: str, ticket_id: str) -> None:
    agent = await build_agent(get_settings(AgentSettings))
    try:
        a = (await agent.app.aget_state(thread(run_a, ticket_id))).values
        b = (await agent.app.aget_state(thread(run_b, ticket_id))).values
        assert a and b and a["run_id"] == run_a and b["run_id"] == run_b
    finally:
        await agent.aclose()


@pytest.mark.parametrize("name", ["l1_pack", "handoff"])
def test_rows_written_and_name_only_in_store_message(name: str) -> None:
    run_a, run_b = str(uuid.uuid4()), str(uuid.uuid4())
    out = asyncio.run(main_async(FIXTURES / f"route_{name}.json", [], run_id=run_a, quiet=True))
    tid = out.state.ticket.ticket_id
    full_name, phone = _vault(tid)
    rows = _rows(run_a, tid)

    # itsm rows exist, the create_ticket row first.
    assert len(rows["ticket"]) == 1
    assert rows["idem"] and any(k.endswith(":open:create") for k in rows["idem"])
    first_itsm = next(json.loads(a) for a in rows["audit"] if json.loads(a)["step"] == "itsm")
    assert first_itsm["action"] == "create_ticket", first_itsm
    assert rows["messages"], "no store message"
    kinds = {c.split(":", 1)[0] for c in rows["comments"]}
    assert kinds == ({"l1_pack"} if name == "l1_pack" else {"l2_note"})

    # The real first name is in the store message, and nowhere else.
    first = full_name.split()[0]
    assert all(re.search(rf"\b{re.escape(first)}\b", m) for m in rows["messages"])
    sources = {
        "comments": "\n".join(rows["comments"]),
        "ticket": "\n".join(rows["ticket"]),
        "audit": "\n".join(rows["audit"]),
        "logs": _logs(),
        "trace": _trace(run_a, tid),
        "state": out.state.model_dump_json(),
    }
    leaks = {k: h for k, text in sources.items() if (h := _hits(text, full_name, phone))}
    assert not leaks, leaks

    # The same ticket under a second run_id: a fresh thread and fresh rows (B1).
    asyncio.run(main_async(FIXTURES / f"route_{name}.json", [], run_id=run_b, quiet=True))
    rows_b = _rows(run_b, tid)
    assert len(rows_b["ticket"]) == 1 and rows_b["messages"]
    assert set(rows_b["idem"]).isdisjoint(rows["idem"])
    assert all(k.startswith(f"{run_b}:{tid}:") for k in rows_b["idem"])
    asyncio.run(_fresh_thread(run_a, run_b, tid))
