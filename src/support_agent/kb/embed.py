"""Embeddings through LiteLLM (index step 8 and the knowledge server's query vector).

The alias (`embed`) maps to text-embedding-3-small at 768 dimensions (D64); no task
prefixes. Text is cut at the model's 8,191-token input limit, which a 480-token
chunk never reaches.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import httpx

BATCH = 64
MAX_CHARS = 8_191 * 3  # a safe character cut below the model's token limit


class EmbedError(RuntimeError):
    pass


def _check(vectors: list[list[float]], dim: int, n: int) -> list[list[float]]:
    if len(vectors) != n:
        raise EmbedError(f"asked for {n} embeddings, got {len(vectors)}")
    bad = {len(v) for v in vectors if len(v) != dim}
    if bad:
        raise EmbedError(f"embedding width {sorted(bad)} != EMBED_DIM {dim}")
    return vectors


def _body(model: str, texts: Sequence[str]) -> dict[str, object]:
    return {"model": model, "input": [t[:MAX_CHARS] for t in texts]}


def _vectors(data: dict[str, object]) -> list[list[float]]:
    raw = data["data"]
    if not isinstance(raw, list):
        raise EmbedError("embeddings response has no data list")
    items: list[dict[str, Any]] = sorted(raw, key=lambda d: int(d["index"]))
    return [[float(x) for x in d["embedding"]] for d in items]


def embed(
    texts: Sequence[str], *, base_url: str, key: str, model: str, dim: int, timeout: float = 60.0
) -> list[list[float]]:
    out: list[list[float]] = []
    with httpx.Client(timeout=timeout) as http:
        for i in range(0, len(texts), BATCH):
            batch = texts[i : i + BATCH]
            r = http.post(
                f"{base_url.rstrip('/')}/v1/embeddings",
                json=_body(model, batch),
                headers={"Authorization": f"Bearer {key}"},
            )
            if r.status_code != 200:
                raise EmbedError(f"embeddings HTTP {r.status_code}")
            out.extend(_check(_vectors(r.json()), dim, len(batch)))
    return out


async def aembed_one(
    http: httpx.AsyncClient, text: str, *, base_url: str, key: str, model: str, dim: int
) -> list[float]:
    r = await http.post(
        f"{base_url.rstrip('/')}/v1/embeddings",
        json=_body(model, [text]),
        headers={"Authorization": f"Bearer {key}"},
    )
    if r.status_code != 200:
        raise EmbedError(f"embeddings HTTP {r.status_code}")
    return _check(_vectors(r.json()), dim, 1)[0]


def vector_literal(vector: Sequence[float]) -> str:
    return "[" + ",".join(f"{x:.7g}" for x in vector) + "]"
