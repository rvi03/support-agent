"""Typed error replies shared by every MCP server (S5).

A refused or failed call comes back as an MCP tool error whose text is one JSON
object `{"error": <code>, "reason": <short text>}`. Domain outcomes such as an
asset that does not exist are not errors: each tool's result model carries
them in its own `status` field.
"""

from __future__ import annotations

import json
from enum import StrEnum


class ErrorCode(StrEnum):
    DENIED = "denied"  # no token, wrong scope or audience, OPA said no or is down
    INVALID = "invalid"  # arguments do not fit the tool's input model
    NOT_FOUND = "not_found"  # reserved for tools whose whole reply is one record
    CONFLICT = "conflict"  # an idempotency key or record reused with a different payload
    ERROR = "error"  # anything else: the server failed, the agent hands off


class ToolFailure(Exception):  # noqa: N818 - a reply kind, not a crash
    def __init__(self, code: ErrorCode, reason: str) -> None:
        super().__init__(f"{code}: {reason}")
        self.code, self.reason = code, reason

    def as_json(self) -> str:
        return json.dumps({"error": str(self.code), "reason": self.reason})

    @classmethod
    def from_json(cls, text: str) -> ToolFailure:
        """Parse a server's error text (the SDK puts `Error executing tool <name>: ` in
        front); anything unparseable is an `error`."""
        try:
            data = json.loads(text[text.index("{") :])
            return cls(ErrorCode(data["error"]), str(data.get("reason", "")))
        except (ValueError, KeyError, TypeError):
            return cls(ErrorCode.ERROR, "unparseable error reply")
