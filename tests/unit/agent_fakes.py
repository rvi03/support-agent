"""Shared fakes for the S8 agent unit tests (mock values only, D70)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from support_agent.agent.state import Facts, Flag, TriageOutput, TriageResult
from support_agent.intake.schema import MaskedTicket
from support_agent.mcp.it_data.models import Asset, KnownBugResult, SlaResult, Store, TicketSummary
from support_agent.mcp.knowledge.models import Document, SectionRef

# 09:30 IST: outside peak hours.
OPENED = datetime(2026, 1, 5, 4, 0, tzinfo=UTC)
ESCALATE_MIN = {"P1": 30, "P2": 90, "P3": 180, "P4": 360}  # sla_matrix escalation_to_l2_minutes


def sla(priority: str, opened: datetime = OPENED) -> SlaResult:
    m = ESCALATE_MIN[priority]
    return SlaResult(
        status="found", priority=priority, category_requested="POS", category_used="POS",  # type: ignore[arg-type]
        first_response_minutes=15, escalation_to_l2_minutes=m, resolution_target_minutes=m * 4,
        first_response_by=opened + timedelta(minutes=15), escalate_by=opened + timedelta(minutes=m),
        resolve_by=opened + timedelta(minutes=m * 4),
    )  # fmt: skip


def ticket(**over: Any) -> MaskedTicket:
    base: dict[str, Any] = {
        "ticket_id": "T-1", "store_id": "SW-0001", "date_opened": OPENED,
        "subject": "Receipt printer offline", "description": "The printer shows offline on POS.",
        "priority": "P3", "category": "Printers", "asset_id": "PRN-0001-P1",
    }  # fmt: skip
    return MaskedTicket(**(base | over))


def asset(asset_type: str = "Receipt Printer") -> Asset:
    d = date(2025, 1, 1)
    return Asset(
        asset_id="PRN-0001-P1", store_id="SW-0001", asset_type=asset_type, make="Mockmake",
        model="M1", system_version="Mockprint v1.0", system_name="Mockprint", version="v1.0",
        install_date=d, last_service_date=d, warranty_expiry=d, as_of=d, in_warranty=True,
        warranty_days_left=10,
    )  # fmt: skip


def facts(
    *,
    priority: str = "P3",
    store_type: str = "franchise",
    flags: list[Flag] | None = None,
    bug: KnownBugResult | None = None,
    recent: list[TicketSummary] | None = None,
    asset_type: str | None = "Receipt Printer",
) -> Facts:
    return Facts(
        store=Store(
            store_id="SW-0001",
            store_name="Mock Store",
            store_type=store_type,
            city="Mockcity",
            neighborhood="Mockarea",
        ),  # fmt: skip
        asset=asset(asset_type) if asset_type else None,
        store_assets=[],
        recent_tickets=recent or [],
        sla=sla(priority),
        sla_by_priority={p: sla(p) for p in ESCALATE_MIN},
        priority_used=priority,
        known_bug_cmdb=bug,
        known_bug_ticket=None,
        flags=flags or [],
    )


def recent(days_before: int, *, asset_id: str | None = "PRN-0001-P1") -> TicketSummary:
    return TicketSummary(
        ticket_id=f"T-{days_before}", store_id="SW-0001", store_name=None,
        date_opened=OPENED - timedelta(days=days_before), priority="P3", category="Printers",
        subcategory=None, subject="Printer offline", description="x", asset_id=asset_id,
        system_version=None, tags=[], escalation_flag=None, related_tickets=[],
    )  # fmt: skip


def output(**over: Any) -> TriageOutput:
    base: dict[str, Any] = {
        "real_category": "Printers", "real_device": "Receipt Printer", "trick_flags": [],
        "runbook_id": "runbooks/printer-offline.md",
        "runbook_evidence": {"section_id": "runbooks/printer-offline.md#symptoms",
                             "quote": "Printer shows Offline status"},
        "sop_triggers": [], "doc_conflicts": [], "route": "l1_guided", "reason": "r",
        "confidence": 0.9,
    }  # fmt: skip
    return TriageOutput.model_validate(base | over)


def result(out: TriageOutput | None = None, **over: Any) -> TriageResult:
    base: dict[str, Any] = {
        "output": out, "handoff_reason": None, "searched": True, "quote_check": "verified",
        "tool_calls": 2, "first_try_valid": True, "kb_rev": "kb-test",
    }  # fmt: skip
    return TriageResult(**(base | over))


SECTION_TEXT = (
    "## Symptoms\n\n- Printer shows **Offline** status in ServeWell POS system\n"
    "- Print jobs queue but do not output"
)


def document(
    doc_id: str = "runbooks/printer-offline.md",
    family: list[str] | None = None,
    doc_type: str = "runbook",
    section_text: str | None = SECTION_TEXT,
) -> Document:
    return Document(
        doc_id=doc_id, doc_type=doc_type, title="Printer Offline", categories=["Printers"],  # type: ignore[arg-type]
        device_family=family or ["printer"], covered_systems=[], related=[],
        revision=None, last_updated=None, truncated=False, masked_text="# Printer\n" + SECTION_TEXT,
        sections=[SectionRef(section_id=f"{doc_id}#symptoms", parent_section_id=None,
                             path="Symptoms", ord=1, masked_text=section_text)],
    )  # fmt: skip
