"""`make openapi`: write the API's OpenAPI schema (S12, handed on to S13 and S14)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from support_agent.api.app import create_app


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    out = Path(args[0] if args else "docs/openapi.json")
    schema = create_app().openapi()
    out.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")
    print(f"wrote {out} ({len(schema['paths'])} paths)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
