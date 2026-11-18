"""The 4 CSV cleaning rules (design.md, CSV cleaning) and the CSV row parsers.

Each parser takes the raw CSV text as downloaded from S3 and returns the rows
to upsert. The raw files are never changed (D4); cleaning happens only here.

- (a) assets `system_version` -> `system_name` + `version`
- (b) version-matrix `patch_available` -> `patch_status` + `patch_fix`
- (c) version-matrix `known_bugs` "None known" -> NULL
- (d) train_index `filename` `raw/<id>.json` -> `tickets/train/<id>.json`
"""

from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime
from typing import Any

PATCH_STATUSES = ("Yes", "No", "Partial")
NONE_KNOWN = "None known"
_PATCH_SEP = re.compile(r"\s+[—–-]\s+")  # em dash in the data; en dash and hyphen tolerated
_TRAIN_FILE = re.compile(r"^(?:raw/)?(INC-\d{5}\.json)$")


class CleaningError(ValueError):
    """A source value does not fit its cleaning rule."""


def split_system_version(value: str) -> tuple[str, str]:
    """Rule (a): `FoodTech POS v4.2.1` -> (`FoodTech POS`, `v4.2.1`).

    The version is the last space-separated token; system names may hold spaces
    and even a `v2` of their own (`StarMC Print v2 v3.0`).
    """
    system, sep, version = value.strip().rpartition(" ")
    if not sep or not system or not version:
        raise CleaningError(f"system_version without a version: {value!r}")
    return system, version


def split_patch(value: str) -> tuple[str, str | None]:
    """Rule (b): `Yes — v4.2.2 patch` -> (`Yes`, `v4.2.2 patch`); `No` -> (`No`, None)."""
    parts = _PATCH_SEP.split(value.strip(), maxsplit=1)
    status = parts[0]
    if status not in PATCH_STATUSES:
        raise CleaningError(f"patch_available with unknown status: {value!r}")
    fix = parts[1].strip() if len(parts) == 2 else None
    if status == "No" and fix:
        raise CleaningError(f"patch_available `No` with a fix: {value!r}")
    if status != "No" and not fix:
        raise CleaningError(f"patch_available `{status}` without a fix: {value!r}")
    return status, fix


def clean_known_bugs(value: str) -> str | None:
    """Rule (c): "None known" (or empty) -> None."""
    text = value.strip()
    return None if text in ("", NONE_KNOWN) else text


def fix_train_filename(value: str) -> str:
    """Rule (d): `raw/INC-00001.json` -> `tickets/train/INC-00001.json`."""
    match = _TRAIN_FILE.match(value.strip())
    if not match:
        raise CleaningError(f"train_index filename not of form raw/INC-NNNNN.json: {value!r}")
    return f"tickets/train/{match.group(1)}"


def _none_if_empty(value: str) -> str | None:
    text = value.strip()
    return text or None


def _bool(value: str) -> bool:
    if value == "True":
        return True
    if value == "False":
        return False
    raise CleaningError(f"not True/False: {value!r}")


def _rows(text: str, columns: tuple[str, ...]) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if tuple(reader.fieldnames or ()) != columns:
        raise CleaningError(f"columns {reader.fieldnames} != expected {list(columns)}")
    return list(reader)


STORE_COLUMNS = (
    "store_id",
    "store_name",
    "city",
    "neighborhood",
    "store_type",
    "region_manager",
    "support_phone",
)
ASSET_COLUMNS = (
    "asset_id",
    "store_id",
    "asset_type",
    "make",
    "model",
    "system_version",
    "serial_number",
    "install_date",
    "last_service_date",
    "warranty_expiry",
)
SLA_COLUMNS = (
    "priority",
    "category",
    "first_response_minutes",
    "resolution_target_minutes",
    "escalation_to_l2_minutes",
)
VERSION_COLUMNS = ("system", "version", "release_date", "known_bugs", "patch_available", "notes")
INDEX_COLUMNS = (
    "ticket_id",
    "store_id",
    "date_opened",
    "priority",
    "category",
    "subcategory",
    "status",
    "chaos_type",
    "escalation_flag",
    "filename",
)


def parse_stores(text: str) -> list[dict[str, Any]]:
    return [dict(row) for row in _rows(text, STORE_COLUMNS)]


def parse_assets(text: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in _rows(text, ASSET_COLUMNS):
        system_name, version = split_system_version(row["system_version"])
        out.append(
            {
                **row,
                "system_name": system_name,
                "version": version,
                "install_date": date.fromisoformat(row["install_date"]),
                "last_service_date": date.fromisoformat(row["last_service_date"]),
                "warranty_expiry": date.fromisoformat(row["warranty_expiry"]),
            }
        )
    return out


def parse_sla(text: str) -> list[dict[str, Any]]:
    return [
        {
            "priority": row["priority"],
            "category": row["category"],
            "first_response_minutes": int(row["first_response_minutes"]),
            "resolution_target_minutes": int(row["resolution_target_minutes"]),
            "escalation_to_l2_minutes": int(row["escalation_to_l2_minutes"]),
        }
        for row in _rows(text, SLA_COLUMNS)
    ]


def parse_version_matrix(text: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in _rows(text, VERSION_COLUMNS):
        status, fix = split_patch(row["patch_available"])
        out.append(
            {
                "system": row["system"],
                "version": row["version"],
                "release_date": date.fromisoformat(row["release_date"]),
                "known_bugs": clean_known_bugs(row["known_bugs"]),
                "patch_status": status,
                "patch_fix": fix,
                "notes": _none_if_empty(row["notes"]),
            }
        )
    return out


def parse_ticket_index(text: str) -> list[dict[str, Any]]:
    return [
        {
            **row,
            "date_opened": datetime.fromisoformat(row["date_opened"]),
            "chaos_type": _none_if_empty(row["chaos_type"]),
            "escalation_flag": _bool(row["escalation_flag"]),
            "filename": fix_train_filename(row["filename"]),
        }
        for row in _rows(text, INDEX_COLUMNS)
    ]
