"""Index step 7: sections and chunks (S6 step 1; rag-design.md section 4, step 7; D13).

- Split on markdown headings (`#`-`####`, outside code fences), on bold step
  headers (`**Step n: ...**`, `**Resolution Step n**`, `**Scenario n**`,
  `**Path X**`, `**Phase n**`) and, in FAQs, on each `**Q: ...**` (one Q/A per chunk).
- `index_text` = `<title> > <path>` + the text; its token count (tiktoken
  `cl100k_base`, D64) includes that prefix (Codex P3).
- A section over the budget is split at paragraph, list-item or table-row
  boundaries; table pieces repeat the header. Each piece keeps `parent_section_id`.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from functools import cache
from pathlib import Path

CHUNK_BUDGET = 480
_HEADING = re.compile(r"^(?P<hashes>#{1,4})\s+(?P<title>.+?)\s*#*\s*$")
_BOLD_STEP = re.compile(
    r"^\*\*(?P<title>(?:Resolution\s+)?(?:Step|Scenario|Path|Phase)\s+[\w.]+\b[^*]*?)\*\*:?\s*$",
    re.I,
)
_FAQ_Q = re.compile(r"^\*\*(?P<title>Q:\s*[^*]+?)\*\*\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")
_SLUG = re.compile(r"[^a-z0-9]+")

Counter = Callable[[str], int]


@cache
def _encoding() -> object:
    import tiktoken

    os.environ.setdefault("TIKTOKEN_CACHE_DIR", str(Path(".run/tiktoken").resolve()))
    return tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    """Tokens of the embedding model's own tokenizer (text-embedding-3: cl100k_base)."""
    enc = _encoding()
    return len(enc.encode(text, disallowed_special=()))  # type: ignore[attr-defined]


@dataclass
class Section:
    section_id: str
    parent_section_id: str | None
    doc_id: str
    path: str
    ord: int
    text: str
    index_text: str
    token_count: int
    start: int  # character offset of the section in the document text
    end: int


def slug(text: str) -> str:
    return _SLUG.sub("-", text.lower()).strip("-")[:60] or "section"


@dataclass
class _Raw:
    path: list[str]
    start: int
    end: int


def _split_raw(text: str, faq: bool) -> tuple[str, list[_Raw]]:
    """(title, sections with their heading path and offsets)."""
    title = ""
    stack: list[tuple[int, str]] = []  # (level, heading)
    raws: list[_Raw] = []
    in_fence = False
    offset = 0
    current = _Raw(["Introduction"], 0, 0)
    for line in text.splitlines(keepends=True):
        stripped = line.rstrip("\n")
        if _FENCE.match(stripped):
            in_fence = not in_fence
        level, name = 0, ""
        if not in_fence:
            h = _HEADING.match(stripped)
            b = _BOLD_STEP.match(stripped)
            q = _FAQ_Q.match(stripped) if faq else None
            if h:
                level, name = len(h.group("hashes")), h.group("title").strip("* ")
            elif b:
                level, name = 5, b.group("title").strip()
            elif q:
                level, name = 6, q.group("title").strip()
        if level == 1 and not title:
            title = name
            current.end = offset
            raws.append(current)
            current = _Raw(["Introduction"], offset + len(line), offset + len(line))
        elif level:
            current.end = offset
            raws.append(current)
            stack = [(lv, nm) for lv, nm in stack if lv < level]
            stack.append((level, name))
            current = _Raw([nm for _, nm in stack], offset, offset)
        offset += len(line)
    current.end = offset
    raws.append(current)
    return title, raws


def _body_is_empty(section_text: str) -> bool:
    lines = [ln.strip() for ln in section_text.splitlines()]
    body = [
        ln
        for ln in lines
        if ln and ln != "---" and not _HEADING.match(ln) and not ln.startswith("**Q:")
    ]
    if section_text.lstrip().startswith("**") and len(body) == 1 and _BOLD_STEP.match(body[0]):
        return True
    return not body


