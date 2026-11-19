"""S14 build step 1: the Langfuse dataset `servewell-256` (D39, D52, D56, Codex F4).

One item per dataset ticket (220 labelled + 36 tricky), holding a sanitized
projection only:

- input: the masked ticket from `tickets.source_tickets` (no contact field exists
  there, D59) and the `source_ticket_id` the runner replays by (D52);
- expected_output: the label, when the ticket has one;
- metadata: split half and cohort (eval/split.json via `eval.split`), the trick
  type, the fault-card id (the ticket id when `eval/fault_cards/<ticket>.yaml`
  exists, else null) and the item hash.

Label text is not masked at seed time, so every string in an item goes through
the log PII filter (`scrub_text`: actor names, emails, phones); any change refuses
the push and names the ticket, because nothing unmasked may reach Langfuse.
An item is re-pushed only when its hash changes; the split counts must equal
split.json, and an unknown item already in the dataset stops the push.

Usage: `make eval-dataset` (`python -m support_agent.eval.dataset [--dry-run]`).
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

import psycopg

from support_agent.common.config import EvalSettings, get_settings
from support_agent.common.db import dsn
from support_agent.common.pii_filter import scrub_text

ROOT = Path(__file__).resolve().parents[3]
SPLIT_FILE = ROOT / "eval" / "split.json"
CARDS_DIR = ROOT / "eval" / "fault_cards"
DATASET = "servewell-256"
ITEM_PREFIX = "sw256-"  # Langfuse item ids are unique per project, not per dataset
TICKET_COLUMNS = (
    "ticket_id", "store_id", "store_name", "date_opened", "priority", "category",
    "subcategory", "subject", "description", "asset_id", "system_version", "tags",
    "escalation_flag", "related_tickets", "ticket_history",
)  # fmt: skip
LABEL_COLUMNS = (
    "correct_routing", "should_escalate", "escalation_reason", "expected_agent_action",
    "relevant_kb_docs", "correct_resolution_summary", "chaos_correct_behavior",
    "evaluator_notes",
)  # fmt: skip


class DatasetError(RuntimeError):
    pass


@dataclass(frozen=True)
class Item:
    id: str
    input: dict[str, Any]
    expected_output: dict[str, Any] | None
    metadata: dict[str, Any]

    @property
    def hash(self) -> str:
        return str(self.metadata["hash"])


def _plain(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, list | tuple):
        for v in value:
            yield from _strings(v)


def item_hash(body: Mapping[str, Any]) -> str:
    raw = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode()).hexdigest()


def build_item(
    ticket: Mapping[str, Any],
    label: Mapping[str, Any] | None,
    *,
    half: str,
    cohort: str,
    chaos_type: str | None,
    has_card: bool,
) -> Item:
    tid = str(ticket["ticket_id"])
    inp = {k: _plain(ticket[k]) for k in TICKET_COLUMNS if ticket.get(k) is not None}
    inp["source_ticket_id"] = tid
    expected = {k: _plain(label[k]) for k in LABEL_COLUMNS} if label is not None else None
    meta: dict[str, Any] = {
        "ticket_id": tid,
        "split": half,
        "cohort": cohort,
        "chaos_type": chaos_type,
        "fault_card": tid if has_card else None,
    }
    for text in _strings([inp, expected, meta]):
        if scrub_text(text) != text:
            raise DatasetError(f"{tid}: unmasked contact-like text in the item; not pushed")
    meta["hash"] = item_hash({"input": inp, "expected_output": expected, "metadata": meta})
    return Item(ITEM_PREFIX + tid, inp, expected, meta)


def check_counts(items: list[Item], split: Mapping[str, Any]) -> None:
    want = Counter(
        {(h, c): len(split[h][c]) for h in ("tune", "heldout") for c in ("labelled", "tricky")}
    )
    got = Counter((i.metadata["split"], i.metadata["cohort"]) for i in items)
    if got != want:
        raise DatasetError(f"split counts {dict(got)} differ from split.json {dict(want)}")
    for i in items:
        if (i.expected_output is None) != (i.metadata["cohort"] == "tricky"):
            raise DatasetError(f"{i.metadata['ticket_id']}: label presence does not fit its cohort")


def load_items(conn: psycopg.Connection[Any], cards_dir: Path = CARDS_DIR) -> list[Item]:
    cols = ", ".join(f"t.{c}" for c in TICKET_COLUMNS)
    labels = ", ".join(f"l.{c}" for c in LABEL_COLUMNS)
    cur = conn.execute(
        f"SELECT {cols}, s.half, s.cohort, i.chaos_type, l.ticket_id IS NOT NULL, {labels} "  # noqa: S608
        "FROM eval.split s JOIN tickets.source_tickets t USING (ticket_id) "
        "LEFT JOIN eval.ticket_index i USING (ticket_id) "
        "LEFT JOIN eval.labels l USING (ticket_id) ORDER BY t.ticket_id"
    )
    n = len(TICKET_COLUMNS)
    items = []
    for row in cur.fetchall():
        ticket = dict(zip(TICKET_COLUMNS, row[:n], strict=True))
        half, cohort, chaos, labelled = row[n : n + 4]
        label = dict(zip(LABEL_COLUMNS, row[n + 4 :], strict=True)) if labelled else None
        has_card = (cards_dir / f"{ticket['ticket_id']}.yaml").is_file()
        items.append(
            build_item(ticket, label, half=half, cohort=cohort, chaos_type=chaos, has_card=has_card)
        )
    return items


class DatasetClient(Protocol):
    def existing(self) -> dict[str, str | None] | None:
        """Item id -> stored hash, or None when the dataset does not exist."""
        ...

    def create(self) -> None: ...
    def upsert(self, item: Item) -> None: ...


@dataclass
class PushResult:
    created: int
    updated: int
    unchanged: int


def push(client: DatasetClient, items: list[Item]) -> PushResult:
    hashes = client.existing()
    if hashes is None:
        client.create()
        hashes = {}
    ours = {i.id for i in items}
    stray = sorted(set(hashes) - ours)
    if stray:
        raise DatasetError(f"{DATASET} holds items not in the 256: {stray[:5]}")
    created = updated = 0
    for item in items:
        if item.id not in hashes:
            created += 1
        elif hashes[item.id] != item.hash:
            updated += 1
        else:
            continue
        client.upsert(item)
    return PushResult(created, updated, len(items) - created - updated)


class LangfuseDataset:
    def __init__(self, settings: EvalSettings) -> None:
        from langfuse import Langfuse

        if not (
            settings.langfuse_public_key and settings.langfuse_secret_key and settings.langfuse_host
        ):
            raise SystemExit(
                "LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY and LANGFUSE_HOST are needed"
            )
        self.lf = Langfuse(
            public_key=settings.langfuse_public_key.get_secret_value(),
            secret_key=settings.langfuse_secret_key.get_secret_value(),
            host=settings.langfuse_host,
        )

    def existing(self) -> dict[str, str | None] | None:
        from langfuse.api import NotFoundError

        try:
            items = self.lf.get_dataset(DATASET, fetch_items_page_size=100).items
        except NotFoundError:
            return None
        return {i.id: (i.metadata or {}).get("hash") for i in items}

    def create(self) -> None:
        self.lf.create_dataset(
            name=DATASET,
            description="ServeWell 256 dataset tickets, masked; split tags from eval/split.json",
        )

    def upsert(self, item: Item) -> None:
        self.lf.create_dataset_item(
            dataset_name=DATASET,
            id=item.id,
            input=item.input,
            expected_output=item.expected_output,
            metadata=item.metadata,
        )

    def flush(self) -> None:
        self.lf.flush()


def main(argv: list[str]) -> int:
    settings = get_settings(EvalSettings)
    split = json.loads(SPLIT_FILE.read_text())
    with psycopg.connect(dsn(settings.database_url_eval, settings.db_host)) as conn:
        items = load_items(conn)
    check_counts(items, split)
    cards = sum(1 for i in items if i.metadata["fault_card"])
    print(f"{len(items)} items built, {cards} with a fault card")
    if "--dry-run" in argv:
        return 0
    client = LangfuseDataset(settings)
    result = push(client, items)
    client.flush()
    print(
        f"{DATASET}: {result.created} created, {result.updated} updated, "
        f"{result.unchanged} unchanged"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except DatasetError as exc:
        print(f"eval-dataset: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
