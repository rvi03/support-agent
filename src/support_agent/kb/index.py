"""`make index`: build and publish one KB revision (S6 step 1; rag-design.md section 4).

    load (S3) -> truncation -> redact -> mask -> links -> table padding -> metadata
      -> chunk -> tokens -> embed -> kb_staging -> publish (schema swap)

Steps 2-9 are pure (`build`); only `load`, `embed` and `write` touch a service.
S9 adds step 6 (parsed runbook steps) through `STEP_HOOKS` before publish.
The run prints the index report and saves it to eval/reports/index_report.md.
Exit codes: 0 published, 1 a check failed (nothing published).
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from support_agent.common.config import KbIndexSettings, get_settings
from support_agent.common.db import dsn
from support_agent.kb import chunk, clean, metadata
from support_agent.kb.embed import embed, vector_literal
from support_agent.kb.load import SourceFile, load, s3_client
from support_agent.mcp.itsm.registry import REGISTRY_PATH, registry_version
from support_agent.mcp.knowledge import tokenizer

PIPELINE_VERSION = "kb-pipeline-v1"
TOKENIZER_VERSION = "bm25-tok-v1"
DB_EMBED_DIM = 768  # the vector width in db/sql/007_kb.sql
REPORT_PATH = Path("eval/reports/index_report.md")
_SECRET_RE = re.compile(re.escape(clean.SECRET))

Embedder = Callable[[Sequence[str]], list[list[float]]]
# S9 adds step 6 (parsed runbook steps) here; each hook runs on the built revision
# before it is written, and may add rows, gaps and report lines.
STEP_HOOKS: list[Callable[[Built], None]] = []


class IndexCheckError(RuntimeError):
    pass


@dataclass
class DocRow:
    meta: metadata.DocMeta
    truncated: bool
    related: list[str]
    content_hash: str
    masked_text: str


@dataclass
class SectionRow:
    section: chunk.Section
    doc_type: str
    device_family: list[str]
    categories: list[str]
    bm25_tokens: list[str]
    embedding: list[float] = field(default_factory=list)


@dataclass
class Built:
    kb_rev: str
    source_hashes: dict[str, str]
    rule_versions: dict[str, str]
    docs: list[DocRow]
    sections: list[SectionRow]
    redactions: list[tuple[str, str | None, int, str]]  # doc, section, offset, rule
    gaps: list[tuple[str, str, str]]  # doc, kind, detail
    report: dict[str, Any]


def _rule_versions() -> dict[str, str]:
    return {
        "redaction": clean.REDACTION_RULES_VERSION,
        "masking": clean.MASK_RULES_VERSION,
        "tokenizer": TOKENIZER_VERSION,
        "chunk_budget": str(chunk.CHUNK_BUDGET),
        # The registry file hash (S7): run_fix refuses a registry that drifted from it.
        "action_registry": registry_version(REGISTRY_PATH.read_bytes()),
    }


def kb_rev_of(source_hashes: dict[str, str], rule_versions: dict[str, str], embed: str) -> str:
    material = json.dumps(
        {
            "sources": source_hashes,
            "pipeline": PIPELINE_VERSION,
            "rules": rule_versions,
            "embedding": embed,
        },
        sort_keys=True,
    )
    return "kb-" + hashlib.sha256(material.encode()).hexdigest()[:16]


def _section_at(sections: list[chunk.Section], pos: int) -> str | None:
    for s in sections:
        if s.start <= pos < s.end:
            return s.parent_section_id or s.section_id
    return None


def build(
    files: list[SourceFile],
    *,
    embed_id: str,
    analyze: clean.Analyze = clean.presidio_analyze,
) -> Built:
    """Steps 2-9 on the loaded files; raises IndexCheckError when redactions do not line up."""
    source_hashes = {f.doc_id: f.sha256 for f in files}
    md_files = [f for f in files if f.doc_id.endswith(".md")]
    md_ids = [f.doc_id for f in md_files]
    rule_versions = _rule_versions()

    redacted: dict[str, tuple[str, list[clean.Redaction]]] = {}
    for f in md_files:
        redacted[f.doc_id] = clean.redact(f.data.decode("utf-8"))
    vocabulary = clean.lowercase_vocabulary(t for t, _ in redacted.values())

    docs: list[DocRow] = []
    sections: list[SectionRow] = []
    redactions: list[tuple[str, str | None, int, str]] = []
    gaps: list[tuple[str, str, str]] = []
    masks: Counter[str] = Counter()
    truncated_why: dict[str, str] = {}
    for f in md_files:
        raw = f.data.decode("utf-8")
        doc_type = metadata.doc_type_of(f.doc_id)
        truncated, why = clean.truncation(f.doc_id, doc_type, raw)
        text, found = redacted[f.doc_id]
        text, counts = clean.mask(text, vocabulary, analyze)
        masks.update(counts)
        linked = clean.links(text, md_ids)
        final = clean.strip_table_padding(linked.text)
        meta = metadata.build(f.doc_id, final)
        _, secs = chunk.sections(f.doc_id, doc_type, final)

        positions = [m.start() for m in _SECRET_RE.finditer(final)]
        if len(positions) != len(found):
            raise IndexCheckError(f"{f.doc_id}: {len(found)} redactions, {len(positions)} markers")
        for pos, red in zip(positions, found, strict=True):
            redactions.append((f.doc_id, _section_at(secs, pos), pos, red.rule_id))
        if truncated:
            truncated_why[f.doc_id] = why
            gaps.append((f.doc_id, "truncated", why))
        gaps.extend((f.doc_id, "missing_link", name) for name in linked.missing)
        docs.append(DocRow(meta, truncated, linked.related, f.sha256, final))
        for s in secs:
            sections.append(
                SectionRow(
                    section=s,
                    doc_type=doc_type,
                    device_family=meta.device_family,
                    categories=meta.categories,
                    bm25_tokens=tokenizer.index_terms(s.index_text),
                )
            )

    kb_rev = kb_rev_of(source_hashes, rule_versions, embed_id)
    gap_kinds = Counter(kind for _, kind, _ in gaps)
    report: dict[str, Any] = {
        "kb_rev": kb_rev,
        "pipeline_version": PIPELINE_VERSION,
        "documents": dict(Counter(d.meta.doc_type for d in docs)),
        "sections": len(sections),
        "split_sections": len({s.section.parent_section_id for s in sections} - {None}),
        "max_section_tokens": max(s.section.token_count for s in sections),
        "redactions": dict(Counter(r[3] for r in redactions)),
        "redactions_total": len(redactions),
        "masks": dict(masks),
        "gaps": dict(gap_kinds),
        "missing_links": gap_kinds.get("missing_link", 0),
        "docs_with_missing_links": len({d for d, k, _ in gaps if k == "missing_link"}),
        "truncated": dict(sorted(truncated_why.items())),
    }
    return Built(kb_rev, source_hashes, rule_versions, docs, sections, redactions, gaps, report)


# ---- service steps ----------------------------------------------------------------------


def add_embeddings(built: Built, embedder: Embedder) -> None:
    vectors = embedder([s.section.index_text for s in built.sections])
    for row, vec in zip(built.sections, vectors, strict=True):
        row.embedding = vec


_TABLES = ("revisions", "documents", "sections", "redactions", "gaps")


def write_staging(conn: psycopg.Connection[Any], built: Built) -> None:
    """Fill kb_staging in one transaction: earlier revisions' metadata rows, then this one."""
    rev = built.kb_rev
    with conn.transaction():
        conn.execute("TRUNCATE " + ", ".join(f"kb_staging.{t}" for t in _TABLES))
        conn.execute(
            "INSERT INTO kb_staging.revisions (kb_rev, created_at, source_hashes, "
            "pipeline_version, rule_versions, report, is_current) "
            "SELECT kb_rev, created_at, source_hashes, pipeline_version, rule_versions, report, "
            "false FROM kb.revisions WHERE kb_rev <> %s",
            (rev,),
        )
        conn.execute(
            "INSERT INTO kb_staging.revisions (kb_rev, source_hashes, pipeline_version, "
            "rule_versions, report, is_current) VALUES (%s, %s, %s, %s, %s, true)",
            (
                rev,
                Jsonb(built.source_hashes),
                PIPELINE_VERSION,
                Jsonb(built.rule_versions),
                Jsonb(built.report),
            ),
        )
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO kb_staging.documents (kb_rev, doc_id, doc_type, title, categories, "
                "device_family, covered_systems, related, revision, last_updated, truncated, "
                "content_hash, masked_text) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                [
                    (
                        rev,
                        d.meta.doc_id,
                        d.meta.doc_type,
                        d.meta.title,
                        d.meta.categories,
                        d.meta.device_family,
                        Jsonb(d.meta.covered_systems),
                        d.related,
                        d.meta.revision,
                        d.meta.last_updated,
                        d.truncated,
                        d.content_hash,
                        d.masked_text,
                    )
                    for d in built.docs
                ],
            )
            cur.executemany(
                "INSERT INTO kb_staging.sections (kb_rev, section_id, parent_section_id, doc_id, "
                "doc_type, device_family, categories, path, ord, masked_text, index_text, "
                "bm25_tokens, token_count, embedding) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector)",
                [
                    (
                        rev,
                        s.section.section_id,
                        s.section.parent_section_id,
                        s.section.doc_id,
                        s.doc_type,
                        s.device_family,
                        s.categories,
                        s.section.path,
                        s.section.ord,
                        s.section.text,
                        s.section.index_text,
                        s.bm25_tokens,
                        s.section.token_count,
                        vector_literal(s.embedding),
                    )
                    for s in built.sections
                ],
            )
            cur.executemany(
                'INSERT INTO kb_staging.redactions (kb_rev, doc_id, section_id, "offset", '
                "rule_id) VALUES (%s, %s, %s, %s, %s)",
                [(rev, *r) for r in built.redactions],
            )
            cur.executemany(
                "INSERT INTO kb_staging.gaps (kb_rev, doc_id, kind, detail) "
                "VALUES (%s, %s, %s, %s)",
                [(rev, *g) for g in built.gaps],
            )


