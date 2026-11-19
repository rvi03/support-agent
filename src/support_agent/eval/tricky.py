"""CP10.2 (S10): the tune-half tricky tickets through the full graph.

Reads eval/tricky_tune.yaml (expected routes per ticket, hand-judged by the K9
rules), runs each masked source ticket through the graph as the agent (same
servers, itsm writes under a fresh run_id), and stops at a Clarify pause (the
question is the outcome). Writes eval/reports/tricky_tune.md. Tune half only:
a held-out id in the file stops the run (D39).
"""

from __future__ import annotations

import asyncio
import statistics
import sys
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import yaml

from support_agent.agent.app import build_agent
from support_agent.agent.graph import RunOutcome, run_ticket
from support_agent.agent.state import TicketState
from support_agent.common.config import AgentSettings, get_settings
from support_agent.eval.agent_run import ROOT, Harness

SPEC = ROOT / "eval" / "tricky_tune.yaml"
REPORT = ROOT / "eval" / "reports" / "tricky_tune.md"
CONCURRENCY = 4


@dataclass
class Row:
    spec: dict[str, Any]
    outcome: RunOutcome | None
    error: str | None = None

    @property
    def route(self) -> str:
        s = self.outcome.state if self.outcome else None
        return s.route.route if s and s.route else "-"

    @property
    def ok(self) -> bool:
        if self.outcome is None:
            return False
        s = self.outcome.state
        out = s.triage.output if s.triage else None
        if self.route not in self.spec["routes"]:
            return False
        if "real_category" in self.spec and (
            not out or out.real_category != self.spec["real_category"]
        ):
            return False
        if "redirect_to" in self.spec and (
            not s.policy or s.policy.redirect_to != self.spec["redirect_to"]
        ):
            return False
        return s.failed_node is None


async def run(alias: str | None = None) -> int:
    spec = yaml.safe_load(SPEC.read_text())
    h = Harness(alias or "agent")  # the tune-half reader (refuses held-out ids)
    agent = await build_agent(get_settings(AgentSettings), model_alias=alias)
    sem = asyncio.Semaphore(CONCURRENCY)

    async def one(item: dict[str, Any]) -> Row:
        async with sem:
            ticket = h.ticket(item["id"])
            state = TicketState(
                ticket=ticket,
                run_id=str(uuid.uuid4()),
                clock_offset_s=(ticket.date_opened - datetime.now(UTC)).total_seconds(),
            )
            try:
                return Row(item, await run_ticket(agent.app, state, locker=agent.locker))
            except Exception as exc:  # reported as a fail, never dropped
                return Row(item, None, f"{type(exc).__name__}: {exc}"[:200])

    try:
        rows = list(await asyncio.gather(*(one(i) for i in spec["tickets"])))
    finally:
        await agent.aclose()
    lines = [
        f"# Tricky tickets on the tune half (S10, CP10.2), {spec['version']}",
        "",
        f"Model alias `{alias or 'agent'}`, {datetime.now(UTC):%Y-%m-%d %H:%M} UTC, full graph "
        "(Enrich, Triage, Policy, Router, handler, gate, Communicate). Expected routes are hand "
        "judgements by the K9 rules (eval/tricky_tune.yaml). A Clarify run stops at the pause.",
        "",
        "| Ticket | Type | Example | Expected | Agent route (rule) | Triage | Category | Reason "
        "| Pass |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    by_type: dict[str, list[bool]] = {}
    for r in rows:
        s = r.outcome.state if r.outcome else None
        out = s.triage.output if s and s.triage else None
        by_type.setdefault(r.spec["type"], []).append(r.ok)
        rule = s.route.rule if s and s.route else "-"
        lines.append(
            f"| {r.spec['id']} | {r.spec['type']} | {'yes' if r.spec.get('example') else ''} | "
            f"{', '.join(r.spec['routes'])} | {r.route} ({rule}) | "
            f"{out.route if out else r.error or '-'} | {out.real_category if out else '-'} | "
            f"{s.handoff_reason if s else '-'} | {'yes' if r.ok else 'NO'} |"
        )
    passed = sum(r.ok for r in rows)
    non_example = [r for r in rows if not r.spec.get("example")]
    lines += [
        "",
        f"- Expected route: **{passed}/{len(rows)}**; without the few-shot examples "
        f"{sum(r.ok for r in non_example)}/{len(non_example)}.",
        "- Per type: " + "; ".join(f"{t} {sum(v)}/{len(v)}" for t, v in sorted(by_type.items())),
        f"- Tokens per ticket mean "
        f"{statistics.mean(r.outcome.state.tokens for r in rows if r.outcome):.0f}.",
        "",
    ]
    for r in rows:
        if not r.ok and r.outcome:
            out = r.outcome.state.triage.output if r.outcome.state.triage else None
            lines.append(f"- {r.spec['id']} miss: Triage said {out.route if out else '-'}: "
                         f"{out.reason if out else '-'}")  # fmt: skip
    REPORT.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0 if passed == len(rows) else 1


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    return asyncio.run(run(args[0] if args else None))


if __name__ == "__main__":
    raise SystemExit(main())
