"""CP10.6 and CP10.5 (S10): the 40 model-check tune tickets through the full graph.

- K15a (CP10.6): every L2 note the run stored (`itsm.ticket_comments`, kind
  `l2_note`; read back as the note text the agent sent) passes the independent
  checker (eval/k15a.py). The code-built fallback note for each of the 40 is
  built from the final state and must pass too.
- K14 first look (CP10.5): time and cost per ticket from the run's Langfuse
  trace (span start to end; the generation costs LiteLLM reported), beside the
  agent's own counters. A $0 cost means LiteLLM's price map does not know the
  model (D64: add its prices to the alias's `model_info`).

Writes eval/reports/k15a_tune.md and eval/reports/k14_first_look.md. Tune half
only: the harness refuses held-out ids (D39).
"""

from __future__ import annotations

import asyncio
import json
import statistics
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from support_agent.agent.app import build_agent
from support_agent.agent.graph import RunOutcome, run_ticket
from support_agent.agent.notes import build_fallback_note
from support_agent.agent.state import TicketState
from support_agent.common.config import AgentSettings, get_settings
from support_agent.eval import k15a
from support_agent.eval.agent_run import MODEL_CHECK, ROOT, Harness
from support_agent.eval.traces import LangfuseReader, TraceMissingError

K15A_REPORT = ROOT / "eval" / "reports" / "k15a_tune.md"
K14_REPORT = ROOT / "eval" / "reports" / "k14_first_look.md"
CONCURRENCY = 4


@dataclass
class Row:
    ticket_id: str
    outcome: RunOutcome | None
    seconds: float
    error: str | None = None
    trace_seconds: float | None = None
    trace_cost: float | None = None
    generations: int = 0


def _iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _trace_numbers(rows: list[dict[str, Any]]) -> tuple[float, float, int]:
    starts = [_iso(r["startTime"]) for r in rows if r.get("startTime")]
    ends = [_iso(r["endTime"]) for r in rows if r.get("endTime")]
    gens = [r for r in rows if r.get("type") == "GENERATION"]
    cost = sum(float(r.get("totalCost") or 0.0) for r in gens)
    return (max(ends) - min(starts)).total_seconds(), cost, len(gens)


def _pct(values: list[float], q: float) -> float:
    s = sorted(values)
    return s[min(len(s) - 1, int(q * len(s)))]


async def run() -> int:
    spec = json.loads(MODEL_CHECK.read_text())
    ids: list[str] = spec["group_a"] + spec["mixed"]
    h = Harness("agent")
    settings = get_settings(AgentSettings)
    agent = await build_agent(settings)
    sem = asyncio.Semaphore(CONCURRENCY)

    async def one(tid: str) -> Row:
        async with sem:
            ticket = h.ticket(tid)
            state = TicketState(
                ticket=ticket,
                run_id=str(uuid.uuid4()),
                clock_offset_s=(ticket.date_opened - datetime.now(UTC)).total_seconds(),
            )
            started = time.monotonic()
            try:
                out = await run_ticket(agent.app, state, locker=agent.locker)
                return Row(tid, out, time.monotonic() - started)
            except Exception as exc:  # reported as a fail, never dropped
                return Row(tid, None, time.monotonic() - started, f"{type(exc).__name__}: {exc}")

    try:
        rows = list(await asyncio.gather(*(one(t) for t in ids)))
    finally:
        await agent.aclose()

    # Traces (after the flush in aclose).
    if settings.langfuse_public_key and settings.langfuse_secret_key and settings.langfuse_host:
        reader = LangfuseReader(
            settings.langfuse_host,
            settings.langfuse_public_key.get_secret_value(),
            settings.langfuse_secret_key.get_secret_value(),
        )
        for r in rows:
            if r.outcome is None:
                continue
            try:
                obs = reader.observations(
                    r.outcome.state.run_id, r.ticket_id, wait_for="communicate", timeout_s=120
                )
                r.trace_seconds, r.trace_cost, r.generations = _trace_numbers(obs)
            except TraceMissingError as exc:
                r.error = (r.error or "") + f" trace: {exc}"

    k15_ok = _k15a_report(rows)
    k14_ok = _k14_report(rows)
    return 0 if k15_ok and k14_ok else 1


