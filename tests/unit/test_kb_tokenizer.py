"""CP6.4 (tokenizer half): every KB error-table code and every assets.csv version
tokenizes to its whole form and its normalized form, at index and query time."""

from __future__ import annotations

import pytest

from support_agent.mcp.knowledge import tokenizer as tk
from tests.kb_data import asset_versions, error_table_codes

pytestmark = pytest.mark.unit


def _all_codes() -> list[str]:
    return sorted({c for codes in error_table_codes().values() for c in codes})


def test_the_kb_has_error_tables() -> None:
    codes = _all_codes()
    assert len(codes) >= 60
    assert {"E02", "F01", "E-1", "E1001", "ERR_TOKEN_EXPIRED", "AUTH_ERR_0x0A", "E201"} <= set(
        codes
    )


@pytest.mark.parametrize("code", _all_codes())
def test_code_keeps_whole_and_normalized_form(code: str) -> None:
    tokens = tk.tokenize(f"the screen shows {code} again")
    assert code.lower() in tokens
    norm = tk.normalize_code(code)
    assert norm in tokens or norm.lower() == code.lower()
    # The stored term of the whole and the normalized form is one word, found at query time.
    terms = tk.index_terms(f"error {code}")
    assert tk.term(norm) in terms and tk.term(code.lower()) in terms
    assert tk.term(norm) in tk.query_text(code).split()
    assert tk.term(norm).isalnum()


@pytest.mark.parametrize("version", sorted(asset_versions()))
def test_version_kept_whole(version: str) -> None:
    form = tk.version_form(version)
    assert form in tk.tokenize(f"FoodTech POS {version} crashed")
    assert tk.term(form) in tk.index_terms(f"running {version}")
    # With or without the v: the same term.
    assert tk.term(tk.version_form(version.lstrip("vV"))) == tk.term(form)
    assert tk.term(form).isalnum()


def test_split_parts_and_normal_forms() -> None:
    assert tk.tokenize("ERR_TOKEN_EXPIRED") == ["err_token_expired", "err", "token", "expired"]
    assert tk.tokenize("E-402") == ["e-402", "e", "402", "E402"]
    assert tk.normalize_code("E-02") == tk.normalize_code("E02") == "E02"
    assert "HTTP503" in tk.tokenize("got HTTP 503 from the portal")
    assert tk.codes_in("E-02 then F06 and ERR_AUTH_FAILED, HTTP 401") == [
        "E02", "F06", "ERR_AUTH_FAILED", "HTTP401",
    ]  # fmt: skip


def test_dash_and_no_dash_codes_meet() -> None:
    assert set(tk.index_terms("E-02")) >= {"e02"}
    assert set(tk.index_terms("E02")) >= {"e02"}
    assert tk.term("v4.2.x") == "ver4p2px"
    assert tk.index_terms("Printer OFFLINE") == ["printer", "offline"]