def _blocks(text: str) -> list[str]:
    """Paragraphs, top-level list items and table rows: the places a section may split."""
    blocks: list[str] = []
    cur: list[str] = []

    def flush() -> None:
        if cur:
            blocks.append("".join(cur))
            cur.clear()

    for line in text.splitlines(keepends=True):
        s = line.strip()
        if not s:
            cur.append(line)
            flush()
        elif re.match(r"^(?:\d+\.|[-*+])\s", line) and cur:  # a new top-level list item
            flush()
            cur.append(line)
        else:
            cur.append(line)
    flush()
    return [b for b in blocks if b.strip()]


def _split_table(block: str, prefix: str, budget: int, count: Counter) -> list[str]:
    rows = block.splitlines(keepends=True)
    header, body = rows[:2], rows[2:]
    pieces: list[str] = []
    cur: list[str] = []
    for row in body:
        if cur and count(prefix + "".join(header + cur + [row])) > budget:
            pieces.append("".join(header + cur))
            cur = []
        cur.append(row)
    if cur:
        pieces.append("".join(header + cur))
    return pieces


def _split_long(block: str, prefix: str, budget: int, count: Counter) -> list[str]:
    """A single block still over budget: table rows, else lines, else sentences."""
    lines = block.splitlines(keepends=True)
    if len(lines) > 2 and all(ln.strip().startswith("|") for ln in lines if ln.strip()):
        return _split_table(block, prefix, budget, count)
    units = lines if len(lines) > 1 else re.split(r"(?<=[.!?])\s+", block)
    pieces: list[str] = []
    cur = ""
    for unit in units:
        if cur and count(prefix + cur + unit) > budget:
            pieces.append(cur)
            cur = ""
        cur += unit if len(lines) > 1 else unit + " "
    if cur.strip():
        pieces.append(cur)
    return pieces


def split_to_budget(text: str, prefix: str, budget: int, count: Counter) -> list[str]:
    """Greedy packing of blocks so `prefix + piece` stays within the budget."""
    if count(prefix + text) <= budget:
        return [text]
    pieces: list[str] = []
    cur = ""
    for block in _blocks(text):
        candidates = (
            [block]
            if count(prefix + block) <= budget
            else _split_long(block, prefix, budget, count)
        )
        for cand in candidates:
            if cur and count(prefix + cur + cand) > budget:
                pieces.append(cur)
                cur = ""
            cur += cand
    if cur.strip():
        pieces.append(cur)
    return pieces


def sections(
    doc_id: str,
    doc_type: str,
    text: str,
    *,
    budget: int = CHUNK_BUDGET,
    count: Counter = count_tokens,
) -> tuple[str, list[Section]]:
    """(title, chunks) for one sanitized document."""
    title, raws = _split_raw(text, faq=doc_type == "faq")
    out: list[Section] = []
    used: dict[str, int] = {}
    for raw in raws:
        body = text[raw.start : raw.end]
        if _body_is_empty(body):
            continue
        path = " > ".join(raw.path)
        base = slug(path)
        used[base] = used.get(base, 0) + 1
        sid = f"{doc_id}#{base}" + (f"-{used[base]}" if used[base] > 1 else "")
        prefix = f"{title} > {path}\n"
        pieces = split_to_budget(body.strip("\n") + "\n", prefix, budget, count)
        parent = sid if len(pieces) > 1 else None
        for n, piece in enumerate(pieces, start=1):
            piece_id = f"{sid}~{n}" if parent else sid
            index_text = prefix + piece.strip("\n")
            out.append(
                Section(
                    section_id=piece_id,
                    parent_section_id=parent,
                    doc_id=doc_id,
                    path=path,
                    ord=len(out),
                    text=piece.strip("\n"),
                    index_text=index_text,
                    token_count=count(index_text),
                    start=raw.start,
                    end=raw.end,
                )
            )
    return title, out
