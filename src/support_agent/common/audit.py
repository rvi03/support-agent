"""Write one audit event, or fail the step (D9: "audit or the step fails").

`audit.events` is append-only (db/sql/003_audit.sql). Callers pass their own
connection (their service role); a failed write raises AuditWriteError, so
the step that tried to write it fails too. Text fields must already be
masked: this module stores what it is given.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

from psycopg.types.json import Jsonb


class AuditWriteError(RuntimeError):
    """The audit event was not written; the calling step must fail."""


class _Connection(Protocol):
    def execute(self, query: Any, params: Any = ..., /) -> Any: ...


@dataclass(frozen=True)
class AuditEvent:
    step: str
    actor: str
    action: str
    result: str
    run_id: uuid.UUID | None = None
    ticket_id: str | None = None
    reason: str | None = None
    source: str | None = None
    kb_rev: str | None = None
    step_id: str | None = None
    action_id: str | None = None
    tier: str | None = None
    autonomy_state: str | None = None
    approval_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("step", "actor", "action", "result"):
            if not getattr(self, name):
                raise ValueError(f"audit event needs a non-empty {name}")


_COLUMNS = tuple(AuditEvent.__dataclass_fields__)
_INSERT = (
    f"INSERT INTO audit.events ({', '.join(_COLUMNS)}) "  # noqa: S608 - fixed column list
    f"VALUES ({', '.join(['%s'] * len(_COLUMNS))}) RETURNING id"
)


def write_event(conn: _Connection, event: AuditEvent) -> int:
    """Insert `event` and return its id; raise AuditWriteError on any failure."""
    values = asdict(event)
    values["payload"] = Jsonb(values["payload"])
    try:
        row = conn.execute(_INSERT, tuple(values[c] for c in _COLUMNS)).fetchone()
    except Exception as exc:
        raise AuditWriteError(f"audit write failed for {event.step}/{event.action}") from exc
    if not row:
        raise AuditWriteError(f"audit write returned no id for {event.step}/{event.action}")
    return int(row[0])
