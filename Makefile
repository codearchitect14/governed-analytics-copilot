.DEFAULT_GOAL := help
SHELL := /bin/bash

# Load .env for every recipe (database URLs and dbt credentials). Values are exported to commands.
-include .env
export

COMPOSE := docker compose
UV := uv
DBT_DIR := warehouse/dbt_project
WAREHOUSE_RUN := $(UV) run --package governed-analytics-warehouse
# MetricFlow prints Unicode progress output, so the console must use UTF-8
PYTHON_UTF8 := PYTHONIOENCODING=utf-8

.PHONY: help up down logs ps data data-sample dbt seed test lint eval backup restore \
	semantic-validate golden index retrieval

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-16s %s\n", $$1, $$2}'

up: ## Start the full stack (postgres, api, web, dagster) and wait for health
	$(COMPOSE) up -d --build --wait

down: ## Stop the stack and keep data volumes
	$(COMPOSE) down

logs: ## Follow logs for all services
	$(COMPOSE) logs -f

ps: ## Show service status
	$(COMPOSE) ps

data: ## Download Olist (Kaggle), load raw tables, build dbt models
	$(UV) run --package governed-analytics-scripts python scripts/download_data.py
	$(UV) run --package governed-analytics-scripts python scripts/load_olist.py
	$(MAKE) dbt

data-sample: ## Load only the committed 5,000 order sample (CI and quick start)
	$(UV) run --package governed-analytics-scripts python scripts/load_olist.py --sample
	$(MAKE) dbt

dbt: ## Build dbt models and run tests
	cd $(DBT_DIR) && DBT_PROFILES_DIR=$$PWD $(WAREHOUSE_RUN) dbt deps
	cd $(DBT_DIR) && DBT_PROFILES_DIR=$$PWD $(WAREHOUSE_RUN) dbt build

semantic-validate: ## Validate MetricFlow semantic models and metrics against the warehouse
	cd $(DBT_DIR) && DBT_PROFILES_DIR=$$PWD $(WAREHOUSE_RUN) dbt parse
	cd $(DBT_DIR) && DBT_PROFILES_DIR=$$PWD $(PYTHON_UTF8) $(WAREHOUSE_RUN) mf validate-configs

golden: ## Check that all 30 plan fixtures compile and match their gold SQL
	$(PYTHON_UTF8) $(UV) run --package governed-analytics-warehouse python warehouse/semantic/golden.py

index: ## Rebuild the catalog embedding index in pgvector (app schema)
	$(UV) run --package governed-analytics-backend python -m app.semantic.index_catalog --database-url "$$APP_DATABASE_URL_HOST"

retrieval: ## Measure top 3 retrieval recall on paraphrased metric and dimension mentions
	$(UV) run --package governed-analytics-backend python -m app.semantic.evaluate_retrieval --database-url "$$APP_DATABASE_URL_HOST"

backup: ## Dump the database to backups/ (custom format, with checksum)
	bash infra/scripts/backup.sh

restore: ## Restore a dump: make restore DUMP=backups/<file>.dump CONFIRM=yes
	bash infra/scripts/restore.sh $(DUMP) $(if $(filter yes,$(CONFIRM)),--confirm,)

migrate: ## Apply application database migrations (app schema)
	cd backend && APP_DATABASE_URL="$$APP_DATABASE_URL_HOST" $(UV) run --package governed-analytics-backend alembic upgrade head

seed-users: ## Create roles, policies and demo accounts (local and test environments only)
	APP_DATABASE_URL="$$APP_DATABASE_URL_HOST" $(UV) run --package governed-analytics-backend python -m app.db.seed

verify-audit: ## Verify the audit log hash chain (exit 1 when a row was changed or removed)
	APP_DATABASE_URL="$$APP_DATABASE_URL_HOST" $(UV) run --package governed-analytics-backend python scripts/verify_audit_chain.py

test-db: ## Create the isolated test database (copilot_test) with extensions and app schema
	$(COMPOSE) exec -T postgres psql -U $${POSTGRES_SUPERUSER:-postgres} -d postgres -tc "SELECT 1 FROM pg_database WHERE datname = 'copilot_test'" | grep -q 1 || 		$(COMPOSE) exec -T postgres psql -U $${POSTGRES_SUPERUSER:-postgres} -d postgres -c "CREATE DATABASE copilot_test"
	$(COMPOSE) exec -T postgres psql -U $${POSTGRES_SUPERUSER:-postgres} -d copilot_test -v ON_ERROR_STOP=1 		-c "CREATE EXTENSION IF NOT EXISTS vector" -c "CREATE EXTENSION IF NOT EXISTS pg_trgm" 		-c "CREATE SCHEMA IF NOT EXISTS app AUTHORIZATION app_rw"

smoke-llm: ## Make one real request to each configured LLM provider (needs API keys in .env)
	$(UV) run --package governed-analytics-backend python scripts/smoke_llm.py

seed: ## Create roles, policies and demo accounts (alias of seed-users)
	$(MAKE) seed-users

test: ## Run unit tests for all Python packages (backend tests need make test-db)
	$(UV) run --package governed-analytics-backend pytest backend/tests
	$(UV) run --package governed-analytics-scripts pytest scripts/tests
	$(UV) run --package governed-analytics-warehouse pytest warehouse/tests -m "not integration"

lint: ## Run ruff, mypy and frontend lint
	$(UV) run ruff check .
	$(UV) run ruff format --check .
	$(UV) run --package governed-analytics-backend mypy backend/app
	pnpm --filter frontend lint

eval: ## Run the evaluation harness (Phase 10)
	@echo "eval: not implemented until Phase 10"
