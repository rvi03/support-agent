"""The BM25 tokenizer (S6 build step 3; rag-design.md section 4, step 8).

One function runs at index time and at query time, so codes match exactly:

- plain words, lowercased;
- code-shaped tokens kept whole and also split into their parts
  (`ERR_TOKEN_EXPIRED` -> `err_token_expired`, `err`, `token`, `expired`;
  `E-402` -> `e-402`, `e`, `402`);
- versions kept whole, with or without the `v` (`v4.2.1` and `4.2.1` -> `v4.2.1`);
- the normalized code form: uppercase, no spaces or dashes (`E-02`, `E02` -> `E02`;
  `HTTP 503` -> `HTTP503`).

`terms()` turns tokens into the strings stored in `kb.sections.bm25_tokens`.
pg_textsearch runs Postgres' text parser on every array element, and that parser
splits `e-402`, `err_token_expired` and `v4.2.1`. So each token is encoded as
one alphanumeric word the parser keeps whole: separators are dropped and a
version's dots become `p` behind a `ver` prefix (`v4.2.1` -> `ver4p2p1`).
"""

from __future__ import annotations

import re

# Raw tokens: alphanumeric runs joined by _ - . (so `v4.2.1`, `E-402`, `TM-T88VI` stay together).
_RAW = re.compile(r"[A-Za-z0-9]+(?:[_.\-][A-Za-z0-9]+)*")
_VERSION = re.compile(r"[vV]?\d+(?:\.(?:\d+|[xX]))+[a-z]?")
_HTTP = re.compile(r"\bHTTP[\s_-]?(\d{3})\b", re.IGNORECASE)
_PARTS = re.compile(r"[_.\-]")
_SAFE = re.compile(r"[^a-z0-9]")

# Code shapes the exact-code rule acts on (rag-design.md section 7, step 4), plus
# the other code families in the KB tables (E1001, AUTH_ERR_0x0A, E-CLN-012).
CODE_PATTERNS = (
    r"E-?\d+",
    r"F0\d",
    r"ERR_[A-Z_]+",
    r"0x[0-9A-F]+",
    r"MOT_OVL_\d+",
    r"HTTP\s?\d{3}",
    r"[A-Z]{2,}(?:_[A-Za-z0-9]+)+",
    r"E-[A-Z]{2,4}-\d{2,4}",
)
_CODE = re.compile(r"(?<![\w-])(?:" + "|".join(CODE_PATTERNS) + r")(?![\w-])")


def is_version(token: str) -> bool:
    return _VERSION.fullmatch(token) is not None


def version_form(token: str) -> str:
    """`4.2.1`, `V4.2.1` -> `v4.2.1`; `v4.2.X` -> `v4.2.x`."""
    return "v" + token.lower().lstrip("v")


def is_code_shaped(token: str) -> bool:
    """A token with a separator, or with both letters and digits (E402, SG350, 0x0A)."""
    has_digit = any(c.isdigit() for c in token)
    has_alpha = any(c.isalpha() for c in token)
    return bool(_PARTS.search(token)) or (has_digit and has_alpha)


def normalize_code(code: str) -> str:
    """Uppercase, no spaces or dashes: `E-02` -> `E02`, `http 503` -> `HTTP503`."""
    return re.sub(r"[\s\-]", "", code).upper()


def codes_in(text: str) -> list[str]:
    """Normalized forms of the code-shaped tokens the exact-code rule acts on."""
    found = [normalize_code(m.group(0)) for m in _CODE.finditer(text)]
    return list(dict.fromkeys(found))


def token_groups(text: str) -> list[list[str]]:
    """One group per raw token: its whole form, then its parts and normalized form."""
    groups: list[list[str]] = [[f"HTTP{m.group(1)}"] for m in _HTTP.finditer(text)]
    for m in _RAW.finditer(text):
        raw = m.group(0)
        if is_version(raw):
            groups.append([version_form(raw)])
            continue
        if not is_code_shaped(raw):
            groups.append([raw.lower()])
            continue
        whole = raw.lower()
        group = [whole]
        parts = [p.lower() for p in _PARTS.split(raw) if p]
        if len(parts) > 1:
            group.extend(parts)
        norm = normalize_code(raw)
        if norm.lower() != whole:
            group.append(norm)
        groups.append(group)
    return groups


def tokenize(text: str) -> list[str]:
    """Tokens in text order (duplicates kept: BM25 counts term frequency)."""
    return [t for group in token_groups(text) for t in group]


def term(token: str) -> str:
    """The parser-safe form stored in `bm25_tokens` (one Postgres word per token)."""
    if token.startswith("v") and is_version(token):
        return "ver" + token[1:].lower().replace(".", "p")
    return _SAFE.sub("", token.lower())


def index_terms(text: str) -> list[str]:
    """Encoded terms; forms of one token that encode alike (`e-02`, `E02`) count once."""
    out: list[str] = []
    for group in token_groups(text):
        out.extend(t for t in dict.fromkeys(term(tok) for tok in group) if t)
    return out


def query_text(text: str) -> str:
    """The query string for `to_bm25query`: the same terms, space separated, deduplicated."""
    return " ".join(dict.fromkeys(index_terms(text)))
