"""S11 live walks: the real model on the `agent` alias, a scripted store (mock values only).

`make walk-live` runs three synthetic tickets (D39: no held-out ticket) and writes
eval/reports/walk_live.md:

- CP11.1 printer offline: the store reports "not fixed" until an IT action has run,
  then "it prints again now"; approvals are approved, L2 tasks report no change.
- CP11.4 steps already tried: the ticket says some steps were done (past tense), one
  was not done, one is planned and one is a question (D54); tried steps must never be
  sent, and only the past-tense ones may be marked tried.
- CP11.5 a POS model the runbook does not list (OrbitPOS on pos-screen-frozen): only
  generic steps, then HANDOFF `version_not_covered` with the gap event.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from support_agent.agent.app import Agent, build_agent
from support_agent.agent.graph import RunOutcome, resume, run_ticket
from support_agent.cli.ticket_local import initial_state, intake
from support_agent.common.config import AgentSettings, get_settings

ROOT = Path(__file__).resolve().parents[3]
REPORT = ROOT / "eval" / "reports" / "walk_live.md"
MAX_PAUSES = 10

NOT_FIXED = (
    "Done. The power light is on, the USB cable is firmly connected at both ends, and the "
    "self-test page printed fine. The POS still shows the printer Offline."
)
FIXED = "Done. It prints again now, the test receipt came out."


def _raw(
    tid: str, store: str, asset: str, category: str, subject: str, text: str
) -> dict[str, Any]:
    return {
        "store_id": store, "store_name": "ServeWell - Mock",
        "date_opened": datetime(2026, 3, 10, 4, 0, tzinfo=UTC).isoformat(),
        "submitted_by": "Testa Mockwell", "contact_phone": "+91-90000-00001", "priority": "P3",
        "ticket_id": tid, "category": category, "asset_id": asset, "system_version": None,
        "subject": subject, "description": text,
    }  # fmt: skip


@dataclass
class Case:
    name: str
    raw: dict[str, Any]
    replies: list[str] = field(default_factory=list)


def cases() -> list[Case]:
    n = uuid.uuid4().hex[:6].upper()
    return [
        Case("CP11.1 printer to fixed", _raw(
            f"LOCAL-LIVE-PO-{n}", "SW-0003", "PRN-0003-P1", "Printers",
            "Receipt printer shows offline",
            "Receipt printer P1 at the front counter shows Offline in the POS since this "
            "morning. Print jobs queue but nothing comes out.")),
        Case("CP11.4 steps already tried", _raw(
            f"LOCAL-LIVE-TRIED-{n}", "SW-0003", "PRN-0003-P1", "Printers",
            "Receipt printer offline again",
            "The receipt printer shows Offline in the POS. We restarted the POS application "
            "twice already and we ran the printer self-test, which printed fine. I didn't "
            "restart the spooler. I will reseat the cable after lunch. Should I power cycle "
            "the printer?")),
        Case("CP11.5 version not covered", _raw(
            f"LOCAL-LIVE-ORBIT-{n}", "SW-0044", "POS-0044-T1", "POS",
            "POS touchscreen frozen",
            "The POS touchscreen shows the menu but accepts no input; taps and swipes produce "
            "no response for the last few minutes.")),
    ]  # fmt: skip


def _payload(out: RunOutcome, case: Case) -> dict[str, Any]:
    kind = str((out.paused or {}).get("kind"))
    if kind == "approval":
        return {"decision": "approve", "decided_by": "l2-mock"}
    if kind == "l2_task":
        return {"result": "done", "note": "L2 did the step; no change.", "done_by": "l2-mock"}
    walk = out.state.walk
    if case.name.startswith("CP11.5"):
        return {"text": "Done, the screen is still frozen."}
    ran = bool(walk and any(s.kind == "action" for s in walk.steps))
    return {"text": FIXED if ran else NOT_FIXED}


async def run_case(agent: Agent, case: Case) -> dict[str, Any]:
    result = intake(case.raw)
    run_id = str(uuid.uuid4())
    out = await run_ticket(agent.app, initial_state(result, run_id), locker=agent.locker)
    pauses = 0
    while out.paused and pauses < MAX_PAUSES:
        pauses += 1
        payload = _payload(out, case)
        case.replies.append(f"{out.paused['kind']}: {payload}")
        out = await resume(agent.app, agent.deps, run_id, result.ticket.ticket_id,
                           str(out.paused["pending_id"]), str(out.paused["kind"]), payload,
                           locker=agent.locker)  # fmt: skip
    s = out.state
    walk = s.walk
    return {
        "case": case.name, "ticket_id": s.ticket.ticket_id, "run_id": run_id,
        "route": s.route.route if s.route else None, "status": s.status,
        "reason": s.handoff_reason, "calls": s.llm_calls, "tokens": s.tokens, "cost": s.cost_usd,
        "steps": [(x.step_id, x.kind, x.outcome) for x in walk.steps] if walk else [],
        "tried": [t.step_id for t in walk.tried] if walk else [],
        "version": walk.version if walk else None, "connection": walk.connection if walk else None,
        "end": walk.end_reason if walk else None, "paused_left": out.paused is not None,
        "kinds": [d.kind for d in s.drafts],
    }  # fmt: skip


def _checks(r: dict[str, Any]) -> list[str]:
    fails: list[str] = []
    sent = [s for s, k, _ in r["steps"]]
    if r["case"].startswith("CP11.1"):
        if r["status"] != "resolved":
            fails.append(f"not resolved: {r['status']} {r['reason']}")
        if not any(k == "action" for _, k, _ in r["steps"]):
            fails.append("no IT action ran")
        if r["status"] == "resolved" and "summary" not in r["kinds"]:
            fails.append("no summary message")
    if r["case"].startswith("CP11.4"):
        bad = set(r["tried"]) - {"po-restart-pos-app", "po-self-test"}
        if bad:
            fails.append(f"marked tried without past-tense words: {sorted(bad)}")
        resent = set(r["tried"]) & set(sent)
        if resent:
            fails.append(f"tried step sent again: {sorted(resent)}")
    if r["case"].startswith("CP11.5"):
        from support_agent.agent.bindings import default_bindings

        b = {x.id: x for x in default_bindings().for_runbook("runbooks/pos-screen-frozen.md")}
        non_generic = [s for s in sent if s in b and not b[s].generic]
        if non_generic:
            fails.append(f"non-generic steps sent: {non_generic}")
        if r["reason"] != "version_not_covered":
            fails.append(f"reason {r['reason']}")
        if r["version"] not in ("not_covered", "unclear"):
            fails.append(f"version judged {r['version']}")
    if r["paused_left"]:
        fails.append("still paused after the pause cap")
    return fails


async def main() -> int:
    s = get_settings(AgentSettings)
    agent = await build_agent(s)
    results = []
    try:
        for case in cases():
            r = await run_case(agent, case)
            r["replies"] = case.replies
            results.append(r)
    finally:
        await agent.aclose()
    lines = [f"# S11 live walks ({datetime.now(UTC):%Y-%m-%d %H:%M} UTC)", "",
             "Real model on the `agent` alias; scripted store, approver and L2 (mock values).",
             ""]  # fmt: skip
    ok = True
    for r in results:
        fails = _checks(r)
        ok = ok and not fails
        lines += [
            f"## {r['case']}: {'PASS' if not fails else 'FAIL'}",
            f"- ticket {r['ticket_id']}, route {r['route']}, status {r['status']}, "
            f"reason {r['reason'] or '-'}; LLM calls {r['calls']}, tokens {r['tokens']}, "
            f"cost ${r['cost']:.4f}",
            f"- version {r['version']}, connection {r['connection']}, tried {r['tried']}",
            "- steps: " + (", ".join(f"{s} ({k}: {o})" for s, k, o in r["steps"]) or "none"),
            f"- end: {r['end'] or '-'}",
            *(f"- FAIL: {f}" for f in fails),
            "",
        ]
    REPORT.write_text("\n".join(lines))
    print("\n".join(lines))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
