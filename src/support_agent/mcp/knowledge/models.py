"""Pydantic input and result models of the knowledge tools (rag-design.md section 7).

Domain outcomes are typed `status` values (`found`, `none`, `not_found`,
`budget_exceeded`); refusals and failures are tool errors (base/errors.py).
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

DocType = Literal["runbook", "sop", "faq", "spec"]
Family = Literal["pos", "printer", "network", "online_orders", "soft_serve", "kiosk", "payment"]
DocId = Annotated[
    str,
    StringConstraints(
        pattern=r"^(runbooks|sop|faq|system-specs)/[a-z0-9][a-z0-9-]*\.md$", max_length=120
    ),
]
Query = Annotated[str, StringConstraints(min_length=1, max_length=2000, strip_whitespace=True)]
Category = Annotated[str, StringConstraints(min_length=1, max_length=40, strip_whitespace=True)]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# ---- search_kb ----------------------------------------------------------------------


class SearchKbIn(_In):
    query: Query
    doc_type: DocType | None = None
    device_family: Family | None = None
    category: Category | None = None
    k: int = Field(default=5, ge=1, le=10)


class SectionHit(_Out):
    section_id: str
    parent_section_id: str | None
    path: str
    snippet: str
    promoted: bool


class DocumentHit(_Out):
    doc_id: str
    title: str
    doc_type: DocType
    score: float
    truncated: bool
    sections: list[SectionHit]


class CodeSection(_Out):
    section_id: str
    doc_id: str
    device_family: list[str]


class SearchKbResult(_Out):
    status: Literal["found", "none", "budget_exceeded"]
    kb_rev: str | None = None
    documents: list[DocumentHit] = []
    codes: list[str] = []
    # With codes and no device_family: sections holding a code, every family, not promoted.
    code_sections: list[CodeSection] = []
    budget_used: int = 0
    budget_limit: int = 0


# ---- get_document -------------------------------------------------------------------


class GetDocumentIn(_In):
    doc_id: DocId
    # Code only (S8 quote check): each section's own text, not charged to the budget.
    with_section_text: bool = False


class SectionRef(_Out):
    section_id: str
    parent_section_id: str | None
    path: str
    ord: int
    masked_text: str | None = None


class Document(_Out):
    doc_id: str
    doc_type: DocType
    title: str
    categories: list[str]
    device_family: list[str]
    covered_systems: list[dict[str, Any]]
    related: list[str]
    revision: str | None
    last_updated: str | None
    truncated: bool
    masked_text: str
    sections: list[SectionRef]


class GetDocumentResult(_Out):
    status: Literal["found", "not_found", "budget_exceeded"]
    kb_rev: str | None = None
    document: Document | None = None
    budget_used: int = 0
    budget_limit: int = 0


# ---- eval-only: run-scoped exclusions (S8 abstention test, review M6) --------------


class RegisterExclusionsIn(_In):
    run_id: uuid.UUID
    doc_ids: list[DocId] = Field(min_length=1, max_length=50)


class RegisterExclusionsResult(_Out):
    status: Literal["registered"]
    run_id: uuid.UUID
    excluded: list[str]


class IsExcludedIn(_In):
    run_id: uuid.UUID
    doc_id: DocId


class IsExcludedResult(_Out):
    status: Literal["excluded", "not_excluded"]
