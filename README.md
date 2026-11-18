# support-agent

A working POC of an L1 IT support agent for ServeWell's pilot stores: it reads each incoming ticket, checks it against the real data, routes it, guides the store through POS and Printer fixes, and logs every step. Everything runs on localhost with open-source parts.

## Prerequisites

- macOS with [uv](https://docs.astral.sh/uv/) (Python 3.12 is installed by uv).
- git.
- From S2 on: Docker Engine on Colima, and Ollama running natively.

## Quick start

```sh
cp .env.example .env      # fill in real values; never commit .env
uv sync
make hooks                # install the pre-commit hooks
make check                # lint, mypy strict, unit tests
```

Coming with later sub-tasks: `make up`, `make seed`, `make index`, `make ticket FILE=…`, `make eval`.

## Make targets

| Target | Does |
|---|---|
| `make check` | ruff lint and format check, mypy `--strict` on `src/`, unit tests; needs no services |
| `make check-all` | `check` plus integration tests (from S2 on, needs `make up`) |
| `make lint` / `make fmt` | Check / fix lint and format |
| `make typecheck` | mypy `--strict` |
| `make test` / `test-unit` / `test-integration` | Run tests by marker |
| `make cov` | Unit tests with coverage on the core modules (fails under 85%) |
| `make fresh-check` | Clone the committed HEAD to a temp dir and run `make check` there |
| `make hooks` | Install the pre-commit hooks |

## Layout

```
src/support_agent/
  common/      config (one settings class per service), logging, PII log filter
  ingest/      source data loading            (S3)
  intake/      schema, masking, moderation    (S4)
  mcp/         base, it_data, knowledge, itsm (S5-S7, S9)
  kb/          index pipeline, runbook steps  (S6, S9)
  agent/       LangGraph graph and nodes      (S8-S11)
  api/, cli/   FastAPI service and CLI        (S12)
  eval/        runner, metrics, safety checker (S14)
tests/unit · tests/integration · tests/e2e
```

Each service loads only its own settings: `python -m support_agent.common.config <service>` checks them and exits with code 2, naming every missing or invalid setting.

## Limits

- POC on localhost only; no TLS between services.
- Logs pass a last-line PII filter (phones, emails, `L1 Agent - <name>`, and exact names and phones registered per ticket); masking before logging is done at intake (S4).
