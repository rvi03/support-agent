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
	opa-test env up down nuke status mock-stores seed split

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
	$(COMPOSE) up -d --wait
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

split: ## Write eval/split.json from the uploaded labels (once, before any tuning; commit it)
	$(UV) run python -m support_agent.ingest.seed split
