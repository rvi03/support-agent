"""`make seed`: upload the dataset to S3, then load Postgres from S3 only (S3).

1. Every file under DATASET_DIR goes to `servewell/raw/<source path>` unchanged.
   An object whose bytes already hash to the local SHA-256 is skipped; after a
   put, the object is downloaded again and its bytes hashed (stored metadata is
   never trusted on its own). Each file gets a `data.raw_files` row.
2. The CSVs, train tickets and labels are read back from S3, each object's
   bytes checked against the manifest, cleaned and upserted in one transaction.
3. The split is rebuilt from the S3 bytes and must equal the committed
   `eval/split.json` byte for byte; it is then loaded into `eval.split`.

Run `python -m support_agent.ingest.seed` (all steps) or `... seed split` to
write `eval/split.json` from the uploaded labels (once, before any tuning).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import boto3
import psycopg
from botocore.config import Config
from botocore.exceptions import ClientError
from psycopg.types.json import Jsonb

from support_agent.common.config import IngestSettings, get_settings
from support_agent.ingest import csv_clean, split

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

BUCKET = "servewell"
RAW = "raw"
SPLIT_FILE = Path("eval/split.json")

CSV_KEYS = {
    "stores": "data/stores.csv",
    "version_matrix": "kb/system-specs/version-matrix.csv",
    "assets": "data/assets.csv",
    "sla_matrix": "data/sla_matrix.csv",
    "ticket_index": "tickets/train_index.csv",
}
LABELS_KEY = "labels/train_labels.json"
TRAIN_PREFIX = "tickets/train/"

# Intake-schema fields kept from a train ticket (design.md, Intake step 1).
TICKET_FIELDS = (
    "ticket_id",
    "store_id",
    "store_name",
    "submitted_by",
    "contact_phone",
    "date_opened",
    "priority",
    "category",
    "subcategory",
    "subject",
    "description",
    "asset_id",
    "system_version",
    "tags",
    "escalation_flag",
    "related_tickets",
    "ticket_history",
)
DROPPED_FIELDS = ("status", "resolution_notes")
JSON_FIELDS = ("tags", "related_tickets", "ticket_history")
LABEL_FIELDS = (
    "ticket_id",
    "correct_routing",
    "should_escalate",
    "escalation_reason",
    "expected_agent_action",
    "relevant_kb_docs",
    "correct_resolution_summary",
    "chaos_correct_behavior",
    "evaluator_notes",
)

# table -> (primary key columns, columns in insert order)
TABLES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "data.stores": (("store_id",), csv_clean.STORE_COLUMNS),
    "data.version_matrix": (
        ("system", "version"),
        (
            "system",
            "version",
            "release_date",
            "known_bugs",
            "patch_status",
            "patch_fix",
            "notes",
        ),
    ),
    "data.assets": (
        ("asset_id",),
        (*csv_clean.ASSET_COLUMNS[:6], "system_name", "version", *csv_clean.ASSET_COLUMNS[6:]),
    ),
    "data.sla_matrix": (("priority", "category"), csv_clean.SLA_COLUMNS),
    "tickets.source_staging": (("ticket_id",), TICKET_FIELDS),
    "eval.ticket_index": (("ticket_id",), csv_clean.INDEX_COLUMNS),
    "eval.labels": (("ticket_id",), LABEL_FIELDS),
    "eval.split": (("ticket_id",), ("ticket_id", "half", "cohort")),
}


class SeedError(RuntimeError):
    """A seed step failed; nothing after it ran."""


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def dataset_files(dataset_dir: Path) -> Iterator[tuple[str, Path]]:
    """(source path, file) for every file; dot files and dot folders are skipped."""
    for path in sorted(dataset_dir.rglob("*")):
        rel = path.relative_to(dataset_dir)
        if path.is_file() and not any(part.startswith(".") for part in rel.parts):
            yield rel.as_posix(), path


def s3_client(settings: IngestSettings) -> S3Client:
    client: S3Client = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key_ingest.get_secret_value(),
        aws_secret_access_key=settings.s3_secret_key_ingest.get_secret_value(),
        region_name="us-east-1",
        config=Config(s3={"addressing_style": "path"}, retries={"max_attempts": 3}),
    )
    return client


def _get(s3: S3Client, key: str) -> tuple[bytes, datetime] | None:
    try:
        obj = s3.get_object(Bucket=BUCKET, Key=key)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
            return None
        raise
    return obj["Body"].read(), obj["LastModified"]


@dataclass(frozen=True)
class Upload:
    key: str
    sha256: str
    size: int
    uploaded_at: datetime
    skipped: bool


def upload_file(s3: S3Client, source_path: str, data: bytes) -> Upload:
    key = f"{RAW}/{source_path}"
    digest = sha256_hex(data)
    current = _get(s3, key)
    if current is not None and sha256_hex(current[0]) == digest:
        return Upload(key, digest, len(data), current[1], skipped=True)
    s3.put_object(Bucket=BUCKET, Key=key, Body=data, Metadata={"sha256": digest})
    back = _get(s3, key)
    if back is None or sha256_hex(back[0]) != digest:
        raise SeedError(f"{key}: downloaded bytes do not match the local SHA-256")
    return Upload(key, digest, len(data), back[1], skipped=False)


def upload_all(s3: S3Client, conn: psycopg.Connection[Any], dataset_dir: Path) -> list[Upload]:
    if not dataset_dir.is_dir():
        raise SeedError(f"DATASET_DIR is not a folder: {dataset_dir}")
    uploads: list[Upload] = []
    for source_path, path in dataset_files(dataset_dir):
        up = upload_file(s3, source_path, path.read_bytes())
        # A row changes only when the file does, so a re-run leaves the table as it was.
        conn.execute(
            """
            INSERT INTO data.raw_files (path, sha256, bytes, uploaded_at)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (path) DO UPDATE
              SET sha256 = excluded.sha256, bytes = excluded.bytes,
                  uploaded_at = excluded.uploaded_at
              WHERE data.raw_files.sha256 IS DISTINCT FROM excluded.sha256
            """,
            (up.key, up.sha256, up.size, up.uploaded_at),
        )
        uploads.append(up)
    conn.commit()
    if not uploads:
        raise SeedError(f"No files in {dataset_dir}")
    return uploads


class RawReader:
    """Reads `raw/` objects and checks each one's bytes against the manifest."""

    def __init__(self, s3: S3Client, conn: psycopg.Connection[Any]) -> None:
        self.s3 = s3
        rows = conn.execute("SELECT path, sha256 FROM data.raw_files").fetchall()
        self.manifest: dict[str, str] = {path: digest for path, digest in rows}

    def read(self, source_path: str) -> bytes:
        key = f"{RAW}/{source_path}"
        expected = self.manifest.get(key)
        if expected is None:
            raise SeedError(f"{key} is not in data.raw_files; upload first")
        got = _get(self.s3, key)
        if got is None:
            raise SeedError(f"{key} is missing from S3")
        if sha256_hex(got[0]) != expected:
            raise SeedError(f"{key}: S3 bytes do not match the manifest SHA-256")
        return got[0]

    def text(self, source_path: str) -> str:
        return self.read(source_path).decode("utf-8")

    def keys(self, prefix: str) -> list[str]:
        start = f"{RAW}/{prefix}"
        return sorted(k[len(RAW) + 1 :] for k in self.manifest if k.startswith(start))


