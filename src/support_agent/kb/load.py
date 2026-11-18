"""Index step 1: load the KB from S3 (`raw/kb/`), the only step with raw-bucket access.

`kb-index` may read `servewell/raw/kb/*` and list the bucket, nothing else (D61).
`doc_id` is the path below `kb/` (`runbooks/printer-offline.md`), the labels' form.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

import boto3
from botocore.config import Config

from support_agent.common.config import KbIndexSettings

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

BUCKET = "servewell"
PREFIX = "raw/kb/"


@dataclass(frozen=True)
class SourceFile:
    doc_id: str
    sha256: str
    data: bytes


def s3_client(settings: KbIndexSettings) -> S3Client:
    client: S3Client = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key_kb_index.get_secret_value(),
        aws_secret_access_key=settings.s3_secret_key_kb_index.get_secret_value(),
        region_name="us-east-1",
        config=Config(s3={"addressing_style": "path"}, retries={"max_attempts": 3}),
    )
    return client


def load(s3: S3Client) -> list[SourceFile]:
    """Every object under `raw/kb/` with its SHA-256, sorted by doc_id."""
    files: list[SourceFile] = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=PREFIX):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            data = s3.get_object(Bucket=BUCKET, Key=key)["Body"].read()
            files.append(SourceFile(key[len(PREFIX) :], hashlib.sha256(data).hexdigest(), data))
    if not files:
        raise RuntimeError(f"no objects under s3://{BUCKET}/{PREFIX}; run `make seed` first")
    return sorted(files, key=lambda f: f.doc_id)
