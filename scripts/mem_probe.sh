#!/usr/bin/env bash
# CP2.4: record memory and swap with `make up` running and one LiteLLM call per
# alias with its job check, tokens and cost (A30, D64). Appends the result to
# docs/measurements.md and exits non-zero if a check fails or swap-ins rose.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p docs
out=$(mktemp)
trap 'rm -f "$out"' EXIT
status=0
uv run python -m support_agent.platform.probe >"$out" || status=$?
cat "$out"
{ echo; cat "$out"; } >>docs/measurements.md
exit "$status"