def ticket_row(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Keep the intake-schema fields; `status` and `resolution_notes` never pass (CP3.3)."""
    unknown = set(raw) - set(TICKET_FIELDS) - set(DROPPED_FIELDS)
    if unknown:
        raise SeedError(f"{raw.get('ticket_id')}: unexpected fields {sorted(unknown)}")
    row = {field: raw.get(field) for field in TICKET_FIELDS}
    row["date_opened"] = datetime.fromisoformat(str(row["date_opened"]))
    for field in JSON_FIELDS:
        row[field] = row[field] if row[field] is not None else []
    return row


def label_row(raw: Mapping[str, Any]) -> dict[str, Any]:
    if set(raw) != set(LABEL_FIELDS):
        raise SeedError(f"{raw.get('ticket_id')}: label fields {sorted(raw)}")
    return dict(raw)


def upsert(conn: psycopg.Connection[Any], table: str, rows: Sequence[Mapping[str, Any]]) -> None:
    pk, columns = TABLES[table]
    updates = [c for c in columns if c not in pk]
    names = ", ".join(columns)
    marks = ", ".join(["%s"] * len(columns))
    sets = ", ".join(f"{c} = excluded.{c}" for c in updates)
    sql = (
        f"INSERT INTO {table} ({names}) VALUES ({marks}) "  # noqa: S608 - fixed table/column names
        f"ON CONFLICT ({', '.join(pk)}) DO UPDATE SET {sets}"
    )
    with conn.cursor() as cur:
        cur.executemany(
            sql,
            [
                tuple(Jsonb(row[c]) if isinstance(row[c], list | dict) else row[c] for c in columns)
                for row in rows
            ],
        )


@dataclass
class Loaded:
    index_rows: list[dict[str, Any]]
    labels: list[dict[str, Any]]
    labels_sha256: str
    index_sha256: str


def read_eval_inputs(reader: RawReader) -> Loaded:
    index_bytes = reader.read(CSV_KEYS["ticket_index"])
    labels_bytes = reader.read(LABELS_KEY)
    labels = [label_row(item) for item in json.loads(labels_bytes)]
    return Loaded(
        index_rows=csv_clean.parse_ticket_index(index_bytes.decode("utf-8")),
        labels=labels,
        labels_sha256=sha256_hex(labels_bytes),
        index_sha256=sha256_hex(index_bytes),
    )


def build_split(loaded: Loaded) -> dict[str, Any]:
    return split.make_split(
        loaded.index_rows,
        loaded.labels,
        seed=split.SEED,
        labels_sha256=loaded.labels_sha256,
        index_sha256=loaded.index_sha256,
    )


def load_all(conn: psycopg.Connection[Any], reader: RawReader, split_file: Path) -> dict[str, int]:
    """Clean and upsert every table in one transaction; return rows per table."""
    data = {
        "data.stores": csv_clean.parse_stores(reader.text(CSV_KEYS["stores"])),
        "data.version_matrix": csv_clean.parse_version_matrix(
            reader.text(CSV_KEYS["version_matrix"])
        ),
        "data.assets": csv_clean.parse_assets(reader.text(CSV_KEYS["assets"])),
        "data.sla_matrix": csv_clean.parse_sla(reader.text(CSV_KEYS["sla_matrix"])),
    }
    loaded = read_eval_inputs(reader)
    for row in loaded.index_rows:
        if row["filename"] != f"{TRAIN_PREFIX}{row['ticket_id']}.json":
            raise SeedError(f"{row['ticket_id']}: index filename {row['filename']}")
    index_files = {row["filename"] for row in loaded.index_rows}
    train_keys = {k for k in reader.keys(TRAIN_PREFIX) if k.endswith(".json")}
    if train_keys != index_files:
        raise SeedError(
            f"train tickets in S3 and train_index differ: {sorted(train_keys ^ index_files)[:10]}"
        )
    tickets = []
    for key in sorted(train_keys):
        raw = json.loads(reader.read(key))
        if f"{TRAIN_PREFIX}{raw['ticket_id']}.json" != key:
            raise SeedError(f"{key} holds ticket {raw['ticket_id']}")
        tickets.append(ticket_row(raw))
    data["tickets.source_staging"] = tickets
    data["eval.ticket_index"] = loaded.index_rows
    data["eval.labels"] = loaded.labels

    committed = split_file.read_bytes() if split_file.exists() else None
    if committed is None:
        raise SeedError(f"{split_file} is missing; run `make split` once and commit it")
    rebuilt = split.dumps(build_split(loaded))
    if rebuilt != committed:
        raise SeedError(
            f"{split_file} differs from the split rebuilt with seed {split.SEED}: "
            "the source data or the split code changed"
        )
    data["eval.split"] = [
        {"ticket_id": t, "half": h, "cohort": c} for t, h, c in split.rows(json.loads(committed))
    ]

    with conn.transaction():
        for table, rows in data.items():
            upsert(conn, table, rows)
    return {table: len(rows) for table, rows in data.items()}


def write_split(reader: RawReader, split_file: Path) -> bytes:
    body = split.dumps(build_split(read_eval_inputs(reader)))
    split_file.parent.mkdir(parents=True, exist_ok=True)
    split_file.write_bytes(body)
    return body


def _print_summary(summary: Mapping[str, Mapping[str, Any]]) -> None:
    for name, info in summary.items():
        cats = ", ".join(f"{c} {s:.1%}" for c, s in info["category_share"].items())
        trick = ", ".join(f"{t} {n}" for t, n in info["chaos_types"].items())
        print(
            f"  {name:8} labelled {info['labelled']:3}  tricky {info['tricky']:2}  "
            f"escalate {info['escalate_share']:.1%}\n"
            f"           categories: {cats}\n"
            f"           trick types: {trick}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m support_agent.ingest.seed")
    parser.add_argument("command", nargs="?", default="seed", choices=("seed", "split"))
    parser.add_argument("--split-file", type=Path, default=SPLIT_FILE)
    args = parser.parse_args(argv)

    settings = get_settings(IngestSettings)
    s3 = s3_client(settings)
    try:
        with psycopg.connect(settings.database_url_ingest.get_secret_value()) as conn:
            if args.command == "split":
                reader = RawReader(s3, conn)
                body = write_split(reader, args.split_file)
                print(f"Wrote {args.split_file} ({split.sha256_hex(body)[:12]})")
                return 0
            uploads = upload_all(s3, conn, settings.dataset_dir)
            done = sum(not u.skipped for u in uploads)
            print(f"S3 raw/: {len(uploads)} files ({done} uploaded, {len(uploads) - done} same)")
            reader = RawReader(s3, conn)
            counts = load_all(conn, reader, args.split_file)
            for table, count in counts.items():
                print(f"  {table:24} {count:4} rows")
            loaded = read_eval_inputs(reader)
            print(f"Split (seed {split.SEED}):")
            committed = json.loads(args.split_file.read_bytes())
            _print_summary(split.summary(committed, loaded.index_rows, loaded.labels))
    except (SeedError, csv_clean.CleaningError, split.SplitError) as exc:
        print(f"Seed failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
