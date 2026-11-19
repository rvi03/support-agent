"""`make demote [ACTION=restart_print_spooler]` (S12a): put an action back to supervised.

The demo and its rehearsal must meet the approval card every time, but with
ACTION_AUTONOMY_RUNS=1 one approval promotes the action. This is the admin path of
P5 (an operator acting as `admin`), run inside the itsm-actions container: each
device model's row is demoted through `autonomy.demote` with its history row, so
the audit trail shows who reset it and why. It never promotes.
"""

from __future__ import annotations

import asyncio
import sys

import psycopg

from support_agent.common.config import ItsmSettings, get_settings
from support_agent.common.db import dsn
from support_agent.mcp.base.opa import OpaClient
from support_agent.mcp.itsm import autonomy
from support_agent.mcp.itsm.registry import default_registry

SUBJECT = {"kind": "person", "client_id": "make-demote", "roles": ["admin"]}


async def demote_all(conninfo: str, policy: autonomy.Decider, action_id: str,
                     *, eval_mode: bool) -> list[tuple[str, str]]:  # fmt: skip
    """Demote every device model of `action_id`; returns (model, state after)."""
    action = default_registry().get(action_id)
    if action is None:
        raise ValueError(f"unknown action {action_id}")
    done: list[tuple[str, str]] = []
    async with await psycopg.AsyncConnection.connect(conninfo) as conn:
        cur = await conn.execute(
            "SELECT device_model FROM itsm.action_autonomy WHERE action_id = %s ORDER BY 1",
            (action_id,),
        )
        models = [str(r[0]) for r in await cur.fetchall()]
        for model in models:
            async with conn.transaction():
                after = await autonomy.demote(
                    conn, policy, action_id=action_id, tier=action.tier, model=model,
                    subject=SUBJECT, why="make demote (demo reset)", eval_mode=eval_mode,
                )  # fmt: skip
            if after is None:
                raise PermissionError(f"P5 refused the demotion of {action_id} on {model}")
            done.append((model, after.state))
    return done


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    action_id = args[0] if args else "restart_print_spooler"
    s = get_settings(ItsmSettings)
    conninfo = dsn(s.database_url_itsm, s.db_host)
    done = asyncio.run(demote_all(conninfo, OpaClient(s.opa_url), action_id,
                                  eval_mode=s.eval_mode))  # fmt: skip
    for model, state in done:
        print(f"{action_id} on {model}: {state}")
    if not done:
        print(f"{action_id}: no autonomy rows yet (already supervised)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
