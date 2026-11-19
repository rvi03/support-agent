"""Approved walk steps (S11 build step 3; D108): `bindings.yaml` loaded and checked.

A binding ties one runbook span to who may do it (store, a registry action or an
L2 task), the connection it is written for, whether it is generic, the warnings
sent first, its prerequisites and whether the runbook asks for approval. The
Resolver dispatches nothing that has no binding.

`proposal_id` is the stable id of a proposal: a hash of (kb_rev, document,
section, span), so the audit and itsm rows name exactly which words were used.
"""

from __future__ import annotations

import hashlib
from functools import cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from support_agent.common.text import MIN_QUOTE, normalize, quote_in
from support_agent.mcp.knowledge.models import Document

BINDINGS_PATH = Path(__file__).with_name("bindings.yaml")

Audience = Literal["store", "it", "l2"]
Scope = Literal["any", "usb", "network"]
L2Reason = Literal["l2_only", "secret", "destructive_store_step", "unmapped", "guard"]


class Binding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(pattern=r"^[a-z][a-z0-9-]{2,63}$")
    section: str = Field(pattern=r"^runbooks/[a-z0-9-]+\.md#[a-z0-9~-]+$")
    title: str = Field(min_length=3, max_length=80)
    span: str = Field(min_length=MIN_QUOTE)
    audience: Audience
    action_id: str | None = None
    l2_reason: L2Reason | None = None
    scope: Scope = "any"
    generic: bool = False
    warnings: tuple[str, ...] = ()
    requires: tuple[str, ...] = ()
    approval: bool = False
    conflict: bool = False

    @property
    def doc_id(self) -> str:
        return self.section.split("#", 1)[0]

    @model_validator(mode="after")
    def _audience_fields(self) -> Binding:
        if self.audience == "it" and not self.action_id:
            raise ValueError(f"{self.id}: an IT step needs action_id")
        if self.audience != "it" and self.action_id:
            raise ValueError(f"{self.id}: only an IT step names an action")
        if self.audience == "l2" and not self.l2_reason:
            raise ValueError(f"{self.id}: an L2 step needs l2_reason")
        return self

    def store_text(self) -> str:
        """What the store gets: the warnings first, then the span (D51, D50)."""
        return "\n".join([*self.warnings, self.span])


class Bindings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: int
    runbooks: dict[str, tuple[Binding, ...]]

    @field_validator("runbooks")
    @classmethod
    def _ids(cls, value: dict[str, tuple[Binding, ...]]) -> dict[str, tuple[Binding, ...]]:
        seen: set[str] = set()
        for doc_id, steps in value.items():
            for b in steps:
                if b.id in seen:
                    raise ValueError(f"duplicate binding id {b.id}")
                if b.doc_id != doc_id:
                    raise ValueError(f"{b.id}: section {b.section} is not in {doc_id}")
                seen.add(b.id)
            ids = {b.id for b in steps}
            for b in steps:
                missing = set(b.requires) - ids
                if missing:
                    raise ValueError(f"{b.id}: requires unknown steps {sorted(missing)}")
        return value

    def for_runbook(self, doc_id: str) -> tuple[Binding, ...]:
        return self.runbooks.get(doc_id, ())

    def get(self, doc_id: str, step_id: str) -> Binding | None:
        return next((b for b in self.for_runbook(doc_id) if b.id == step_id), None)

    def words(self) -> str:
        """Every title, span and warning: our curated text for gate check 5."""
        return "\n".join(
            part for steps in self.runbooks.values() for b in steps
            for part in (b.title, b.span, *b.warnings)
        )  # fmt: skip


def load_bindings(path: Path = BINDINGS_PATH) -> Bindings:
    data = yaml.safe_load(path.read_bytes())
    if not isinstance(data, dict):
        raise ValueError(f"{path}: not a mapping")
    return Bindings.model_validate(data)


@cache
def default_bindings() -> Bindings:
    return load_bindings()


def in_document(binding: Binding, doc: Document) -> bool:
    """The span and every warning are still in the binding's section of this revision."""
    section = next((s for s in doc.sections if s.section_id == binding.section), None)
    if section is None or not section.masked_text:
        return False
    return all(quote_in(t, section.masked_text) for t in (binding.span, *binding.warnings))


def proposal_id(kb_rev: str, binding: Binding) -> str:
    raw = "\x1f".join((kb_rev, binding.doc_id, binding.section, normalize(binding.span)))
    return "p-" + hashlib.sha256(raw.encode()).hexdigest()[:16]
