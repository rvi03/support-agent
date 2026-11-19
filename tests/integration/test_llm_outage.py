"""CP10.5 outage, live (`make up`): an LLM outage hands off instead of stalling (X16).

The agent runs on the LiteLLM alias `agent-dead`, whose upstream port is dead
(compose/litellm/config.yaml). LiteLLM retries (`num_retries`), the agent's
client retries with backoff, and then the ticket ends in HANDOFF with reason
`llm_unavailable`, the code-built fallback note and the L2 status message,
well within the retry budget. Mock values only (D70).
"""

from __future__ import annotations

import asyncio
import time
import uuid
from pathlib import Path

import pytest

from support_agent.agent.app import build_agent
from support_agent.agent.graph import RunOutcome, run_ticket
from support_agent.cli.ticket_local import initial_state, intake
from support_agent.common.config import AgentSettings, get_settings

pytestmark = pytest.mark.integration
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "tickets" / "route_handoff.json"
BUDGET_S = 180  # both nodes' retries with backoff, far below a stalled ticket


async def _run() -> RunOutcome:
    import json

    result = intake(json.loads(FIXTURE.read_text()))
    agent = await build_agent(get_settings(AgentSettings), model_alias="agent-dead")
    try:
        state = initial_state(result, str(uuid.uuid4()))
        return await run_ticket(agent.app, state, locker=agent.locker)
    finally:
        await agent.aclose()


def test_llm_outage_hands_off_with_the_fallback_note() -> None:
    started = time.monotonic()
    out = asyncio.run(_run())
    elapsed = time.monotonic() - started
    s = out.state
    assert out.paused is None
    assert s.handoff_reason == "llm_unavailable", (s.handoff_reason, s.failed_node)
    assert s.triage is not None and s.triage.handoff_reason == "llm_unavailable"
    assert s.status == "escalated"
    assert s.note_source == "fallback" and s.note_text
    assert "Escalation reason: llm_unavailable" in s.note_text
    assert [d.kind for d in s.drafts] == ["status_template"]
    assert elapsed < BUDGET_S, elapsed
