"""Action autonomy per (action_id, device model) (S7 build step 5; D37, D47, P5).

- `next_state` is the pure rule: a reversible action counts approved, successful
  runs in a row and becomes a promotion candidate at `ACTION_AUTONOMY_RUNS`; any
  reject or failure sends it back to supervised with the count at 0; read_only is
  never tracked and destructive is never promoted.
- `record_result` applies it inside the caller's transaction: it locks the row,
  asks OPA P5 before a promotion, writes the history row and an
  `action_promoted` / `action_demoted` audit event. Only `run_fix` and
  `decide_approval` call it, so no caller can skip or fake the record.
- In eval mode the history row is written but nothing is promoted (D47).
- `demote` is the admin path (P5); there is no promote entry point.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from psycopg import AsyncConnection

from support_agent.common.audit import AuditEvent, awrite_event
from support_agent.mcp.itsm.registry import Tier

State = Literal["supervised", "autonomous"]
SERVICE_ID = "itsm-actions"
P5 = "servewell/p5_autonomy"

Conn = AsyncConnection[Any]


class Decider(Protocol):
    async def decide(
        self, package: str, policy_input: dict[str, Any], /
    ) -> dict[str, Any] | None: ...


@dataclass(frozen=True)
class Autonomy:
    state: State = "supervised"
    runs: int = 0


@dataclass(frozen=True)
class Step:
    after: Autonomy
    promote: bool  # a candidate; P5 and eval mode still decide
    why: str


def next_state(tier: Tier, now: Autonomy, *, approved: bool, success: bool, threshold: int) -> Step:
    """`approved`: the run had a granted approval (False for a reject or an autonomous
    run); `success`: the action ran without failing (False for a reject)."""
    if tier == "read_only":
        return Step(now, False, "read_only_not_tracked")
    if not success:
        return Step(Autonomy("supervised", 0), False, "failed_or_rejected")
    if now.state == "autonomous":
        return Step(Autonomy("autonomous", now.runs + 1), False, "autonomous_run_ok")
    if not approved:
        return Step(now, False, "unapproved_run")
    runs = now.runs + 1
    if tier == "reversible" and runs >= threshold:
        return Step(Autonomy("supervised", runs), True, f"{runs}_approved_runs_in_a_row")
    return Step(Autonomy("supervised", runs), False, "approved_run_ok")


async def _lock(conn: Conn, action_id: str, model: str) -> Autonomy:
    await conn.execute(
        "INSERT INTO itsm.action_autonomy (action_id, device_model) VALUES (%s, %s) "
        "ON CONFLICT DO NOTHING",
        (action_id, model),
    )
    cur = await conn.execute(
        "SELECT state, runs_in_a_row FROM itsm.action_autonomy "
        "WHERE action_id = %s AND device_model = %s FOR UPDATE",
        (action_id, model),
    )
    row = await cur.fetchone()
    if row is None:
        raise RuntimeError(f"autonomy row missing for {action_id}/{model}")
    return Autonomy(row[0], int(row[1]))


async def current(conn: Conn, action_id: str, model: str, *, lock: bool = False) -> Autonomy:
    if lock:
        return await _lock(conn, action_id, model)
    cur = await conn.execute(
        "SELECT state, runs_in_a_row FROM itsm.action_autonomy "
        "WHERE action_id = %s AND device_model = %s",
        (action_id, model),
    )
    row = await cur.fetchone()
    return Autonomy(row[0], int(row[1])) if row else Autonomy()


async def _save(
    conn: Conn,
    *,
    action_id: str,
    model: str,
    before: Autonomy,
    after: Autonomy,
    event: str,
    approved: bool | None,
    success: bool | None,
    eval_mode: bool,
    why: str,
    run_id: uuid.UUID | None,
    ticket_id: str | None,
    actor: str,
    tier: Tier,
) -> None:
    if after != before:
        await conn.execute(
            "UPDATE itsm.action_autonomy SET state = %s, runs_in_a_row = %s, "
            "changed_at = now(), why = %s WHERE action_id = %s AND device_model = %s",
            (after.state, after.runs, why, action_id, model),
        )
    await conn.execute(
        "INSERT INTO itsm.action_autonomy_history (action_id, device_model, run_id, ticket_id, "
        "event, approved, success, state_before, state_after, runs_before, runs_after, "
        "eval_mode, why) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            action_id, model, run_id, ticket_id, event, approved, success, before.state,
            after.state, before.runs, after.runs, eval_mode, why,
        ),
    )  # fmt: skip
    change = None
    if before.state == "supervised" and after.state == "autonomous":
        change = "action_promoted"
    elif before.state == "autonomous" and after.state == "supervised":
        change = "action_demoted"
    elif after.runs == 0 and before.runs > 0:
        change = "action_demoted"  # the count reset is a demotion of progress too
    if change:
        await awrite_event(
            conn,
            AuditEvent(
                step="itsm.autonomy",
                actor=actor,
                action=change,
                result=after.state,
                reason=why,
                source=SERVICE_ID,
                run_id=run_id,
                ticket_id=ticket_id,
                action_id=action_id,
                tier=tier,
                autonomy_state=after.state,
                payload={"device_model": model, "runs_before": before.runs,
                         "runs_after": after.runs, "eval_mode": eval_mode},
            ),
        )  # fmt: skip


async def record_result(
    conn: Conn,
    policy: Decider,
    *,
    action_id: str,
    tier: Tier,
    model: str,
    approved: bool,
    success: bool,
    threshold: int,
    eval_mode: bool,
    run_id: uuid.UUID | None,
    ticket_id: str | None,
    actor: str,
    event: Literal["run", "reject"] = "run",
) -> Autonomy:
    """Record one run (or a reject) in the caller's transaction; returns the new state."""
    if tier == "read_only":
        return Autonomy()
    before = await _lock(conn, action_id, model)
    step = next_state(tier, before, approved=approved, success=success, threshold=threshold)
    after, why = step.after, step.why
    if step.promote:
        decision = await policy.decide(
            P5,
            {
                "action": "promote",
                "subject": {"kind": "service", "client_id": SERVICE_ID, "roles": []},
                "resource": {
                    "tier": tier, "runs_in_a_row": after.runs, "threshold": threshold,
                    "eval_mode": eval_mode,
                },
            },
        )  # fmt: skip
        if decision is not None and decision.get("allow") is True:
            after, why = Autonomy("autonomous", after.runs), why + "_promoted"
        else:
            why += "_eval_mode_no_promotion" if eval_mode else "_promotion_refused"
    await _save(
        conn, action_id=action_id, model=model, before=before, after=after, event=event,
        approved=approved, success=success, eval_mode=eval_mode, why=why, run_id=run_id,
        ticket_id=ticket_id, actor=actor, tier=tier,
    )  # fmt: skip
    return after


async def demote(
    conn: Conn,
    policy: Decider,
    *,
    action_id: str,
    tier: Tier,
    model: str,
    subject: dict[str, Any],
    why: str,
    eval_mode: bool,
) -> Autonomy | None:
    """Admin demotion (P5): None if OPA refuses. Run inside a transaction."""
    decision = await policy.decide(
        P5, {"action": "demote", "subject": subject, "resource": {"tier": tier}}
    )
    if decision is None or decision.get("allow") is not True:
        return None
    before = await _lock(conn, action_id, model)
    after = Autonomy("supervised", 0)
    await _save(
        conn, action_id=action_id, model=model, before=before, after=after,
        event="admin_demote", approved=None, success=None, eval_mode=eval_mode,
        why=f"admin_demote: {why}"[:300], run_id=None, ticket_id=None,
        actor=str(subject.get("client_id", "unknown")), tier=tier,
    )  # fmt: skip
    return after
