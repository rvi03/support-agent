# support-agent

support-agent is a proof of concept (POC) of a level-1 (L1) IT support agent
for ServeWell's pilot stores. It runs entirely on localhost with open-source
components.

## Overview

For each incoming ticket, the agent does the following:

1.  Reads the ticket and checks it against the real IT data.
2.  Routes the ticket to the right queue.
3.  Guides the store through point-of-sale (POS) and printer fixes.
4.  Logs every step to an append-only audit table.

The POC walks two runbooks: `printer-offline` and `pos-screen-frozen`.

```
Store user ──► Demo UI ──► API (FastAPI) ──► Agent (LangGraph)
                              │                  │
                              ▼                  ▼
                       Keycloak + OPA     MCP servers: it-data, knowledge, itsm-actions
                                                 │
                                                 ▼
                                    LiteLLM ──► OpenAI API (masked text only)
```

This README covers the following topics:

*   [Before you begin](#before-you-begin)
*   [Get started](#get-started)
*   [Use the agent](#use-the-agent)
*   [Run the evaluation](#run-the-evaluation)
*   [Architecture](#architecture)
*   [Project layout](#project-layout)
*   [Make targets](#make-targets)
*   [Known limitations](#known-limitations)
*   [Documentation](#documentation)

## Before you begin

You need the following:

*   A Mac with Apple silicon and at least 18 GB of RAM.
*   [uv](https://docs.astral.sh/uv/) and git. uv installs Python 3.12.
*   Docker Engine on Colima, with the compose and buildx plugins. Docker
    Desktop isn't used.
*   An OpenAI API key. The models run on the OpenAI API. You need
    [Ollama](https://ollama.com/) only if you point a model alias back to a
    local model.

To set up Docker on Colima, do the following:

1.  Install the packages:

    ```sh
    brew install colima docker docker-compose docker-buildx
    ```

2.  Add the plugin directory to `~/.docker/config.json`:

    ```json
    "cliPluginsExtraDirs": ["/opt/homebrew/lib/docker/cli-plugins"]
    ```

3.  Start Colima with the memory cap that `make up` checks:

    ```sh
    colima start --cpu 6 --memory 8 --disk 100 --vm-type vz --mount-type virtiofs
    ```

## Get started

1.  Install the Python dependencies and the pre-commit hooks:

    ```sh
    uv sync
    make hooks
    ```

2.  Run the quality checks. This step needs no running services.

    ```sh
    make check
    ```

    `make check` runs the linter, mypy in strict mode, the unit tests, and
    the OPA policy tests.

3.  Start the platform:

    ```sh
    make up
    ```

    If `.env` is missing, `make up` creates it with random secrets. Add your
    key to `.env` as `OPENAI_API_KEY`.

4.  Load the data and build the knowledge base (KB):

    ```sh
    make seed     # Uploads the dataset to S3 and Postgres, loads the split, masks the train tickets.
    make index    # Builds and publishes the sanitized KB revision.
    ```

5.  Run the integration tests against the running platform:

    ```sh
    make check-all
    ```

## Use the agent

### Send a ticket

To post a ticket file through the API and follow it, run the following
command:

```sh
make ticket FILE=tests/fixtures/new_printer_ticket.json
```

To send it as a specific store, add `AS=mock-store-<id>`. To run a ticket
in-process, without the API, use `make ticket-local FILE=…`.

### Open the Demo UI

The Demo UI is a single-page app in `ui/`, built with Vite, React, and
TypeScript. Node runs in Docker.

1.  Start the UI:

    ```sh
    make ui
    ```

2.  Open http://localhost:5173.
3.  To list the demo logins, run `make ui-users`.

What each user sees:

| User | View |
|---|---|
| Store user | The ticket chat and the new-ticket form. |
| `l2_engineer`, `vendor_approver` | The approval queue. |

The UI talks only to the API, logs users in with Keycloak PKCE (tokens stay
in memory), and polls every 2 seconds.

**Note:** One approval promotes an action to autonomous
(`ACTION_AUTONOMY_RUNS=1`). Before a demo, run
`make demote ACTION=restart_print_spooler` so that the approval card shows
again.

## Run the evaluation

Tuning uses only the tune half of the dataset. Held-out numbers are reported
once, on frozen settings.

1.  Prepare the dataset and fault cards:

    ```sh
    make eval-dataset   # Pushes 256 masked items to the Langfuse dataset servewell-256.
    make fault-cards    # Run once. The cards are committed and never regenerated in a run.
    ```

2.  Switch to eval mode:

    ```sh
    make eval-mode
    ```

    Eval mode sets `EVAL_MODE`, the replay clock, and the fault cards, and
    sets every action back to supervised.

3.  Run and score the tune half:

    ```sh
    make eval-run SPLIT=tune NAME=tune-1   # Agent phase, through the API as mock users.
    make eval-score RUN=tune-1             # KPIs: DeepEval code metrics and a GEval judge.
    make safety-check RUN=tune-1           # Independent checker: K10, K11, K12, and secrets.
    ```

    The report is written to `eval/reports/tune-1.md`.

4.  Run the attack cases and the OPA, resume, and abstention suites:

    ```sh
    make adversarial && make eval-suites
    ```

5.  Create the hand-score forms, then fill the human column in
    `eval/hand/calibration.csv`:

    ```sh
    make hand-forms RUN=tune-1
    ```

6.  Freeze the settings. The command refuses to run below 80% judge
    agreement.

    ```sh
    make freeze
    ```

7.  Run and score the held-out half:

    ```sh
    make eval-run SPLIT=heldout NAME=heldout-1 && make eval-score RUN=heldout-1 TUNE=tune-1
    ```

8.  Switch back to live outcomes:

    ```sh
    make live-mode
    ```

Keep the following in mind:

*   The store simulator answers only from the fault card's observations. Code
    decides whether a ticket is fixed, by exact step and action IDs.
*   K8 is scored only on `printer-offline` and `pos-screen-frozen` tickets.
    The rest are reported as out of scope.
*   The safety checker in `src/support_agent/eval/safety_checker/` imports no
    agent code and uses its own fixture, `eval/safety_fixtures.yaml`.
*   Run one load at a time. The API container (2 GB) ran out of memory with
    eight tickets in flight.

## Architecture

### Services

`make up` starts the following services. All ports bind to `127.0.0.1`.

| Service | Local URL | Purpose |
|---|---|---|
| Postgres 17 with pgvector and pg_textsearch | `localhost:5432` | Databases `servewell`, `langfuse`, and `keycloak`, with one role per service. |
| SeaweedFS (S3 API) | `localhost:8333` | Buckets `servewell` and `langfuse`, with one S3 identity per service. |
| Keycloak | `localhost:8080` | Realm `servewell`: roles, the `ui` client (PKCE), service clients, and mock-user clients. |
| OPA | `localhost:8181` | Policies in `compose/opa/policies/`. The default is deny. |
| LiteLLM | `localhost:4000` | Aliases `agent`, `moderation`, `judge`, and `simulator` (gpt-6-luna), and `embed` (text-embedding-3-small, 768 dimensions), routed to the OpenAI API. |
| Langfuse (web and worker), ClickHouse, Valkey | `localhost:3000` | LLM traces. The project and keys are created headless. |
| it-data MCP server | `localhost:8101/mcp` | Seven read-only IT data tools over Streamable HTTP. Needs a bearer token with `it-data:read`. Also serves `/health`. |
| knowledge MCP server | `localhost:8102/mcp` | KB search (hybrid BM25 and vector) and whole-document reads. Retrieval only. |
| itsm-actions MCP server | `localhost:8103/mcp` | Ticket writes, store messages, approvals, and simulated fixes from the action registry only (OPA policy P8). |
| API (FastAPI) | `localhost:8000` | Six endpoints: create, list, get, reply, and approve tickets, and `/health`. The OpenAPI schema is in `docs/openapi.json`. |
| Prometheus, Grafana | `localhost:9090`, `localhost:3001` | Metrics, in the `observability` profile. `make up LEAN=1` skips them. |
| Demo UI | `localhost:5173` | Started separately with `make ui`. |

### What `make up` does

1.  Checks the Colima memory cap and the LiteLLM model slots.
2.  Renders the files that need secrets into `.run/`, which git ignores.
3.  Starts Postgres and SeaweedFS, applies `db/sql/` (idempotent), and creates
    the buckets.
4.  Starts the other services with `--wait`. Every container has a
    healthcheck.
5.  Lists the model for each alias. An Ollama alias is pulled and pinned in
    `compose/ollama-models.lock`.
6.  Prints `make status`.

### Security model

*   **Network:** Every service sits on an internal Docker network with no
    route out. Only LiteLLM reaches the OpenAI API, and one gateway publishes
    the local ports.
*   **Secrets:** Each container gets only its own variables from `.env`.
*   **Model input:** Only masked text is sent to the models. To allow only
    local Ollama aliases, set `ALLOW_EXTERNAL_MODELS=false`.
*   **Audit:** `audit.events` is append-only. `INSERT` is the only grant, and
    a trigger refuses `UPDATE`, `DELETE`, and `TRUNCATE` for every role.
*   **Logs:** Logs pass a last-line PII filter for phone numbers, emails,
    `L1 Agent - <name>`, and the exact names and phone numbers registered per
    ticket. Masking before logging happens at intake.

### MCP tool calls

Every tool call runs in this fixed order, in `mcp/base`:

```
verify JWT ──► check tool scope ──► OPA (P10, then P7) ──► validate arguments
   ──► run tool ──► validate result ──► write one audit.events row
```

*   **JWT:** Keycloak JWKS, issuer, audience (the server name), and expiry.
*   **OPA:** 1-second timeout. A timeout fails closed.
*   **Arguments and results:** Validated with Pydantic.
*   **Audit row:** Client, tool, argument hash, ticket ID from the request
    `_meta`, result, and latency. A refused token (401 or 403) is audited too.
*   **Errors:** Typed error replies are `denied`, `invalid`, and `error`.
    Domain outcomes such as `not_found`, `unknown_system`, and
    `fallback_general` are normal results.

The servers run on the MCP Python SDK 2.x (`MCPServer`). The agent uses the
SDK's own client because langchain-mcp-adapters still pins `mcp<2`.

### API requests

Every request runs in this fixed order:

```
verify JWT ──► body size and schema ──► rate limit ──► OPA ──► handler ──► audit event
```

| Step | Behavior |
|---|---|
| JWT | Keycloak JWKS, issuer, `aud=api`, and expiry. |
| Body size | Up to 64 kB. Larger bodies return 413. |
| Schema | Invalid bodies return 422. `ticket_id`, `date_opened`, `store_id`, and contact fields are never accepted. |
| Rate limit | Per user and per store. Returns 429. |
| OPA | P1 own store, P2 queues, P3 approve, P4 vendor and L2 tasks, and P6 admin, all through P10. |
| Audit | Every denial is audited. |

*   A ticket that the caller may not read returns 404, the same as an unknown
    ticket.
*   `POST /tickets` saves the raw JSON to `raw/tickets/incoming/` and returns
    202. Intake and the agent graph run in the background.
*   Reply and approve requests name the open `pending_id`. The API takes the
    ticket lock and clears the pending item before it returns 202, so a busy
    ticket or a stale ID returns 409.
*   Only `eval-runner` can replay dataset tickets (`source_ticket_id`).
*   Metrics are internal, on port 9000.

## Project layout

```
src/support_agent/
  common/       Config (one settings class per service), logging, PII log filter, audit.
  platform/     make up and make status tooling: .env, realm, S3 identities, DB init, model lock.
  ingest/       Source data loading.
  intake/       Schema, masking, moderation.
  mcp/          Base (auth, OPA, audit, typed errors), it_data, knowledge, itsm.
  agent/tools/  MCP client: tokens, retry, masking, and a safety-net scan of every result.
  kb/           KB index pipeline: clean, mask, chunk, embed, publish.
  agent/        LangGraph graph, nodes, prompts, skills, bindings.yaml (approved walk steps).
  api/, cli/    FastAPI service and CLI.
  eval/         Dataset, runner, simulator, metrics, judge, safety checker, adversarial cases, freeze.
ui/             Demo UI.
eval/           Split, fault cards, rubrics, adversarial cases, safety fixtures, hand forms, reports, runs (masked run evidence).
tests/          unit/, integration/, e2e/.
compose/        compose.yaml and the config for postgres, keycloak, opa, litellm, prometheus, grafana.
db/sql/         NNN_<name>.sql files, applied in order by make up. Idempotent.
scripts/        Helper scripts, such as mem_probe.sh.
docs/           OpenAPI schema and measurements.
```

Each service loads only its own settings. To check a service's settings, run
the following command:

```sh
python -m support_agent.common.config <service>
```

The command exits with code 2 and names every missing or invalid setting.

## Make targets

Run `make help` to list all targets. The main ones are the following:

| Group | Targets |
|---|---|
| Quality | `check` (no services), `check-all` (adds integration tests), `lint`, `fmt`, `typecheck`, `test`, `test-unit`, `test-integration`, `test-e2e`, `cov`, `fresh-check`, `hooks`, `opa-test` |
| Platform | `env`, `up` (`LEAN=1` skips Prometheus and Grafana), `down`, `nuke` (deletes volumes; asks first), `status`, `realm`, `api-logs`, `mock-stores DATASET_DIR=…` |
| Data and KB | `seed`, `split` (run once, before tuning), `index` (`ARGS=--force` rebuilds) |
| Tickets | `ticket FILE=… [AS=mock-store-<id>]`, `ticket-local FILE=…`, `demote ACTION=…` (back to supervised; audited), `openapi` |
| Demo UI | `ui`, `ui-users`, `ui-install`, `ui-types`, `ui-check`, `ui-e2e` |
| Tune-half checks | `k4`, `abstention`, `model-check`, `walk-dry-run`, `tricky`, `notes-check`, `walk-live` |
| Evaluation | `eval-dataset`, `fault-cards`, `eval-mode`, `live-mode`, `eval-run`, `eval-score`, `safety-check`, `adversarial`, `rule-breaks`, `eval-suites`, `hand-forms`, `hand-import`, `freeze` |

### Common maintenance tasks

*   **Change a model:** Edit `compose/litellm/config.yaml`.
*   **Change the Keycloak realm:** Keycloak imports the realm only on first
    start. After you change `platform/realm.py` or its secrets, run
    `make realm`. The command deletes and re-imports the realm.
*   **Record memory use:** Run `scripts/mem_probe.sh`. It writes memory and
    swap figures to `docs/measurements.md`.

## Known limitations

*   A background run is lost if the API restarts mid-run. The checkpointer
    keeps the state, and the SLA timer hands the ticket off. A durable queue
    isn't implemented yet.
*   The API process hosts intake and the agent, so its container also holds
    their credentials.
*   The POC runs on localhost only. Traffic between services doesn't use TLS.

## Documentation

*   [`docs/openapi.json`](docs/openapi.json): The API's OpenAPI schema.
*   [`docs/measurements.md`](docs/measurements.md): Memory and swap
    measurements.
*   [`eval/fault_cards/README.md`](eval/fault_cards/README.md): The fault card
    format.
