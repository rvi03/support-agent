"""SeaweedFS S3 identities, one per service (D49, review M12; S2 build step 4).

SeaweedFS matches `Action:bucket/path*` wildcards against the object path, so
`api` and `kb-index` are scoped below the bucket and labels stay in
`servewell` (the `servewell-eval` fallback of D49 is not needed).
The agent, it-data, knowledge and itsm services get no S3 key at all.
"""

from __future__ import annotations

from typing import Any

from support_agent.platform.envfile import require

BUCKETS = ("servewell", "langfuse")

# identity -> (access-key var, secret-key var, actions)
IDENTITIES: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "ingest": (
        "S3_ACCESS_KEY_INGEST",
        "S3_SECRET_KEY_INGEST",
        ("Read:servewell", "Write:servewell", "List:servewell", "Tagging:servewell"),
    ),
    "kb-index": (
        "S3_ACCESS_KEY_KB_INDEX",
        "S3_SECRET_KEY_KB_INDEX",
        ("Read:servewell/raw/kb/*", "List:servewell"),
    ),
    "api": (
        "S3_ACCESS_KEY_API",
        "S3_SECRET_KEY_API",
        ("Write:servewell/raw/tickets/incoming/*",),
    ),
    "eval": (
        "S3_ACCESS_KEY_EVAL",
        "S3_SECRET_KEY_EVAL",
        ("Read:servewell/raw/labels/*", "Read:servewell/raw/tickets/train/*", "List:servewell"),
    ),
    "langfuse": (
        "S3_ACCESS_KEY_LANGFUSE",
        "S3_SECRET_KEY_LANGFUSE",
        ("Read:langfuse", "Write:langfuse", "List:langfuse", "Tagging:langfuse"),
    ),
}


def build_s3_config(env: dict[str, str]) -> dict[str, Any]:
    identities = []
    for name, (key_var, secret_var, actions) in IDENTITIES.items():
        access, secret = require(env, key_var, secret_var)
        identities.append(
            {
                "name": name,
                "credentials": [{"accessKey": access, "secretKey": secret}],
                "actions": list(actions),
            }
        )
    return {"identities": identities}
