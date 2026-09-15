# PARADIGM INTELLIGENCE - common tasks
.DEFAULT_GOAL := help
.PHONY: help venv up down logs build migrate revision test test-unit lint fmt ingest rescore brief status shell-db clean load-real-data

VENV    := .venv
PY      := $(VENV)/bin/python
PIP     := $(VENV)/bin/pip
BACKEND := backend
TEST_DB ?= postgresql+psycopg://paradigm:paradigm@127.0.0.1:5432/paradigm_test

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

venv: ## Create the virtualenv and install the backend
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -e '$(BACKEND)[dev]'

up: ## Start the full stack
	docker compose up -d --build

down: ## Stop the stack
	docker compose down

logs: ## Follow API logs
	docker compose logs -f api

build: ## Rebuild images
	docker compose build

migrate: ## Apply migrations
	cd $(BACKEND) && ../$(PY) -m alembic upgrade head

revision: ## Autogenerate a migration (make revision m="add x")
	cd $(BACKEND) && ../$(PY) -m alembic revision --autogenerate -m "$(m)"

test: ## Run every test, including integration tests
	cd $(BACKEND) && TEST_DATABASE_URL="$(TEST_DB)" ../$(PY) -m pytest tests -q

test-unit: ## Run unit tests only (no database needed)
	cd $(BACKEND) && ../$(PY) -m pytest tests -q

lint: ## Lint
	cd $(BACKEND) && ../$(VENV)/bin/ruff check app tests

fmt: ## Auto-fix lint findings
	cd $(BACKEND) && ../$(VENV)/bin/ruff check --fix app tests

load-real-data: ## Load data/real through the analyst intake API (needs the API running)
	$(PY) scripts/load_real_data.py

ingest: ## Fetch sources, extract and score
	cd $(BACKEND) && ../$(PY) -m app.cli ingest

rescore: ## Re-apply score decay
	cd $(BACKEND) && ../$(PY) -m app.cli rescore

brief: ## Print today's brief
	cd $(BACKEND) && ../$(PY) -m app.cli brief

status: ## Show configuration and counts
	cd $(BACKEND) && ../$(PY) -m app.cli status

shell-db: ## Open a psql shell in the container
	docker compose exec postgres psql -U $${POSTGRES_USER:-paradigm} -d $${POSTGRES_DB:-paradigm}

clean: ## Remove caches
	find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
	rm -rf $(BACKEND)/.pytest_cache $(BACKEND)/.ruff_cache
