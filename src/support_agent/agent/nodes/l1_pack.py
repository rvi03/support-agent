"""L1 Pack node (S10 build step 5; agent-architecture.md, 6c): Group B for a human L1.

Code fetches the chosen runbook; one LLM call (write-l1-pack skill) writes the
`L1Pack`, each claim citing section ids. Every cited id must be a section of
that runbook (code) and exist in the ticket's kb_rev (gate check 7); a miss or a
gate block hands off. The store gets the template "An L1 engineer will contact
you by <first response time>".
"""

from __future__ import annotations

from typing import Any

from support_agent.agent.gate import GateOutput, GateResult
from support_agent.agent.messages import status_l1
from support_agent.agent.nodes.handoff import OUTPUT_RULE, note_payload
from support_agent.agent.nodes.triage import _data
from support_agent.agent.notes import L1Pack
from support_agent.agent.prompting import system_prompt
from support_agent.agent.runtime import GateBlocked, NodeCtx
from support_agent.agent.state import StoreDraft, TicketState
from support_agent.agent.tools import ToolCallError
from support_agent.mcp.base.errors import ErrorCode


async def l1_pack_node(state: TicketState, ctx: NodeCtx) -> dict[str, Any]:
    out = state.triage.output if state.triage else None
    if out is None or out.runbook_id is None:
        raise GateBlocked(GateResult(False, 7, "l1_pack_without_runbook"))
    doc = await ctx.kb.get_document(out.runbook_id)
    if doc.document is None:
        raise ToolCallError("get_document", ErrorCode.ERROR, f"runbook {doc.status}")
    runbook = doc.document
    sections = {s.section_id for s in runbook.sections}
    prompt = system_prompt("l1_pack")
    payload = note_payload(state) | {
        "runbook": {
            "doc_id": runbook.doc_id,
            "sections": [{"section_id": s.section_id, "path": s.path} for s in runbook.sections],
            "text": runbook.masked_text,
        }
    }
    data = _data(payload)
    ctx.deps.safety_net.scan_vault(prompt.text + "\n" + data, state.ticket.ticket_id, "prompt")
    pack, _ = await ctx.deps.llm.structured(
        prompt.text + OUTPUT_RULE,
        data,
        L1Pack,
        ctx.budget,
        name="l1_pack",
        metadata={"ticket_id": state.ticket.ticket_id, "run_id": state.run_id,
                  "node": "l1_pack", "prompt": prompt.version},
    )  # fmt: skip
    foreign = [s for s in pack.section_ids() if s not in sections]
    if foreign or not pack.section_ids():
        raise GateBlocked(GateResult(False, 7, f"cites_outside_runbook:{foreign[:3]}"))
    text = pack.render(runbook.doc_id)
    gate = await ctx.check(GateOutput("l1_pack", text, source=data), state.ticket.ticket_id)
    if not gate.ok:
        raise GateBlocked(gate)
    by = state.policy.sla.first_response_by if state.policy else None
    draft = StoreDraft(kind="status_template", text=status_l1(state.ticket.ticket_id, by))
    return {
        "l1_pack_text": text,
        "drafts": [*state.drafts, draft],
        "status": "with_l1",
        "_prompt": prompt.version,
        "_audit": {"runbook_id": runbook.doc_id, "cited": sorted(set(pack.section_ids()))},
    }
