#!/usr/bin/env bash
# CP2.4: record memory and swap with `make up` running, one LiteLLM call per
# alias, and agent + simulator loaded together (A30). Appends the result to
# docs/measurements.md and exits non-zero if macOS swap-ins rose.
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
