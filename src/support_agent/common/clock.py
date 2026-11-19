"""Two kinds of time (S11 build step 6; D48, review M10).

- Ticket time (SLA, escalate-by, peak hours): wall time plus the ticket's offset.
  Live mode: offset 0. Replay mode: the ticket starts at its `date_opened`
  (offset = date_opened - wall at start) and each simulated store reply adds
  `REPLAY_REPLY_DELAY_MIN`; the offset is stored in `itsm.tickets.clock_offset`,
  so any process computes the ticket's own now. Measured run time advances it
  by itself, because wall time does.
- Human time (approval TTL): always wall time, on the agent and the itsm server.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


def wall_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class WallClock:
    """Human time (approval TTL)."""

    wall: Callable[[], datetime] = field(default=wall_now)

    def now(self) -> datetime:
        return self.wall()


@dataclass(frozen=True)
class TicketClock:
    """Ticket time: wall time plus the ticket's offset (0 live, replay otherwise)."""

    offset: timedelta = timedelta(0)
    wall: Callable[[], datetime] = field(default=wall_now)

    def now(self) -> datetime:
        return self.wall() + self.offset


def replay_offset(date_opened: datetime, wall: datetime | None = None) -> timedelta:
    """Replay starts the ticket's clock at its own `date_opened`."""
    return date_opened - (wall or wall_now())


def after_reply(offset: timedelta, delay_min: float) -> timedelta:
    """Replay: one simulated store-reply delay later (0 in live mode)."""
    return offset + timedelta(minutes=delay_min)
