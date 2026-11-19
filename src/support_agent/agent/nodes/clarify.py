"""Clarify (S10 build step 7): one question for the missing-fact key Triage chose (D108).

- `clarify_node` renders the approved question; gate check 8 allows only that
  text. Communicate sends it.
- `wait_answer_node` writes the pending item through itsm (D53), then
  interrupts. LangGraph re-runs the node on resume: the pending write has a fixed
  idem key, so it returns the same `pending_id` and writes nothing new. The
  answer goes through `process_reply()` (masking, safety net, moderation), is
  added to the ticket as data, and the ticket goes back to Triage with
  `clarify_count = 1`. Moderation of the answer: threat or forbidden hands off,
  a second abusive message hands off (S10 build step 3).
"""

from __future__ import annotations

from typing import Any

from langgraph.types import interrupt

from support_agent.agent.gate import GateOutput, GateResult
from support_agent.agent.messages import clarify, person_will_contact, refusal
from support_agent.agent.runtime import GateBlocked, NodeCtx
from support_agent.agent.state import StoreDraft, TicketState


async def clarify_node(state: TicketState, ctx: NodeCtx) -> dict[str, Any]:
    out = state.triage.output if state.triage else None
    key = out.missing_fact if out else None
    text = clarify(key) if key else None
    if text is None:
        raise GateBlocked(GateResult(False, 8, f"no_template:{key}"))
    gate = await ctx.check(
        GateOutput("store_message", text, "clarify", key), state.ticket.ticket_id
    )
    if not gate.ok:
        raise GateBlocked(gate)
    draft = StoreDraft(kind="clarify", text=text, key=key)
    return {"drafts": [*state.drafts, draft], "status": "waiting_store", "_audit": {"key": key}}


async def wait_answer_node(state: TicketState, ctx: NodeCtx) -> dict[str, Any]:
    step = f"answer-{state.clarify_count}"
    pending = await ctx.itsm.call("create_pending", "wait", step, kind="answer")
    payload = interrupt(
        {"pending_id": pending["pending_id"], "kind": "answer", "ticket_id": state.ticket.ticket_id}
    )
    if payload.get("timeout"):  # the SLA timer won the pending item (S11, D53)
        return {"pending_id": None, "pending_kind": None, "status": "in_progress",
                "handoff_reason": "sla_breach", "_result": "handoff",
                "_audit_reason": "sla_breach"}  # fmt: skip
    if ctx.deps.moderate_reply is None:
        raise RuntimeError("no reply moderation configured")
    masked, label = await ctx.deps.moderate_reply(state, str(payload.get("text", "")))
    tid = state.ticket.ticket_id
    base = {"pending_id": None, "pending_kind": None, "status": "in_progress"}
    abusive = label == "abusive"
    if label in ("threat", "forbidden", "failed") or (abusive and state.abuse_count >= 1):
        text = refusal(tid) if label == "forbidden" else person_will_contact(tid)
        return base | {
            "moderation_label": label,
            "handoff_reason": "moderation",
            "drafts": [*state.drafts, StoreDraft(kind="status_template", text=text)],
            "_result": "handoff",
            "_audit_reason": f"moderation:{label}",
        }
    question = (
        clarify(state.triage.output.missing_fact)
        if state.triage and state.triage.output and state.triage.output.missing_fact
        else ""
    )
    asked = question.split(",", 1)[-1].strip() if question else "the question"
    ticket = state.ticket.model_copy(
        update={
            "description": f'{state.ticket.description}\n\nStore\'s answer to "{asked}": {masked}'
        }  # fmt: skip
    )
    return base | {
        "ticket": ticket,
        "clarify_count": state.clarify_count + 1,
        "abuse_count": state.abuse_count + int(abusive),
        "moderation_label": label if label != "ok" else state.moderation_label,
        "_result": "answered",
        "_audit": {"moderation": label, "pending_id": pending["pending_id"]},
    }
