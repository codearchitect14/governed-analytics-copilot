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

.PHONY: help up down logs ps data data-sample dbt seed test lint eval \
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

seed: ## Backfill synthetic operations history (Phase 7)
	@echo "seed: not implemented until Phase 7"

test: ## Run unit tests for all Python packages (integration tests are excluded)
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
