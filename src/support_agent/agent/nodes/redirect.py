"""Redirect node (S10 build step 6): the fixed message for the approved destination key
Triage chose (D108); code owns the directory and contacts. Off-topic moderation
(no Triage) goes to `hr`. Gate check 8 allows only the rendered template."""

from __future__ import annotations

from typing import Any

from support_agent.agent.gate import GateOutput, GateResult
from support_agent.agent.messages import redirect
from support_agent.agent.runtime import GateBlocked, NodeCtx
from support_agent.agent.state import StoreDraft, TicketState


async def redirect_node(state: TicketState, ctx: NodeCtx) -> dict[str, Any]:
    key = state.policy.redirect_to if state.policy and state.policy.redirect_to else "hr"
    text = redirect(key)
    if text is None:
        raise GateBlocked(GateResult(False, 8, f"no_template:{key}"))
    gate = await ctx.check(
        GateOutput("store_message", text, "redirect", key), state.ticket.ticket_id
    )
    if not gate.ok:
        raise GateBlocked(gate)
    draft = StoreDraft(kind="redirect", text=text, key=key)
    return {"drafts": [*state.drafts, draft], "status": "redirected", "_audit": {"key": key}}
