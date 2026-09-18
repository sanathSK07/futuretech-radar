# FutureTech Radar — developer entry points.
# Everything below assumes `uv` (https://docs.astral.sh/uv/) and Docker.

SHELL := /bin/bash
UV ?= uv
COMPOSE ?= docker compose -f infra/docker-compose.yml

.DEFAULT_GOAL := help

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

.PHONY: setup
setup: ## Create the virtualenv and install the locked dependencies
	$(UV) sync --extra dev
	@test -f .env || (cp .env.example .env && echo "created .env from .env.example")

.PHONY: lock
lock: ## Re-resolve dependencies and update uv.lock
	$(UV) lock

.PHONY: db-up
db-up: ## Start PostgreSQL 16 + pgvector and wait for it
	$(COMPOSE) up -d
	@printf "waiting for postgres"
	@until $(COMPOSE) exec -T db pg_isready -U radar -d radar >/dev/null 2>&1; do \
		printf "."; sleep 1; \
	done; echo " ready"

.PHONY: db-down
db-down: ## Stop the database (data is kept)
	$(COMPOSE) down

.PHONY: db-reset
db-reset: ## Destroy the database and its data, then recreate and migrate
	$(COMPOSE) down -v
	$(MAKE) db-up
	$(MAKE) migrate

.PHONY: migrate
migrate: ## Apply all migrations
	.venv/bin/alembic upgrade head

.PHONY: migration
migration: ## Autogenerate a migration: make migration m="add claim table"
	@test -n "$(m)" || (echo "usage: make migration m=\"description\"" && exit 1)
	.venv/bin/alembic revision --autogenerate -m "$(m)"

.PHONY: check-migrations
check-migrations: ## Fail if the models have drifted from the migrations
	.venv/bin/alembic check

.PHONY: test
test: ## Run the test suite
	.venv/bin/pytest

.PHONY: lint
lint: ## Lint and check formatting
	.venv/bin/ruff check .
	.venv/bin/ruff format --check .

.PHONY: format
format: ## Reformat and autofix
	.venv/bin/ruff format .
	.venv/bin/ruff check --fix .

.PHONY: typecheck
typecheck: ## Strict type checking
	.venv/bin/mypy

.PHONY: ingest
ingest: ## Ingest the last day from every active source
	.venv/bin/radar ingest --since 1d

.PHONY: sources
sources: ## Print the source registry
	.venv/bin/radar sources list

.PHONY: smoke-arxiv
smoke-arxiv: ## Fetch a few live arXiv records and print them (writes nothing)
	.venv/bin/radar smoke --source arxiv-cs-ro --count 3

.PHONY: check
check: lint typecheck test ## Everything CI runs
