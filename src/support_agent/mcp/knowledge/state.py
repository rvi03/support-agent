"""Per-run state of the knowledge server in Valkey (S6 step 5).

- KB-text budget: tokens of KB text returned, counted per (run_id, ticket_id) with a
  TTL; over the limit a call returns a typed `budget_exceeded` result.
- Exclusions: doc ids the `eval-runner` left out for one run_id (abstention test).
  Read on every search and document call of that run; set only by `eval-runner`.
Keys expire after a day; no ticket run outlasts that.
"""

from __future__ import annotations

import uuid
from typing import Protocol

TTL_S = 24 * 3600


class Store(Protocol):
    async def incr_budget(self, key: str, tokens: int) -> int: ...
    async def get_budget(self, key: str) -> int: ...
    async def add_exclusions(self, run_id: uuid.UUID, doc_ids: list[str]) -> list[str]: ...
    async def exclusions(self, run_id: uuid.UUID) -> frozenset[str]: ...


def budget_key(run_id: uuid.UUID | None, ticket_id: str | None) -> str | None:
    """No run and no ticket (a bare tool call): nothing to count against."""
    if run_id is None and ticket_id is None:
        return None
    return f"kb:budget:{run_id or '-'}:{ticket_id or '-'}"


class ValkeyStore:
    def __init__(self, url: str) -> None:
        import valkey.asyncio as valkey

        self._db = valkey.from_url(url, decode_responses=True)  # type: ignore[no-untyped-call]

    async def incr_budget(self, key: str, tokens: int) -> int:
        async with self._db.pipeline(transaction=True) as pipe:
            pipe.incrby(key, tokens)
            pipe.expire(key, TTL_S)
            used, _ = await pipe.execute()
        return int(used)

    async def get_budget(self, key: str) -> int:
        value = await self._db.get(key)
        return int(value or 0)

    async def add_exclusions(self, run_id: uuid.UUID, doc_ids: list[str]) -> list[str]:
        key = f"kb:excl:{run_id}"
        async with self._db.pipeline(transaction=True) as pipe:
            pipe.sadd(key, *doc_ids)
            pipe.expire(key, TTL_S)
            pipe.smembers(key)
            _, _, members = await pipe.execute()
        return sorted(members)

    async def exclusions(self, run_id: uuid.UUID) -> frozenset[str]:
        return frozenset(await self._db.smembers(f"kb:excl:{run_id}"))


class MemoryStore:
    """For unit tests."""

    def __init__(self) -> None:
        self.budgets: dict[str, int] = {}
        self.excluded: dict[uuid.UUID, set[str]] = {}

    async def incr_budget(self, key: str, tokens: int) -> int:
        self.budgets[key] = self.budgets.get(key, 0) + tokens
        return self.budgets[key]

    async def get_budget(self, key: str) -> int:
        return self.budgets.get(key, 0)

    async def add_exclusions(self, run_id: uuid.UUID, doc_ids: list[str]) -> list[str]:
        self.excluded.setdefault(run_id, set()).update(doc_ids)
        return sorted(self.excluded[run_id])

    async def exclusions(self, run_id: uuid.UUID) -> frozenset[str]:
        return frozenset(self.excluded.get(run_id, set()))
