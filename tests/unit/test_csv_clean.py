"""CP3.2: the 4 CSV cleaning rules, each tested on real rows from the dataset."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from support_agent.ingest import csv_clean
from support_agent.ingest.csv_clean import CleaningError

pytestmark = pytest.mark.unit

ASSET_HEADER = ",".join(csv_clean.ASSET_COLUMNS)
VERSION_HEADER = ",".join(csv_clean.VERSION_COLUMNS)
INDEX_HEADER = ",".join(csv_clean.INDEX_COLUMNS)

# Real rows copied from the dataset (data/assets.csv, version-matrix.csv, train_index.csv).
ASSET_POS = (
    "POS-0001-T1,SW-0001,POS Terminal,FoodTech POS,FoodTech POS Terminal 1,"
    "FoodTech POS v5.1.0,FT962050,2022-09-05,2023-02-28,2025-09-05"
)
ASSET_STARMC = (
    "PRN-0002-P1,SW-0002,Receipt Printer,StarMC Print v2,StarMC Print v2,"
    "StarMC Print v2 v3.0,EP717113,2022-05-28,2023-06-06,2025-05-04"
)
VM_YES = (
    "CreamTech SC-300,v3.1,2022-05-10,E04 false alarm with ambient temp > 35C,"
    "Yes — firmware 3.1.2,Retrofit required for stores above 35C"
)
VM_PARTIAL = (
    "FrostyPro 800,v1.8,2021-07-01,Overrun on mix level < 10%,Partial — manual check recommended,"
)
VM_NONE_KNOWN = "OrbitPOS,v2.1,2023-02-14,None known,No,Current stable release"
INDEX_ROW = "INC-00005,SW-0017,2025-11-22T17:59:00+05:30,P2,Kiosks,Payment Reader,Open,misdirection,False,raw/INC-00005.json"  # noqa: E501
INDEX_NORMAL = (
    "INC-00001,SW-0023,2026-04-04T10:01:00+05:30,P4,POS,Loyalty Sync,Open,,False,raw/INC-00001.json"  # noqa: E501
)


def test_rule_a_asset_system_version_is_split() -> None:
    (pos, starmc) = csv_clean.parse_assets(f"{ASSET_HEADER}\n{ASSET_POS}\n{ASSET_STARMC}\n")
    assert (pos["system_name"], pos["version"]) == ("FoodTech POS", "v5.1.0")
    assert pos["system_version"] == "FoodTech POS v5.1.0"  # the given value is kept
    assert pos["warranty_expiry"] == date(2025, 9, 5)
    # A system name holding its own "v2" keeps it; only the last token is the version.
    assert (starmc["system_name"], starmc["version"]) == ("StarMC Print v2", "v3.0")


def test_rule_b_patch_available_yes_and_partial() -> None:
    yes, partial = csv_clean.parse_version_matrix(f"{VERSION_HEADER}\n{VM_YES}\n{VM_PARTIAL}\n")
    assert (yes["patch_status"], yes["patch_fix"]) == ("Yes", "firmware 3.1.2")
    assert partial["patch_status"] == "Partial"
    assert partial["patch_fix"] == "manual check recommended"
    assert partial["notes"] is None  # empty cell
    assert yes["known_bugs"] == "E04 false alarm with ambient temp > 35C"


def test_rule_c_none_known_is_null() -> None:
    (row,) = csv_clean.parse_version_matrix(f"{VERSION_HEADER}\n{VM_NONE_KNOWN}\n")
    assert row["known_bugs"] is None
    assert (row["patch_status"], row["patch_fix"]) == ("No", None)
    assert row["notes"] == "Current stable release"


def test_rule_d_train_index_filename_is_fixed() -> None:
    tricky, normal = csv_clean.parse_ticket_index(f"{INDEX_HEADER}\n{INDEX_ROW}\n{INDEX_NORMAL}\n")
    assert tricky["filename"] == "tickets/train/INC-00005.json"
    assert tricky["chaos_type"] == "misdirection"
    assert tricky["escalation_flag"] is False
    assert tricky["date_opened"] == datetime.fromisoformat("2025-11-22T17:59:00+05:30")
    assert tricky["date_opened"].utcoffset() == timedelta(hours=5, minutes=30)
    assert normal["chaos_type"] is None


@pytest.mark.parametrize(
    ("func", "value"),
    [
        (csv_clean.split_system_version, "FoodTech"),
        (csv_clean.split_patch, "Maybe — later"),
        (csv_clean.split_patch, "No — but a fix"),
        (csv_clean.split_patch, "Yes"),
        (csv_clean.fix_train_filename, "raw/tickets/INC-1.json"),
    ],
)
def test_values_outside_a_rule_are_refused(func: object, value: str) -> None:
    with pytest.raises(CleaningError):
        func(value)  # type: ignore[operator]


def test_wrong_columns_are_refused() -> None:
    with pytest.raises(CleaningError, match="columns"):
        csv_clean.parse_stores("store_id,name\nSW-0001,x\n")


def test_bad_bool_is_refused() -> None:
    with pytest.raises(CleaningError, match="True/False"):
        csv_clean.parse_ticket_index(f"{INDEX_HEADER}\n{INDEX_NORMAL.replace('False', 'no')}\n")


def test_stores_and_sla_parse() -> None:
    header = ",".join(csv_clean.STORE_COLUMNS)
    row = "SW-0001,ServeWell - Banjara Hills,Hyderabad,Banjara Hills,corporate,Regiona Mocklead,+91-90000-00006"  # noqa: E501
    (store,) = csv_clean.parse_stores(f"{header}\n{row}\n")
    assert store["store_id"] == "SW-0001"
    (sla,) = csv_clean.parse_sla(f"{','.join(csv_clean.SLA_COLUMNS)}\nP1,POS,15,60,30\n")
    assert sla["escalation_to_l2_minutes"] == 30