def _k15a_report(rows: list[Row]) -> bool:
    now = datetime.now(UTC)
    lines = [
        "# K15a on the 40 model-check tune tickets (S10, CP10.6)",
        "",
        f"{now:%Y-%m-%d %H:%M} UTC, full graph, model alias `agent`. Checker: eval/k15a.py "
        "(independent of the agent, D42). Measured in S10, when the Resolver was a stub and "
        "Group A L1 tickets also handed off; since S11 they walk and pause for the store, so "
        "a rerun needs the S14 store simulator.",
        "",
        "| Ticket | Route | Reason | Note source | Note K15a | Fallback K15a | Problems |",
        "|---|---|---|---|---|---|---|",
    ]
    notes = notes_ok = fallback_ok = 0
    for r in rows:
        if r.outcome is None:
            lines.append(f"| {r.ticket_id} | error | {r.error} | - | NO | NO | run failed |")
            continue
        s = r.outcome.state
        fb = k15a.check(build_fallback_note(s, now).render())
        fallback_ok += fb.ok
        note = k15a.check(s.note_text) if s.note_text else None
        if note:
            notes += 1
            notes_ok += note.ok
        probs = "; ".join(
            [*(note.problems if note else []), *(f"fallback {p}" for p in fb.problems)]
        )
        lines.append(
            f"| {r.ticket_id} | {s.route.route if s.route else '-'} | {s.handoff_reason or '-'} | "
            f"{s.note_source or '-'} | {('yes' if note.ok else 'NO') if note else 'no note'} | "
            f"{'yes' if fb.ok else 'NO'} | {probs or '-'} |"
        )
    failed = sum(r.outcome is None for r in rows)
    lines += [
        "",
        f"- L2 notes stored: {notes}; pass K15a: **{notes_ok}/{notes}** (target 100%).",
        f"- Code-built fallback note for every ticket: **{fallback_ok}/{len(rows)}** pass.",
        f"- Runs failed: {failed} (a failed run counts as a fail, D56).",
        "",
    ]
    K15A_REPORT.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return failed == 0 and notes_ok == notes and fallback_ok == len(rows)


def _k14_report(rows: list[Row]) -> bool:
    done = [r for r in rows if r.outcome is not None]
    traced = [r for r in done if r.trace_seconds is not None]
    wall = [r.seconds for r in done]
    tokens = [r.outcome.state.tokens for r in done if r.outcome]
    calls = [r.outcome.state.llm_calls for r in done if r.outcome]
    own_cost = [r.outcome.state.cost_usd for r in done if r.outcome]
    tr_sec = [r.trace_seconds for r in traced if r.trace_seconds is not None]
    tr_cost = [r.trace_cost for r in traced if r.trace_cost is not None]

    def stats(v: list[float], fmt: str) -> str:
        if not v:
            return "-"
        return " / ".join(
            format(x, fmt) for x in (statistics.mean(v), _pct(v, 0.5), _pct(v, 0.95), max(v))
        )

    zero_cost = [r.ticket_id for r in traced if r.generations and not r.trace_cost]
    lines = [
        "# K14 first look: time and cost per ticket (S10, CP10.5)",
        "",
        f"{datetime.now(UTC):%Y-%m-%d %H:%M} UTC; the 40 model-check tune tickets through the "
        f"full graph, {CONCURRENCY} at a time, model alias `agent` (gpt-6-luna). Before S11: the "
        "Resolver is a stub, so a Group A walk is not in these numbers yet.",
        "",
        "| Measure | mean / p50 / p95 / max |",
        "|---|---|",
        f"| Wall time per ticket, s (agent clock) | {stats(wall, '.1f')} |",
        f"| Trace time per ticket, s (Langfuse, first to last span) | {stats(tr_sec, '.1f')} |",
        f"| Cost per ticket, USD (Langfuse generations) | {stats(tr_cost, '.4f')} |",
        f"| Cost per ticket, USD (agent's counter, LiteLLM header) | {stats(own_cost, '.4f')} |",
        f"| Tokens per ticket | {stats([float(t) for t in tokens], '.0f')} |",
        f"| LLM calls per ticket | {stats([float(c) for c in calls], '.1f')} |",
        "",
        f"- Tickets run: {len(done)}/{len(rows)}; traces found: {len(traced)}/{len(done)}.",
        f"- Total cost of the 40 (Langfuse): ${sum(tr_cost):.4f}; agent counter "
        f"${sum(own_cost):.4f}.",
        f"- Tickets with LLM calls but $0 cost: {len(zero_cost)}"
        + (
            f" ({', '.join(zero_cost)}): add prices to the alias's model_info (D64)."
            if zero_cost
            else "."
        ),  # fmt: skip
        "- Target: set in S14 from run 1 (kpis.md K14); the token budget per ticket is "
        "120k (D104).",
        "",
    ]
    K14_REPORT.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return len(traced) == len(done) == len(rows) and not zero_cost


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(run())


if __name__ == "__main__":
    raise SystemExit(main())
