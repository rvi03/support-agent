"""Rate limits per user and per store (S12 build step 5).

The `limits` library (the engine under slowapi, D27) with a moving window in
memory: one API process (D30). Writes count against the user and the token's
store; reads against the user. The eval runner, which replays a whole dataset
run, has its own limit (S14). slowapi's decorator is not used because it runs
before the token check, and the API's fixed order is JWT, size and schema, then
the rate limit, then OPA.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from limits import RateLimitItem, parse
from limits.storage import MemoryStorage
from limits.strategies import MovingWindowRateLimiter

from support_agent.api.auth import Subject

Kind = Literal["read", "write"]


@dataclass
class RateLimits:
    write_user: str = "20/minute"
    write_store: str = "60/minute"
    read_user: str = "240/minute"
    replay: str = "2000/minute"
    _limiter: MovingWindowRateLimiter = field(init=False)
    _items: dict[str, RateLimitItem] = field(init=False)

    def __post_init__(self) -> None:
        self._limiter = MovingWindowRateLimiter(MemoryStorage())
        self._items = {
            "write_user": parse(self.write_user),
            "write_store": parse(self.write_store),
            "read_user": parse(self.read_user),
            "replay": parse(self.replay),
        }

    def hit(self, subject: Subject, kind: Kind) -> str | None:
        """Count one request; return the name of the limit it broke, or None."""
        if subject.is_replayer:
            checks = [("replay", f"user:{subject.user}")]
        elif kind == "read":
            checks = [("read_user", f"user:{subject.user}")]
        else:
            checks = [("write_user", f"user:{subject.user}")]
            if subject.store_id:
                checks.append(("write_store", f"store:{subject.store_id}"))
        for name, key in checks:
            if not self._limiter.hit(self._items[name], key, kind):
                return name
        return None
