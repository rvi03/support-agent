"""common/audit.py: one row per event, and a failed write fails the step."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from support_agent.common.audit import AuditEvent, AuditWriteError, write_event

pytestmark = pytest.mark.unit


class FakeConn:
    def __init__(self, row: tuple[int] | None = (7,), error: Exception | None = None) -> None:
        self.row, self.error = row, error
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def execute(self, query: str, params: tuple[Any, ...]) -> FakeConn:
        if self.error:
            raise self.error
        self.calls.append((query, params))
        return self

    def fetchone(self) -> tuple[int] | None:
        return self.row


def _event(**kw: Any) -> AuditEvent:
    base: dict[str, Any] = {"step": "triage", "actor": "agent", "action": "route", "result": "ok"}
    return AuditEvent(**{**base, **kw})


def test_writes_one_row_and_returns_its_id() -> None:
    conn = FakeConn()
    run = uuid.uuid4()
    assert write_event(conn, _event(run_id=run, ticket_id="INC-1", payload={"k": 1})) == 7
    ((query, params),) = conn.calls
    assert query.startswith("INSERT INTO audit.events (step, actor, action, result, run_id")
    assert params[:6] == ("triage", "agent", "route", "ok", run, "INC-1")


def test_failed_write_raises() -> None:
    with pytest.raises(AuditWriteError, match="triage/route"):
        write_event(FakeConn(error=RuntimeError("db down")), _event())


def test_no_id_raises() -> None:
    with pytest.raises(AuditWriteError):
        write_event(FakeConn(row=None), _event())


@pytest.mark.parametrize("missing", ["step", "actor", "action", "result"])
def test_required_fields(missing: str) -> None:
    with pytest.raises(ValueError, match=missing):
        _event(**{missing: ""})
