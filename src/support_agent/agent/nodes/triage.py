"""Triage node (S8 build step 3; agent-architecture.md, 3 Triage): bounded ReAct.

- The model (alias `agent`) gets the versioned prompt plus the escalation SOP,
  and the ticket and facts inside `<data>` tags.
- Tools: search_kb, get_document, get_ticket, get_recent_tickets, get_known_bug;
  at most `max_tool_calls` lookups, counted in code. After the last one only
  `submit_triage` is offered; a lookup past the cap hands off (`budget_exceeded`).
- The output is the strict JSON schema of `TriageOutput`; an invalid one gets one
  retry with the validation error, then `invalid_output`.
- Code then checks the runbook citation (`grounding.verify_quote`); a failed
  citation sets `runbook_id = None`. Everything else (device, tricks, triggers,
  document disagreements) is the model's judgement (S8a).
- Every failure carries a reason code (D57).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from importlib import resources
from typing import Any, Protocol

from pydantic import ValidationError

from support_agent.agent.grounding import FAMILY_OF_ASSET, normalize, verify_quote
from support_agent.agent.llm import (
    BudgetExceeded,
    ChatClient,
    LlmUnavailable,
    TicketBudget,
    strict_schema,
)
from support_agent.agent.nodes.enrich import ItData
from support_agent.agent.state import Facts, HandoffReason, TriageOutput, TriageResult
from support_agent.agent.tools import ToolCallError
from support_agent.intake.safety_net import PIIBlocked
from support_agent.intake.schema import MaskedTicket
from support_agent.mcp.base.errors import ErrorCode
from support_agent.mcp.knowledge.models import Document, GetDocumentResult, SearchKbResult

SOP_DOC = "sop/escalation-procedure.md"
SUBMIT = "submit_triage"
MIN_HISTORY_QUOTE = 15
# A real runbook cited with a bad quote gets one repair turn; a document that is
# excluded or unknown (abstention, D20) never does.
QUOTE_REPAIRABLE = frozenset({"quote_not_in_section", "quote_too_short", "section_not_in_runbook"})
FAMILIES = ["pos", "printer", "network", "online_orders", "soft_serve", "kiosk", "payment"]


def load_prompt() -> str:
    return resources.files("support_agent.agent.prompts").joinpath("triage.md").read_text()


PROMPT_VERSION = load_prompt().splitlines()[0]


class Knowledge(Protocol):
    async def search_kb(
        self,
        query: str,
        *,
        doc_type: str | None = None,
        device_family: str | None = None,
        k: int = 5,
    ) -> SearchKbResult: ...
    async def get_document(self, doc_id: str) -> GetDocumentResult: ...


class History(Protocol):
    """The it-data history and known-bug calls Triage may make."""

    async def get_ticket(self, ticket_id: str, before: datetime) -> Any: ...


class TriageItData(ItData, History, Protocol):
    pass


class SopCache:
    """The escalation SOP, fetched once per `kb_rev` and kept (S8 build step 3)."""

    def __init__(self) -> None:
        self.rev: str | None = None
        self.text: str | None = None

    async def get(self, kb: Knowledge) -> tuple[str, str | None]:
        if self.text is None:
            result = await kb.get_document(SOP_DOC)
            if result.status != "found" or result.document is None:
                raise ToolCallError("get_document", ErrorCode.ERROR, f"sop {result.status}")
            self.rev, self.text = result.kb_rev, result.document.masked_text
        return self.text, self.rev


PromptScan = Callable[[str, str], object]  # (fixed, data) -> raises PIIBlocked on a hit


@dataclass
class TriageDeps:
    llm: ChatClient
    kb: Knowledge
    it_data: TriageItData
    budget: TicketBudget
    sop: SopCache
    max_tool_calls: int = 6
    scan_prompt: PromptScan | None = None
    run_id: uuid.UUID | None = None
    # Triage judges runbook fit; "minimal" cited same-device runbooks for other symptoms.
    reasoning_effort: str = "low"
    trace: list[dict[str, Any]] = field(default_factory=list)


# ---- tool definitions shown to the model ---------------------------------------------


def _fn(name: str, description: str, properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": list(properties),
                "additionalProperties": False,
            },
        },
    }


LOOKUP_TOOLS = [
    _fn(
        "search_kb",
        "Hybrid search over KB sections. Query = device + symptom + error code from the "
        "ticket's subject and description. device_family only when the device is certain.",
        {
            "query": {"type": "string"},
            "device_family": {"type": ["string", "null"], "enum": [*FAMILIES, None]},
        },
    ),
    _fn(
        "get_document",
        "A whole KB document: text and section ids.",
        {"doc_id": {"type": "string"}},
    ),
    _fn(
        "get_ticket",
        "An earlier ticket cited by this one (opened before it).",
        {"ticket_id": {"type": "string"}},
    ),
    _fn(
        "get_recent_tickets",
        "Earlier tickets of this store, or of one asset.",
        {"asset_id": {"type": ["string", "null"]}},
    ),
    _fn(
        "get_known_bug",
        "Known bug, patch and notes for a system and version from the version matrix.",
        {"system": {"type": "string"}, "version": {"type": "string"}},
    ),
]
SUBMIT_TOOL = _fn(SUBMIT, "Submit the triage verdict (once).", {})
SUBMIT_TOOL["function"]["parameters"] = strict_schema(TriageOutput.model_json_schema())


# ---- prompt data ---------------------------------------------------------------------


def _data(payload: Any) -> str:
    text = json.dumps(payload, ensure_ascii=False, default=str)
    return "<data>\n" + text.replace("</data>", "<\\/data>") + "\n</data>"


def ticket_payload(ticket: MaskedTicket, facts: Facts) -> dict[str, Any]:
    asset = facts.asset
    return {
        "ticket": {
            "ticket_id": ticket.ticket_id,
            "date_opened": ticket.date_opened.isoformat(),
            "subject": ticket.subject,
            "description": ticket.description,
            "category": ticket.category,
            "subcategory": ticket.subcategory,
            "priority": ticket.priority,
            "asset_id": ticket.asset_id,
            "system_version": ticket.system_version,
            "tags": ticket.tags,
            "escalation_flag": ticket.escalation_flag,
            "related_tickets": ticket.related_tickets,
            "history": [h.model_dump() for h in ticket.ticket_history],
        },
        "facts": {
            "flags": [str(f) for f in facts.flags],
            "store_type": facts.store.store_type if facts.store else None,
            "store_device_types": sorted({a.asset_type for a in facts.store_assets}),
            "asset": asset.model_dump(
                include={
                    "asset_id",
                    "asset_type",
                    "make",
                    "model",
                    "system_version",
                    "in_warranty",
                }  # fmt: skip
            )
            if asset
            else None,
            "known_bug_cmdb": facts.known_bug_cmdb.model_dump(exclude_none=True)
            if facts.known_bug_cmdb
            else None,
            "known_bug_ticket_version": facts.known_bug_ticket.model_dump(exclude_none=True)
            if facts.known_bug_ticket
            else None,
            "recent_tickets": [
                {
                    "ticket_id": t.ticket_id,
                    "date_opened": t.date_opened.isoformat(),
                    "category": t.category,
                    "asset_id": t.asset_id,
                    "subject": t.subject,
                }  # fmt: skip
                for t in facts.recent_tickets
            ],
        },
    }


def _search_view(result: SearchKbResult) -> dict[str, Any]:
    return {
        "status": result.status,
        "documents": [
            {
                "doc_id": d.doc_id,
                "title": d.title,
                "doc_type": d.doc_type,
                "sections": [
                    {"section_id": s.section_id, "path": s.path, "snippet": s.snippet}
                    for s in d.sections
                ],
            }
            for d in result.documents
        ],
        "codes": result.codes,
    }


def _document_view(result: GetDocumentResult) -> dict[str, Any]:
    doc = result.document
    if doc is None:
        return {"status": result.status}
    return {
        "status": result.status,
        "doc_id": doc.doc_id,
        "doc_type": doc.doc_type,
        "device_family": doc.device_family,
        "truncated": doc.truncated,
        "sections": [{"section_id": s.section_id, "path": s.path} for s in doc.sections],
        "text": doc.masked_text,
    }


# ---- the loop ------------------------------------------------------------------------


class _Run:
    def __init__(self, ticket: MaskedTicket, facts: Facts, deps: TriageDeps) -> None:
        self.ticket, self.facts, self.deps = ticket, facts, deps
        self.documents: dict[str, Document] = {}
        self.searched = False
        self.kb_rev: str | None = None
        self.history = [
            normalize(h.note)
            for h in ticket.ticket_history
            if len(normalize(h.note)) >= MIN_HISTORY_QUOTE
        ]

    async def lookup(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        d, t = self.deps, self.ticket
        if name == "search_kb":
            query = str(args.get("query", ""))
            if any(line in normalize(query) for line in self.history):
                return {"error": "query_rejected: copy no ticket history into a query"}
            result = await d.kb.search_kb(query, device_family=args.get("device_family"))
            self.searched = True
            self.kb_rev = result.kb_rev or self.kb_rev
            return _search_view(result)
        if name == "get_document":
            doc = await d.kb.get_document(str(args.get("doc_id", "")))
            if doc.document is not None:
                self.documents[doc.document.doc_id] = doc.document
            self.kb_rev = doc.kb_rev or self.kb_rev
            return _document_view(doc)
        if name == "get_ticket":
            r = await d.it_data.get_ticket(str(args.get("ticket_id", "")), t.date_opened)
            return dict(r.model_dump(mode="json"))
        if name == "get_recent_tickets":
            r = await d.it_data.get_recent_tickets(
                t.date_opened, store_id=t.store_id, asset_id=args.get("asset_id")
            )
            return dict(r.model_dump(mode="json"))
        if name == "get_known_bug":
            r = await d.it_data.get_known_bug(str(args["system"]), str(args["version"]))
            return dict(r.model_dump(mode="json", exclude_none=True))
        return {"error": f"unknown tool {name}"}

    def established_family(self, out: TriageOutput) -> str | None:
        """The device family is established when the model's real device is the
        linked asset's type; then the cited runbook must be for that family."""
        asset = self.facts.asset
        if asset is None or out.real_device != asset.asset_type:
            return None
        return FAMILY_OF_ASSET.get(asset.asset_type)

    async def check(self, out: TriageOutput) -> tuple[TriageOutput, str | None]:
        """Code check after a valid submit: the runbook citation."""
        update: dict[str, Any] = {}
        quote: str | None = None
        if out.runbook_id:
            ev = out.runbook_evidence
            doc = self.documents.get(out.runbook_id)
            if doc is None and ev is not None:
                fetched = await self.deps.kb.get_document(out.runbook_id)
                doc = fetched.document
            check = (
                verify_quote(
                    out.runbook_id,
                    ev.section_id,
                    ev.quote,
                    doc,
                    device_family=self.established_family(out),
                )  # fmt: skip
                if ev
                else None
            )
            quote = check.reason if check else "no_evidence"
            if check is None or not check.ok:
                update.update(runbook_id=None, runbook_evidence=None)
        elif out.runbook_evidence is not None:
            update["runbook_evidence"] = None
        return (out.model_copy(update=update) if update else out), quote


