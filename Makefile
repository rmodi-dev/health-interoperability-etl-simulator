# =============================================================================
# Project entrypoints. Run on the VM (Linux). Secrets are generated locally.
# NOTE: recipe lines MUST start with a TAB (enforced by .editorconfig).
# =============================================================================
.DEFAULT_GOAL := help
SHELL := /bin/bash

# ---------------------------------------------------------------------------
.PHONY: help bootstrap env test test-unit test-integration lint format check db-up db-down db-logs db-shell db-clean db-migrate db-migrate-check db-history

help: ## Show available targets
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

bootstrap: env ## Create .venv from the lock (idempotent)
	@uv sync

env: ## Generate .env from template with real random secrets (once)
	@if [ ! -f .env ]; then \
	  cp .env.example .env && chmod 600 .env; \
	  sed -i "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$$(openssl rand -hex 16)|" .env; \
	  sed -i "s|^API_KEY=.*|API_KEY=$$(openssl rand -hex 32)|" .env; \
	  echo "Created .env (mode 600) with generated secrets."; \
	else \
	  echo ".env already exists - leaving it untouched."; \
	fi

test: ## Run the test suite
	@uv run pytest -q

test-unit: ## Run only unit tests (no database required)
	@uv run pytest -q -m "not integration"

test-integration: ## Run only integration tests (requires make db-up)
	@uv run pytest -q -m integration

lint: ## Lint only (no autofix)
	@uv run ruff check .

format: ## Auto-format
	@uv run ruff format .

check: lint test ## Lint + test

db-up: ## Start Postgres (detached) and wait for healthy
	@docker compose up -d postgres
	@echo "Waiting for healthcheck..."; \
	 for i in $$(seq 1 30); do \
	   st=$$(docker inspect --format '{{.State.Health.Status}}' interop-postgres 2>/dev/null || echo starting); \
	   [ "$$st" = "healthy" ] && { echo "postgres healthy"; exit 0; }; \
	   sleep 2; \
	 done; \
	 echo "postgres NOT healthy after 60s" >&2; exit 1

db-down: ## Stop services (keep data volume)
	@docker compose down

db-logs: ## Tail Postgres logs
	@docker compose logs -f postgres

db-shell: ## Open psql inside the container
	@docker compose exec -T postgres sh -c 'psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"'

db-clean: ## Stop and DELETE the data volume (destructive)
	@docker compose down -v

db-migrate: ## Apply Alembic migrations to the real interop database
	@uv run alembic upgrade head

db-migrate-check: ## Fail if models and the migrated database disagree
	@uv run alembic check

db-history: ## Show migration history
	@uv run alembic history --verbose
