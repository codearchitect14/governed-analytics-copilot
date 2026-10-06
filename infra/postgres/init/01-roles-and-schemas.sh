#!/bin/bash
# Runs once, when the postgres data volume is first initialized.
# Creates extensions, schemas and least privilege database roles.
# Passwords are passed in from the environment (.env) and never written to disk.
set -euo pipefail

: "${LOADER_DB_PASSWORD:?LOADER_DB_PASSWORD must be set}"
: "${WAREHOUSE_RO_DB_PASSWORD:?WAREHOUSE_RO_DB_PASSWORD must be set}"
: "${APP_RW_DB_PASSWORD:?APP_RW_DB_PASSWORD must be set}"

psql -v ON_ERROR_STOP=1 \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" \
  -v loader_pw="$LOADER_DB_PASSWORD" \
  -v ro_pw="$WAREHOUSE_RO_DB_PASSWORD" \
  -v app_pw="$APP_RW_DB_PASSWORD" <<'EOSQL'
-- Extensions used by the application (pgvector for embeddings, pg_trgm for synonym matching)
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Database roles (one login role per responsibility)
CREATE ROLE loader LOGIN PASSWORD :'loader_pw';
CREATE ROLE warehouse_ro LOGIN PASSWORD :'ro_pw';
CREATE ROLE app_rw LOGIN PASSWORD :'app_pw';

-- Session guard rails for the read only executor role
ALTER ROLE warehouse_ro SET statement_timeout = '10s';
ALTER ROLE warehouse_ro SET idle_in_transaction_session_timeout = '30s';
ALTER ROLE warehouse_ro SET search_path = analytics;

-- Application role guard rails
ALTER ROLE app_rw SET statement_timeout = '30s';
ALTER ROLE app_rw SET idle_in_transaction_session_timeout = '60s';

-- Schemas (one per data zone, see docs/architecture.md)
CREATE SCHEMA raw AUTHORIZATION loader;
CREATE SCHEMA analytics AUTHORIZATION loader;
CREATE SCHEMA app AUTHORIZATION app_rw;

-- The public schema is not a place for application objects
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

-- loader: writes raw, builds analytics (dbt and load scripts). No access to app.
GRANT USAGE ON SCHEMA raw TO loader;
GRANT USAGE, CREATE ON SCHEMA analytics TO loader;

-- warehouse_ro: SELECT only on analytics. No access to raw or app.
-- warehouse_ro read access is granted per model by the dbt post-run macro (marts only, with row level security)

-- app_rw: owns the app schema only.
REVOKE ALL ON SCHEMA raw FROM app_rw;
REVOKE ALL ON SCHEMA analytics FROM app_rw;
EOSQL

echo "Database bootstrap complete: schemas raw, analytics, app; roles loader, warehouse_ro, app_rw."
