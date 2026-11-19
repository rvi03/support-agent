"""`make ticket-local FILE=...` (S10 build step 11): intake -> graph in-process, no API.

Runs the ticket file through intake (schema, vault as `intake_rw`, masking, safety
net, moderation), then the graph as the agent, and prints the route, the store
messages (with `{name}` still in place: the filled text goes only to itsm), the
L2 note or L1 pack, and the audit trail. A pause asks on the terminal, or takes
the answers from `ANSWERS` (one per line, for scripted runs).

Replay clock (D48): ticket time starts at the file's `date_opened`.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg

from support_agent.agent.app import build_agent
from support_agent.agent.graph import RunOutcome, resume, run_ticket
from support_agent.agent.state import TicketState
from support_agent.common.audit import AuditEvent, write_event
from support_agent.common.config import AgentSettings, IntakeSettings, get_settings
from support_agent.common.db import dsn
from support_agent.intake.masker import Masker
from support_agent.intake.moderation import ModerationBudget, ModerationClient, Moderator
from support_agent.intake.pipeline import IntakeResult, process_ticket
from support_agent.intake.reference import load_reference
from support_agent.intake.safety_net import SafetyNet
from support_agent.intake.vault import write_vault


def intake(raw: dict[str, Any]) -> IntakeResult:
    s = get_settings(IntakeSettings)
    conn = psycopg.connect(dsn(s.database_url_intake, s.db_host), autocommit=True)
    try:
        reference = load_reference(conn)

        def audit(event: AuditEvent) -> int:
            return write_event(conn, event)

        net = SafetyNet(reference, audit, actor="intake")
        moderator = Moderator(
            ModerationClient(
                s.litellm_base_url, s.litellm_master_key.get_secret_value(),
                model=s.model_moderation,
            ),
            net,
            audit,
        )  # fmt: skip
        result = process_ticket(
            raw, Masker(reference), safety_net=net, moderator=moderator,
            budget=ModerationBudget(s.moderation_max_calls),
        )  # fmt: skip
        write_vault(conn, result.ticket.ticket_id, result.contact, result.mask_map)
        return result
    finally:
        conn.close()


def initial_state(
    result: IntakeResult, run_id: str, *, wall: datetime | None = None
) -> TicketState:
    mod = result.moderation
    label = "failed" if mod is not None and mod.failed else (mod.label.value if mod else "ok")
    now = wall or datetime.now(UTC)
    return TicketState(
        ticket=result.ticket,
        run_id=run_id,
        clock_offset_s=(result.ticket.date_opened - now).total_seconds(),
        moderation_label=label,
        moderation_calls=1 if mod else 0,
    )


def _question(outcome: RunOutcome) -> str:
    paused = outcome.paused or {}
    if paused.get("kind") == "approval":
        card = paused.get("approval") or {}
        return (f"approve {card.get('action_id')} ({card.get('tier')}) for '{card.get('step')}'? "
                "answer 'approve' or 'reject: <reason>'")  # fmt: skip
    if paused.get("kind") == "l2_task":
        return "L2 task result? answer 'done: <note>' or 'failed: <note>'"
    return outcome.state.drafts[-1].text if outcome.state.drafts else "?"


def payload_for(kind: str, answer: str) -> dict[str, Any]:
    """A terminal answer as the resume payload of its pause kind (S11)."""
    head, _, rest = answer.partition(":")
    if kind == "approval":
        decision = "reject" if head.strip().lower().startswith("reject") else "approve"
        return {"decision": decision, "decided_by": "l2-local", "reason": rest.strip() or None}
    if kind == "l2_task":
        result = "failed" if head.strip().lower().startswith("fail") else "done"
        return {"result": result, "note": rest.strip() or result, "done_by": "l2-local"}
    return {"text": answer}


def show(outcome: RunOutcome, trail: list[str]) -> None:
    s = outcome.state
    route = s.route.route if s.route else "-"
    rule = s.route.rule if s.route else "-"
    out = s.triage.output if s.triage else None
    print(f"\n== {s.ticket.ticket_id} run {s.run_id}")
    print(f"route: {route} (line {rule}); triage: {out.route if out else '-'}; "
          f"status: {s.status}; handoff reason: {s.handoff_reason or '-'}")  # fmt: skip
    print(f"priority: {s.policy.priority if s.policy else '-'}; runbook: "
          f"{out.runbook_id if out else '-'}; LLM calls {s.llm_calls}, tokens {s.tokens}, "
          f"cost ${s.cost_usd:.4f}")  # fmt: skip
    for d in s.drafts:
        print(f"store message [{d.kind}{':' + d.key if d.key else ''}]: {d.text}")
    if s.note_text:
        print(f"L2 note ({s.note_source}):\n  " + s.note_text.replace("\n", "\n  "))
    if s.l1_pack_text:
        print("L1 pack:\n  " + s.l1_pack_text.replace("\n", "\n  "))
    print("audit trail: " + " -> ".join(trail))


async def main_async(
    path: Path, answers: list[str], *, run_id: str | None = None, quiet: bool = False
) -> RunOutcome:
    raw = json.loads(path.read_text())
    result = intake(raw)
    agent = await build_agent(get_settings(AgentSettings))
    trail: list[str] = []
    real_audit = agent.deps.audit

    async def audit(event: AuditEvent) -> int:
        extra = {k: event.payload[k] for k in ("error", "misses") if event.payload.get(k)}
        trail.append(
            f"{event.action}:{event.result}"
            + (f"({event.reason})" if event.reason else "")
            + (f" {extra}" if extra else "")
        )
        return await real_audit(event)

    agent.deps.audit = audit
    run_id = run_id or os.environ.get("RUN_ID") or str(uuid.uuid4())
    try:
        outcome = await run_ticket(agent.app, initial_state(result, run_id), locker=agent.locker)
        while outcome.paused:
            kind = str(outcome.paused["kind"])
            question = _question(outcome)
            if not quiet:
                print(f"\n[paused: {kind}] {question}")
            answer = answers.pop(0) if answers else input("answer> ")
            if not quiet:
                print(f"answer> {answer}")
            outcome = await resume(
                agent.app, agent.deps, run_id, result.ticket.ticket_id,
                str(outcome.paused["pending_id"]), kind, payload_for(kind, answer),
                locker=agent.locker,
            )  # fmt: skip
        if not quiet:
            show(outcome, trail)
        return outcome
    finally:
        await agent.aclose()


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        raise SystemExit("usage: python -m support_agent.cli.ticket_local FILE")
    answers = [a for a in os.environ.get("ANSWERS", "").split("\n") if a.strip()]
    asyncio.run(main_async(Path(args[0]), answers))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
