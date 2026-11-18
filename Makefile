# Quality gates (S1). Later sub-tasks add: up, down, status, seed, index, ticket, ticket-local, eval.
.DEFAULT_GOAL := help
UV ?= uv
SRC := src tests

.PHONY: help check check-all lint fmt typecheck test test-unit test-integration cov fresh-check hooks

help: ## List targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-18s %s\n", $$1, $$2}'

check: lint typecheck test-unit ## Quality gate with no services: lint, mypy strict, unit tests

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
