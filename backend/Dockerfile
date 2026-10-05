# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv

COPY --from=ghcr.io/astral-sh/uv:0.8.22 /uv /usr/local/bin/uv

WORKDIR /workspace
COPY pyproject.toml uv.lock ./
COPY backend/pyproject.toml backend/pyproject.toml
COPY orchestration/dagster_project/pyproject.toml orchestration/dagster_project/pyproject.toml
COPY warehouse/pyproject.toml warehouse/pyproject.toml
COPY scripts/pyproject.toml scripts/pyproject.toml
COPY backend/app backend/app
RUN uv sync --locked --package governed-analytics-backend --no-dev --no-editable

# dbt packages (dbt_utils) are needed for MetricFlow to parse the project at query time
COPY warehouse/dbt_project /workspace/warehouse/dbt_project
RUN cd /workspace/warehouse/dbt_project && DBT_PROFILES_DIR=/workspace/warehouse/dbt_project /opt/venv/bin/dbt deps

# MetricFlow reads the semantic manifest from target/. Parsing does not connect, so placeholders suffice.
RUN cd /workspace/warehouse/dbt_project && DBT_PROFILES_DIR=/workspace/warehouse/dbt_project WAREHOUSE_RO_DB_PASSWORD=build-only LOADER_DB_PASSWORD=build-only /opt/venv/bin/dbt parse --target executor

# Embedding model, downloaded at build time so that the running container needs no network access
RUN /opt/venv/bin/python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5', cache_dir='/opt/models')"

FROM python:3.12-slim-bookworm AS runtime
ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1 \
    DBT_PROJECT_DIR=/opt/backend/warehouse/dbt_project \
    SEMANTIC_SEED_DIR=/opt/backend/semantic_seed \
    EMBEDDING_CACHE_DIR=/opt/models \
    LLM_CONFIG_PATH=/opt/backend/llm_config.yml
RUN useradd --create-home --uid 10001 app
COPY --from=base /opt/venv /opt/venv
COPY --from=base /opt/models /opt/models
WORKDIR /opt/backend
COPY backend/alembic.ini alembic.ini
COPY backend/migrations migrations
COPY backend/llm_config.yml llm_config.yml
COPY dataset/semantic_seed semantic_seed
COPY --from=base /workspace/warehouse/dbt_project warehouse/dbt_project
USER app
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=2).status == 200 else 1)"
# Apply schema migrations before serving. The migration role owns the app schema.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
