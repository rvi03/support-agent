"""CP3.1: every dataset file is in SeaweedFS at raw/<source path> with a matching SHA-256.

Needs `make up` and `make seed`. Each object is downloaded and its bytes hashed;
the stored `sha256` metadata and the manifest are checked too.
"""

from __future__ import annotations

from pathlib import Path

import boto3
import psycopg
import pytest
from botocore.config import Config
from mypy_boto3_s3 import S3Client

from support_agent.ingest import seed
from tests.integration.platform_env import ROOT, load_env, superuser_url

pytestmark = pytest.mark.integration

DATASET = (ROOT / load_env().get("DATASET_DIR", "../../references/assignment/dataset")).resolve()


def _s3() -> S3Client:
    env = load_env()
    client: S3Client = boto3.client(
        "s3",
        endpoint_url="http://localhost:8333",
        aws_access_key_id=env["S3_ACCESS_KEY_INGEST"],
        aws_secret_access_key=env["S3_SECRET_KEY_INGEST"],
        region_name="us-east-1",
        config=Config(s3={"addressing_style": "path"}),
    )
    return client


def _local() -> dict[str, Path]:
    return {f"raw/{rel}": path for rel, path in seed.dataset_files(DATASET)}


def _listed(s3: S3Client) -> set[str]:
    keys: set[str] = set()
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket="servewell", Prefix="raw/"):
        keys |= {obj["Key"] for obj in page.get("Contents", [])}
    return keys


def test_every_file_is_in_s3_with_its_bytes() -> None:
    s3 = _s3()
    local = _local()
    assert len(local) == 311  # 312 files in the dataset minus its .gitignore
    listed = {k for k in _listed(s3) if not k.startswith("raw/tickets/incoming/")}
    assert listed == set(local)
    for key, path in local.items():
        obj = s3.get_object(Bucket="servewell", Key=key)
        want = seed.sha256_hex(path.read_bytes())
        assert seed.sha256_hex(obj["Body"].read()) == want, key
        assert obj["Metadata"].get("sha256") == want, key


def test_manifest_matches_the_local_files() -> None:
    with psycopg.connect(superuser_url(load_env())) as conn:
        rows = conn.execute("SELECT path, sha256, bytes FROM data.raw_files").fetchall()
    manifest = {path: (digest, size) for path, digest, size in rows}
    local = _local()
    assert set(manifest) == set(local)
    for key, path in local.items():
        data = path.read_bytes()
        assert manifest[key] == (seed.sha256_hex(data), len(data)), key
