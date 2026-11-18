"""CP1.3: the log filter removes phone and name patterns from every sink."""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from support_agent.common import pii_filter
from support_agent.common.logging import (
    bind_ticket,
    clear_exact_values,
    configure_logging,
    get_logger,
    register_exact_values,
    unbind_ticket,
)

pytestmark = pytest.mark.unit

TICKET = "INC-00045"
EXACT_NAME = "Testa Mockwell"  # a submitter-style name no pattern would catch
PII = [
    "+91-90000-00001",
    "9000000002",
    "+91 90000 00003",
    "+919000000004",
    "Fixtura Testkar",
    "store.manager@servewell.in",
    EXACT_NAME,
]
KEEP = ["INC-00045", "POS-0012-T1", "E-402", "v4.2.1", "ERR-4521", "2026-11-18T10:00:00Z"]
LINE = (
    "L1 Agent - Fixtura Testkar called +91-90000-00001 and 9000000002, alt +91 90000 00003 "
    "/ +919000000004, mail store.manager@servewell.in, submitter Testa Mockwell; "
    "ticket INC-00045 asset POS-0012-T1 error E-402 ERR-4521 on v4.2.1 at 2026-11-18T10:00:00Z"
)


@pytest.fixture
def log_file(tmp_path: Path) -> Iterator[Path]:
    path = configure_logging("unit", tmp_path)
    register_exact_values(TICKET, [EXACT_NAME])
    yield path
    clear_exact_values(TICKET)
    unbind_ticket()


def _assert_clean(text: str) -> None:
    for value in PII:
        assert value not in text, value
    assert "Testa" not in text and "Fixtura" not in text
    for value in KEEP:
        assert value in text, value


def _events(path: Path) -> list[dict[str, object]]:
    for handler in logging.getLogger().handlers:
        handler.flush()
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_structlog_line_is_clean_in_stdout_and_file(
    log_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bind_ticket(TICKET)
    get_logger("test").info(LINE, note={"history": [LINE]})

    out = capsys.readouterr().out
    _assert_clean(out)
    events = _events(log_file)
    assert len(events) == 1
    assert events[0]["ticket_id"] == TICKET
    _assert_clean(json.dumps(events[0]))
    assert "L1 Agent - [PERSON]" in str(events[0]["event"])


def test_stdlib_logger_with_args_and_extra_is_clean(
    log_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    logging.getLogger("uvicorn.access").warning("%s", LINE, extra={"ticket_id": TICKET})

    _assert_clean(capsys.readouterr().out)
    _assert_clean(json.dumps(_events(log_file)))


def test_worker_thread_without_bound_context_is_clean(
    log_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def work() -> None:
        get_logger("scheduler").info("sla check", ticket_id=TICKET, detail=LINE)
        logging.getLogger("apscheduler").info(LINE)

    thread = threading.Thread(target=work)
    thread.start()
    thread.join()

    _assert_clean(capsys.readouterr().out)
    events = _events(log_file)
    assert len(events) == 2
    _assert_clean(json.dumps(events))


def test_exception_traceback_is_clean(log_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    try:
        raise ValueError(f"bad contact {PII[0]} for {EXACT_NAME}")
    except ValueError:
        get_logger("test").exception("failed", ticket_id=TICKET)

    out = capsys.readouterr().out
    assert PII[0] not in out and EXACT_NAME not in out
    assert "ValueError" in out


def test_exact_values_match_case_and_phone_separators() -> None:
    register_exact_values("INC-1", ["Testa Mockwell", "90000 00005"])
    try:
        text = pii_filter.scrub_text(
            "TESTA MOCKWELL at 9000000005 or +91-90000-00005, Mockwellville"
        )
    finally:
        clear_exact_values("INC-1")

    assert "TESTA" not in text and "90000" not in text and "9000000005" not in text
    assert "Mockwellville" in text  # whole words only


def test_cleared_and_expired_values_stop_matching() -> None:
    register_exact_values("INC-2", ["Zubin"])
    clear_exact_values("INC-2")
    assert pii_filter.scrub_text("Zubin") == "Zubin"

    register_exact_values("INC-3", ["Zubin"], ttl_seconds=0)
    assert pii_filter.scrub_text("Zubin") == "Zubin"


@pytest.mark.parametrize(
    "text",
    ["INC-00045", "POS-0012-T1", "1763452800", "12345678901234", "id-9000000002123", "v10.2.3"],
)
def test_non_phone_numbers_survive(text: str) -> None:
    assert pii_filter.scrub_text(text) == text


def test_scrub_keeps_non_text_types() -> None:
    event = {"n": 3, "ok": True, "none": None, "f": 1.5, "s": {"9000000002"}, "_record": object()}
    out = pii_filter.pii_filter_processor(None, "info", dict(event))

    assert out["n"] == 3 and out["ok"] is True and out["none"] is None and out["f"] == 1.5
    assert out["s"] == ["[PHONE]"]
    assert out["_record"] is event["_record"]
    assert pii_filter.pii_filter_processor(None, "info", {"p": Path("/x/9000000002")}) == {
        "p": "/x/[PHONE]"
    }
