# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    DAGSTER_HOME=/opt/dagster_home

COPY --from=ghcr.io/astral-sh/uv:0.8.22 /uv /usr/local/bin/uv

WORKDIR /workspace
COPY pyproject.toml uv.lock ./
COPY backend/pyproject.toml backend/pyproject.toml
COPY warehouse/pyproject.toml warehouse/pyproject.toml
COPY scripts/pyproject.toml scripts/pyproject.toml
COPY orchestration/dagster_project orchestration/dagster_project
RUN uv sync --locked --package governed-analytics-orchestration --no-dev --no-editable \
    && mkdir -p /opt/dagster_home

WORKDIR /workspace/orchestration/dagster_project
EXPOSE 3000
CMD ["dagster-webserver", "-h", "0.0.0.0", "-p", "3000", "-m", "dagster_project"]
