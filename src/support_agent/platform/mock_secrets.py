"""Mock-user client secrets (D52).

There is one Keycloak confidential client per mock user (108 mock stores plus
the L1, L2, vendor, admin and dual users). Rather than 113 secrets in `.env`,
each secret is HMAC-SHA256(MOCK_CLIENT_SECRET_KEY, client_id), so the realm
renderer, the tests and the CLI derive the same value from one key.
"""

from __future__ import annotations

import hashlib
import hmac


def mock_client_secret(key: str, client_id: str) -> str:
    if not key:
        raise ValueError("MOCK_CLIENT_SECRET_KEY is empty")
    return hmac.new(key.encode(), client_id.encode(), hashlib.sha256).hexdigest()