def _result(
    run: _Run,
    calls: int,
    *,
    output: TriageOutput | None = None,
    reason: HandoffReason | None = None,
    first_try_valid: bool = False,
    quote: str | None = None,
) -> TriageResult:
    return TriageResult(
        output=output,
        handoff_reason=reason,
        searched=run.searched,
        quote_check=quote,
        tool_calls=calls,
        first_try_valid=first_try_valid,
        kb_rev=run.kb_rev,
    )


async def triage(ticket: MaskedTicket, facts: Facts, deps: TriageDeps) -> TriageResult:
    run = _Run(ticket, facts, deps)
    calls = 0
    try:
        sop, sop_rev = await deps.sop.get(deps.kb)
        run.kb_rev = sop_rev
        fixed = load_prompt() + "\n" + sop
        data = _data(ticket_payload(ticket, facts))
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": fixed},
            {"role": "user", "content": data},
        ]
        retried = quote_retried = False
        meta = {"ticket_id": ticket.ticket_id, "node": "triage", "prompt": PROMPT_VERSION}
        if deps.run_id:
            meta["run_id"] = str(deps.run_id)
        while True:
            tools = [*LOOKUP_TOOLS, SUBMIT_TOOL] if calls < deps.max_tool_calls else [SUBMIT_TOOL]
            if deps.scan_prompt:
                deps.scan_prompt(
                    fixed, "\n".join(str(m.get("content") or "") for m in messages[1:])
                )
            reply = await deps.llm.complete(
                messages,
                deps.budget,
                tools=tools,
                metadata=meta,
                reasoning_effort=deps.reasoning_effort,
            )
            msg = reply.message
            tool_calls = msg.get("tool_calls") or []
            messages.append(
                {"role": "assistant", "content": msg.get("content"), "tool_calls": tool_calls}
                if tool_calls
                else {"role": "assistant", "content": msg.get("content") or ""}
            )
            deps.trace.append({"tool_calls": [tc["function"]["name"] for tc in tool_calls]})
            if not tool_calls:
                if retried:
                    return _result(run, calls, reason="invalid_output")
                retried = True
                messages.append({"role": "user", "content": f"Call a tool or {SUBMIT}."})
                continue
            submit = next((tc for tc in tool_calls if tc["function"]["name"] == SUBMIT), None)
            for tc in tool_calls:
                name = tc["function"]["name"]
                if tc is submit:
                    continue
                if submit is not None:
                    content: dict[str, Any] = {"error": "ignored: submitted in the same turn"}
                elif calls >= deps.max_tool_calls:
                    # Never more than the cap. A parallel batch that crosses it gets
                    # "limit reached"; a lookup after only submit was offered hands off.
                    if len(tools) == 1:
                        return _result(run, calls, reason="budget_exceeded")
                    content = {"error": f"tool limit reached: call {SUBMIT} now"}
                else:
                    calls += 1
                    try:
                        args = json.loads(tc["function"].get("arguments") or "{}")
                    except ValueError:
                        args = {}
                    content = await run.lookup(name, args)
                messages.append(
                    {"role": "tool", "tool_call_id": tc["id"], "content": _data(content)}
                )
            if submit is None:
                continue
            try:
                output = TriageOutput.model_validate_json(submit["function"].get("arguments", ""))
            except ValidationError as exc:
                if retried:
                    return _result(run, calls, reason="invalid_output")
                retried = True
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": submit["id"],
                        "content": f"invalid: {exc.errors(include_url=False)}. Submit again.",
                    }
                )
                continue
            checked, quote = await run.check(output)
            if quote in QUOTE_REPAIRABLE and not quote_retried and calls <= deps.max_tool_calls:
                quote_retried = True
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": submit["id"],
                        "content": f"citation rejected: {quote}. Copy the quote character for "
                        "character from that section's text in get_document, or set runbook_id "
                        "and runbook_evidence to null. Submit again.",
                    }
                )
                continue
            result = _result(run, calls, output=checked, first_try_valid=not retried, quote=quote)
            return result.model_copy(
                update={"cited_runbook": output.runbook_id, "cited": output.runbook_evidence}
            )
    except ToolCallError:
        return _result(run, calls, reason="tool_error")
    except BudgetExceeded:
        return _result(run, calls, reason="budget_exceeded")
    except LlmUnavailable:
        return _result(run, calls, reason="llm_unavailable")
    except PIIBlocked:
        return _result(run, calls, reason="gate_block")
