"""Communicate node (S10 build step 9; agent-architecture.md, 8) as `agent-actor`.

Through itsm-actions, each write with its idem key (`run_id` + ticket + node + step):
update_ticket (route, category, priority, status, queue, SLA; runbook and kb_rev
once, on the final pass), add_comment (L1 pack), escalate_to_l2 (L2 note and
reason code), message_store (each new draft).

Every draft is gated again here (defense in depth). The real first name is put
back only inside `send_store_message`, after the gate: the filled text goes
straight to itsm and is never returned, logged or traced (review M3).
"""

from __future__ import annotations

from typing import Any

from support_agent.agent.gate import GateOutput
from support_agent.agent.messages import fill
from support_agent.agent.runtime import GateBlocked, NodeCtx
from support_agent.agent.state import StoreDraft, TicketState

QUEUE = {"escalated": "l2", "with_l1": "l1", "redirected": "store", "waiting_store": "store"}
ITSM_STATUS = {"with_l1": "in_progress", "in_progress": "in_progress"}
ITSM_ROUTE = {"human": "handoff"}


async def send_store_message(
    state: TicketState, ctx: NodeCtx, draft: StoreDraft, step: str
) -> None:
    """The reply sender: the vault name is read and filled here and goes only to itsm."""
    name = await ctx.deps.vault_name(state.ticket.ticket_id)
    await ctx.itsm.call(
        "message_store", "communicate", step, kind=draft.kind, body=fill(draft.text, name),
        section_id=draft.section_id,
    )  # fmt: skip


async def communicate_node(state: TicketState, ctx: NodeCtx) -> dict[str, Any]:
    tid = state.ticket.ticket_id
    final = state.status != "waiting_store"
    n = state.comm_pass  # one update key per pass (Clarify, final, a later SLA handoff)
    out = state.triage.output if state.triage else None
    fields: dict[str, Any] = {
        "status": ITSM_STATUS.get(state.status, state.status if state.status != "escalated"
                                  else "in_progress"),  # escalate_to_l2 sets escalated
        "assignee_queue": QUEUE.get(state.status),
    }  # fmt: skip
    if state.route:
        fields["route"] = ITSM_ROUTE.get(state.route.route, state.route.route)
    if out:
        fields["real_category"] = out.real_category
    if state.policy:
        fields |= {
            "priority": state.policy.priority,
            "first_response_by": state.policy.sla.first_response_by.isoformat(),
            "escalate_by": state.policy.sla.escalate_by.isoformat(),
            "resolve_by": state.policy.sla.resolve_by.isoformat(),
        }
    if final and out and out.runbook_id and state.triage and state.triage.kb_rev:
        fields |= {"runbook_id": out.runbook_id, "kb_rev": state.triage.kb_rev}
    await ctx.itsm.call("update_ticket", "communicate", f"update-{n}", **fields)
    if state.l1_pack_text and final:
        await ctx.itsm.call("add_comment", "communicate", "l1-pack", kind="l1_pack",
                            body=state.l1_pack_text)  # fmt: skip
    if state.summary_text and final:
        await ctx.itsm.call("add_comment", "communicate", "walk-summary", kind="note",
                            body=state.summary_text)  # fmt: skip
    if state.note_text and final:
        await ctx.itsm.call("escalate_to_l2", "communicate", "escalate", queue="l2",
                            reason_code=state.handoff_reason or "l2_needed",
                            note=state.note_text)  # fmt: skip
    for i, draft in enumerate(state.drafts[state.sent :], start=state.sent):
        gate = await ctx.check(GateOutput("store_message", draft.text, draft.kind, draft.key), tid)
        if not gate.ok:
            raise GateBlocked(gate)
        await send_store_message(state, ctx, draft, f"message-{i}")
    return {
        "sent": len(state.drafts),
        "comm_pass": state.comm_pass + 1,
        "_result": state.status,
        "_audit": {"messages": len(state.drafts) - state.sent,
                   "kinds": [d.kind for d in state.drafts[state.sent :]]},
    }  # fmt: skip