def publish(conn: psycopg.Connection[Any], kb_rev: str) -> None:
    """Swap kb_staging in as kb in one transaction (kb_admin.publish, SECURITY DEFINER)."""
    with conn.transaction():
        conn.execute("SELECT kb_admin.publish(%s)", (kb_rev,))


# ---- report -----------------------------------------------------------------------------


def report_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# KB index report: {report['kb_rev']}",
        "",
        f"- Pipeline: {report['pipeline_version']}",
        f"- Documents: {report['documents']}",
        f"- Sections (chunks): {report['sections']}; sections split for size: "
        f"{report['split_sections']}; largest chunk: {report['max_section_tokens']} tokens",
        f"- Redactions: {report['redactions_total']} {report['redactions']}",
        f"- PII masks: {report['masks']}",
        f"- Gaps: {report['gaps']}",
        f"- Missing links: {report['missing_links']} in "
        f"{report['docs_with_missing_links']} documents",
        f"- Truncated documents: {len(report['truncated'])}",
        *[f"  - {doc} ({why})" for doc, why in report["truncated"].items()],
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    settings = get_settings(KbIndexSettings)
    if settings.embed_dim != DB_EMBED_DIM:
        print(f"EMBED_DIM {settings.embed_dim} != vector({DB_EMBED_DIM}) in 007_kb.sql")
        return 1
    files = load(s3_client(settings))
    try:
        built = build(files, embed_id=f"{settings.model_embed}:{settings.embed_dim}")
    except IndexCheckError as exc:
        print(f"Index check failed, nothing published: {exc}")
        return 1
    with psycopg.connect(dsn(settings.database_url_kb_index, settings.db_host)) as conn:
        row = conn.execute("SELECT kb_rev FROM kb.revisions WHERE is_current").fetchone()
        if row and row[0] == built.kb_rev and "--force" not in args:
            print(report_markdown(built.report))
            print(f"Unchanged: {built.kb_rev} is already current (use --force to rebuild).")
            return 0

        def embedder(texts: Sequence[str]) -> list[list[float]]:
            return embed(
                texts,
                base_url=settings.litellm_base_url,
                key=settings.litellm_master_key.get_secret_value(),
                model=settings.model_embed,
                dim=settings.embed_dim,
            )

        for hook in STEP_HOOKS:
            hook(built)
        add_embeddings(built, embedder)
        write_staging(conn, built)
        publish(conn, built.kb_rev)
    text = report_markdown(built.report)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(text)
    print(text)
    print(f"Published {built.kb_rev}; report saved to {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
