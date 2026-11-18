# support-agent

A working POC of an L1 IT support agent for ServeWell's pilot stores: it reads each incoming ticket, checks it against the real data, routes it, guides the store through POS and Printer fixes, and logs every step. Everything runs on localhost with open-source parts.

## Prerequisites

- macOS (Apple silicon, 18 GB RAM or more) with [uv](https://docs.astral.sh/uv/) (Python 3.12 is installed by uv) and git.
- Docker Engine on Colima, plus the compose and buildx plugins (no Docker Desktop):
  `brew install colima docker docker-compose docker-buildx`, then add
  `"cliPluginsExtraDirs": ["/opt/homebrew/lib/docker/cli-plugins"]` to `~/.docker/config.json`.
- Colima started with the memory cap `make up` checks (A30):
  `colima start --cpu 6 --memory 8 --disk 100 --vm-type vz --mount-type virtiofs`.
- An OpenAI API key: put it in `.env` as `OPENAI_API_KEY` (models run on the OpenAI API, D64).
  Ollama is needed only if you point an alias back at a local model.

## Quick start

```sh
uv sync
make hooks                # install the pre-commit hooks
make check                # lint, mypy strict, unit tests, opa test
make up                   # creates .env with random secrets if missing, starts everything
make check-all            # check plus integration tests against the running platform
```

Coming with later sub-tasks: `make seed`, `make index`, `make ticket FILE=…`, `make eval`.

## Local platform (`make up`)

`make up` checks Colima's memory cap and the LiteLLM model slots, renders the files that need secrets into `.run/` (git-ignored), starts Postgres and SeaweedFS, applies `db/sql/` (idempotent), creates the buckets, starts the rest with `--wait` (every container has a healthcheck), lists the model per alias (an Ollama alias is pulled and pinned in `compose/ollama-models.lock`) and prints `make status`.

| Service | Local URL | Purpose |
|---|---|---|
| Postgres 17 + pgvector + pg_textsearch | `localhost:5432` | Databases `servewell`, `langfuse`, `keycloak`; one role per service |
| SeaweedFS (S3 API) | `localhost:8333` | Buckets `servewell` and `langfuse`; one S3 identity per service |
| Keycloak | `localhost:8080` | Realm `servewell`: roles, `ui` (PKCE), service clients, mock-user clients |
| OPA | `localhost:8181` | Policies in `compose/opa/policies/` (default deny) |
| LiteLLM | `localhost:4000` | Aliases `agent`, `moderation`, `judge`, `simulator` (gpt-6-luna) and `embed` (text-embedding-3-small, 768 dims) → OpenAI API |
| Langfuse (web, worker) + ClickHouse + Valkey | `localhost:3000` | LLM traces; project and keys created headless |
| it-data MCP server | `localhost:8101/mcp` | 7 read-only IT data tools (Streamable HTTP; bearer token with `it-data:read`), `/health` |
| Prometheus, Grafana | `localhost:9090`, `localhost:3001` | Metrics (profile `observability`; `make up LEAN=1` skips them) |

- All ports bind to 127.0.0.1. Each container gets only its own variables from `.env` (D46).
- Keycloak imports the realm on first start only. After changing the realm or its secrets, reset with `make nuke && make up`.
- `audit.events` is append-only: INSERT is the only grant, and a trigger refuses UPDATE, DELETE and TRUNCATE for every role.
- A model swap is an edit of `compose/litellm/config.yaml`. Only masked text is sent to the models (S4 safety net). `ALLOW_EXTERNAL_MODELS=false` forces local Ollama aliases only.
- `scripts/mem_probe.sh` records memory and swap (CP2.4) into `docs/measurements.md`.

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
| `make opa-test` | OPA policy unit tests in the pinned OPA image (part of `check`) |
| `make env` | Create `.env` from `.env.example` with fresh random secrets, if missing |
| `make up` / `make up LEAN=1` | Start the platform (see above); `LEAN=1` skips Prometheus and Grafana |
| `make down` | Stop every container; volumes are kept |
| `make nuke` | Stop everything and delete all volumes (asks first) |
| `make status` | Container health, model digests, Keycloak and OPA ping |
| `make mock-stores DATASET_DIR=…` | Regenerate the mock-store client list from the dataset |

## Layout

```
src/support_agent/
  common/      config (one settings class per service), logging, PII log filter, audit
  platform/    make up / status tooling: .env, realm, S3 identities, DB init, model lock
  ingest/      source data loading            (S3)
  intake/      schema, masking, moderation    (S4)
  mcp/         base (auth, OPA, audit, typed errors), it_data, knowledge, itsm (S5-S7, S9)
  agent/tools  MCP client: tokens, retry, mask + safety-net scan of every result (S5)
  kb/          index pipeline, runbook steps  (S6, S9)
  agent/       LangGraph graph and nodes      (S8-S11)
  api/, cli/   FastAPI service and CLI        (S12)
  eval/        runner, metrics, safety checker (S14)
tests/unit · tests/integration · tests/e2e
compose/      compose.yaml, postgres/, keycloak/, opa/, litellm/, prometheus/, grafana/
db/sql/       NNN_<name>.sql, applied in order by make up, idempotent
```

Each service loads only its own settings: `python -m support_agent.common.config <service>` checks them and exits with code 2, naming every missing or invalid setting.

## MCP servers

Every tool call runs one fixed order in `mcp/base`: verify the JWT (Keycloak JWKS, issuer, audience = server name, expiry) → the tool's scope → OPA (P10 → P7; 1 s timeout, fail closed) → validate the arguments (Pydantic) → the tool → validate the result → one `audit.events` row (client, tool, argument hash, ticket id from the request `_meta`, result, latency). A refused token (401/403) is audited too. Typed error replies: `denied`, `invalid`, `error`; domain outcomes (`not_found`, `unknown_system`, `fallback_general`) are normal results. The servers run on the MCP Python SDK 2.x (`MCPServer`); the agent uses the SDK's own client, because langchain-mcp-adapters still pins `mcp<2`.

## Limits

- POC on localhost only; no TLS between services.
- Logs pass a last-line PII filter (phones, emails, `L1 Agent - <name>`, and exact names and phones registered per ticket); masking before logging is done at intake (S4).
