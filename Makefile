# Quality gates (S1) and the local platform (S2).
# Source data (S3). Later sub-tasks add: index, ticket, ticket-local, eval.
.DEFAULT_GOAL := help
UV ?= uv
SRC := src tests
PLATFORM := $(UV) run python -m support_agent.platform
COMPOSE := docker compose --project-name servewell --env-file .env -f compose/compose.yaml
OPA_IMAGE := openpolicyagent/opa:1.22.4-static
# LEAN=1 skips Prometheus and Grafana (X3).
ifeq ($(LEAN),1)
export COMPOSE_PROFILES :=
endif

.PHONY: help check check-all lint fmt typecheck test test-unit test-integration cov fresh-check hooks \
	opa-test env up down nuke status mock-stores seed split index realm k4 abstention model-check walk-dry-run \
	ticket-local tricky notes-check walk-live ticket test-e2e openapi api-logs

help: ## List targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-18s %s\n", $$1, $$2}'

check: lint typecheck test-unit opa-test ## Quality gate with no services: lint, mypy strict, unit tests, opa test

check-all: check test-integration ## check plus integration tests (needs `make up` from S2 on)

lint: ## ruff lint and format check
	$(UV) run ruff check $(SRC)
	$(UV) run ruff format --check $(SRC)

fmt: ## Fix lint and format
	$(UV) run ruff check --fix $(SRC)
	$(UV) run ruff format $(SRC)

typecheck: ## mypy --strict on src/
	$(UV) run mypy

test: ## All tests
	$(UV) run pytest

test-unit: ## Unit tests
	$(UV) run pytest -m unit

test-integration: ## Integration tests
	$(UV) run pytest -m integration

cov: ## Unit tests with coverage on core modules (fail under 85%)
	$(UV) run pytest -m unit --cov --cov-report=term-missing

fresh-check: ## Clone the committed HEAD to a temp dir and run `make check` there
	@tmp=$$(mktemp -d) && trap 'rm -rf "$$tmp"' EXIT && \
	git clone --quiet "$$(git rev-parse --show-toplevel)" "$$tmp/repo" && \
	git -C "$$tmp/repo" checkout --quiet "$$(git rev-parse HEAD)" && \
	$(MAKE) -C "$$tmp/repo" check

hooks: ## Install the pre-commit hooks
	$(UV) run pre-commit install

opa-test: ## OPA policy unit tests, run in the pinned OPA image (needs Docker, no services)
	docker run --rm -v "$(CURDIR)/compose/opa/policies:/policies:ro" $(OPA_IMAGE) test /policies -v

env: ## Create .env from .env.example with fresh random secrets, if missing
	@$(PLATFORM) env

up: env ## Start the platform: checks, render, Postgres + init SQL, buckets, all services, models, status
	@$(PLATFORM) colima-check
	@$(PLATFORM) model-check
	@$(PLATFORM) render
	$(COMPOSE) up -d --build --wait postgres seaweedfs
	@$(PLATFORM) db-init
	@$(PLATFORM) buckets
	$(COMPOSE) up -d --build --wait
	@$(PLATFORM) models
	@$(PLATFORM) status

down: ## Stop every container; volumes are kept
	$(COMPOSE) --profile observability down

nuke: ## Stop everything and delete all volumes (asks first)
	@read -r -p "Delete ALL platform data volumes? Type 'yes': " ans && [ "$$ans" = yes ]
	$(COMPOSE) --profile observability down --volumes --remove-orphans

status: ## Container health, model digests, Keycloak and OPA ping
	@$(PLATFORM) status

mock-stores: ## Regenerate compose/keycloak/mock-stores.txt from DATASET_DIR
	@$(PLATFORM) mock-stores

seed: ## Upload the dataset to S3, load Postgres from S3, load the split, then mask the train tickets (S4)
	$(UV) run python -m support_agent.ingest.seed
	$(UV) run python -m support_agent.intake.seed

k4: ## K4 replay + retrieval ablation on the tune half (S6); writes eval/reports/ablation_tune.md
	$(UV) run python -m support_agent.eval.k4 $(or $(SPLIT),tune)

abstention: ## CP8.2: 20 Group A tune tickets with every runbook of their family excluded must hand off (D102); SCOPE=labelled for the report
	$(UV) run python -m support_agent.eval.agent_run abstention $(or $(ALIAS),agent) $(or $(SCOPE),family)

model-check: ## CP8.4: K1, K5, output validity on 40 tune tickets; ALIAS=agent|agent-terra
	$(UV) run python -m support_agent.eval.agent_run model-check $(or $(ALIAS),agent)

walk-dry-run: ## CP9.3: walk-runbook skill on 5 tune Group A tickets with a scripted store; writes eval/reports/walk_dry_run.md
	$(UV) run python -m support_agent.eval.walk_dry_run

ticket: ## S12: post a ticket file through the API as a mock user and follow it (FILE=..., AS=mock-store-<id>, ANSWERS=... for pauses)
	$(UV) run python -m support_agent.cli.ticket $(FILE) $(if $(filter command line environment,$(origin AS)),$(AS))

test-e2e: ## S12: API end-to-end tests (CP12.1, CP12.2) against the running API
	$(UV) run pytest -m e2e

openapi: ## S12: write the API's OpenAPI schema to docs/openapi.json
	$(UV) run python -m support_agent.api.openapi docs/openapi.json

api-logs: ## Follow the API container's log
	$(COMPOSE) logs -f api

ticket-local: ## S10: run one ticket file through intake and the graph in-process (FILE=..., ANSWERS=... for pauses)
	$(UV) run python -m support_agent.cli.ticket_local $(FILE)

tricky: ## CP10.2: tune-half tricky tickets (vague, misdirection, unknown system, contradictory, miscategorized) through the graph; writes eval/reports/tricky_tune.md
	$(UV) run python -m support_agent.eval.tricky $(ALIAS)

notes-check: ## CP10.6 + CP10.5: the 40 model-check tune tickets through the graph; K15a on every L2 note and fallback note, K14 time and cost; writes eval/reports/k15a_tune.md and k14_first_look.md
	$(UV) run python -m support_agent.eval.notes_check

walk-live: ## S11: three live Resolver walks (printer to fixed, steps already tried, version not covered); writes eval/reports/walk_live.md
	$(UV) run python -m support_agent.eval.walk_live

realm: ## Re-import the Keycloak realm after a realm.py change (deletes and re-imports it)
	@$(PLATFORM) realm-reload

index: ## Build and publish a sanitized KB revision from S3 (S6); ARGS=--force rebuilds an unchanged one
	$(UV) run python -m support_agent.kb.index $(ARGS)

split: ## Write eval/split.json from the uploaded labels (once, before any tuning; commit it)
	$(UV) run python -m support_agent.ingest.seed split
