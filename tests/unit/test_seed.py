"""ingest/seed.py pure parts: file walk, ticket field filter, label check, upload logic."""

from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from botocore.exceptions import ClientError

from support_agent.ingest import seed

pytestmark = pytest.mark.unit


def test_dataset_files_keeps_source_paths_and_skips_dot_files(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "stores.csv").write_text("x")
    (tmp_path / ".gitignore").write_text("x")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("x")
    (tmp_path / "README.md").write_text("x")
    assert [p for p, _ in seed.dataset_files(tmp_path)] == ["README.md", "data/stores.csv"]


def _ticket(**extra: Any) -> dict[str, Any]:
    return {
        "ticket_id": "INC-00001",
        "store_id": "SW-0023",
        "date_opened": "2026-04-04T10:01:00+05:30",
        "subject": "s",
        "description": "d",
        "tags": None,
        "status": "Closed",
        "resolution_notes": "Fixed by reseating the cable",
        **extra,
    }


def test_ticket_row_drops_status_and_resolution_notes() -> None:
    row = seed.ticket_row(_ticket())
    assert "status" not in row and "resolution_notes" not in row
    assert set(row) == set(seed.TICKET_FIELDS)
    assert row["tags"] == [] and row["ticket_history"] == []
    assert row["date_opened"].isoformat() == "2026-04-04T10:01:00+05:30"


def test_ticket_row_refuses_unknown_fields() -> None:
    with pytest.raises(seed.SeedError, match="unexpected fields"):
        seed.ticket_row(_ticket(extra_field="x"))


def test_label_row_needs_exact_fields() -> None:
    label = dict.fromkeys(seed.LABEL_FIELDS, "x")
    assert seed.label_row(label) == label
    with pytest.raises(seed.SeedError):
        seed.label_row({**label, "extra": 1})


class FakeS3:
    """Stores objects; `corrupt` makes every read return other bytes."""

    def __init__(self, corrupt: bool = False) -> None:
        self.objects: dict[str, bytes] = {}
        self.puts = 0
        self.corrupt = corrupt

    def get_object(self, Bucket: str, Key: str) -> dict[str, Any]:  # noqa: N803
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        body = b"tampered" if self.corrupt else self.objects[Key]
        return {"Body": BytesIO(body), "LastModified": datetime(2026, 11, 18, tzinfo=UTC)}

    def put_object(self, Bucket: str, Key: str, Body: bytes, Metadata: dict[str, str]) -> None:  # noqa: N803
        self.objects[Key] = Body
        self.puts += 1


def test_upload_puts_once_then_skips_matching_bytes() -> None:
    s3 = FakeS3()
    first = seed.upload_file(s3, "data/stores.csv", b"abc")  # type: ignore[arg-type]
    second = seed.upload_file(s3, "data/stores.csv", b"abc")  # type: ignore[arg-type]
    assert first.key == "raw/data/stores.csv" and not first.skipped
    assert second.skipped and s3.puts == 1
    assert first.sha256 == seed.sha256_hex(b"abc")


def test_upload_replaces_changed_bytes() -> None:
    s3 = FakeS3()
    seed.upload_file(s3, "a.csv", b"old")  # type: ignore[arg-type]
    up = seed.upload_file(s3, "a.csv", b"new")  # type: ignore[arg-type]
    assert not up.skipped and s3.objects["raw/a.csv"] == b"new"


def test_upload_fails_when_downloaded_bytes_differ() -> None:
    with pytest.raises(seed.SeedError, match="downloaded bytes"):
        seed.upload_file(FakeS3(corrupt=True), "a.csv", b"abc")  # type: ignore[arg-type]


def test_other_s3_errors_are_raised() -> None:
    class Denied(FakeS3):
        def get_object(self, Bucket: str, Key: str) -> dict[str, Any]:  # noqa: N803
            raise ClientError({"Error": {"Code": "AccessDenied"}}, "GetObject")

    with pytest.raises(ClientError):
        seed.upload_file(Denied(), "a.csv", b"abc")  # type: ignore[arg-type]
