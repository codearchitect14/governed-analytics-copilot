# Meridian Data Copilot

Governed natural language analytics for business users. Questions are resolved against a semantic layer where
possible, SQL is generated only when needed, role based access is enforced in several layers, every generated query
is shown, and every request is written to an audit log.

> Status: Phases 0, 1 and 2 (foundation, warehouse, semantic layer). See [Project status](#project-status).
> The full build plan is in [PROJECT_PLAN.md](PROJECT_PLAN.md).

## Quick start

Requirements: Docker, Python 3.12, [uv](https://docs.astral.sh/uv/), Node.js 22.12 or later, pnpm 10.18.2.

```bash
cp .env.example .env          # then replace every change-me value
docker compose up -d --build --wait
curl http://localhost:8010/api/v1/health   # {"status":"ok","version":"0.1.0"}
```

| Service | URL |
|---|---|
| Web | http://localhost:5180 |
| API | http://localhost:8010 (OpenAPI at `/docs`) |
| Dagster | http://localhost:3010 |
| PostgreSQL | localhost:5433 (database `copilot`) |

Ports can be changed in `.env` if they are in use.

### Load the warehouse

```bash
make data-sample   # committed sample, no Kaggle account needed (available once Phase 1 sample is committed)
make data          # full Olist download from Kaggle, then load and build
```

`make` targets load `.env` automatically. On Windows without `make`, run the commands in the Makefile directly
(the scripts are plain Python and dbt is run from `warehouse/dbt_project`).

### Semantic layer

```bash
make semantic-validate   # mf validate-configs against the warehouse
make golden              # 30 plan fixtures: MetricFlow SQL result must match the gold SQL
make index               # embed metrics, dimensions and examples into pgvector (app schema)
make retrieval           # top 3 recall on paraphrased mentions (target 95 percent)
```

Metrics, dimensions and the time spine are defined in `warehouse/dbt_project/models/semantic`.
Business vocabulary is in `dataset/semantic_seed/synonyms.yml`. The embedding model is
`BAAI/bge-small-en-v1.5` (384 dimensions) run locally through fastembed (ONNX).

## Repository layout

```
backend/            FastAPI application (app/), tests and Dockerfile
frontend/           React and Vite web application, nginx image
orchestration/      Dagster code location (dagster_project/)
warehouse/          dbt project (dbt_project/) and dbt tooling
scripts/            dataset download, load and sample scripts (with tests)
dataset/            dataset documentation, sample and downloads (see dataset/README.md)
infra/postgres/     database bootstrap: extensions, schemas, least privilege roles
.github/workflows/  CI: lint, types, tests, warehouse build, stack health, security scans
```

## Database roles

| Role | Access | Used by |
|---|---|---|
| `loader` | Writes `raw`, builds `analytics` | Load scripts and dbt |
| `warehouse_ro` | `SELECT` on `analytics` only, 10 s statement timeout | Query executor (Phase 5) |
| `app_rw` | Owns `app` schema | API (users, policies, audit) |

`raw` and `analytics` are not readable by `app_rw`, and `raw` is not readable by `warehouse_ro`.

## Development

```bash
uv sync --all-packages                                # Python workspace
pnpm install                                          # frontend workspace
uv run --package governed-analytics-backend pytest backend/tests
uv run --package governed-analytics-scripts pytest scripts/tests
uv run ruff check . && uv run ruff format --check .
uv run --package governed-analytics-backend mypy backend/app
pnpm --filter frontend lint && pnpm --filter frontend typecheck && pnpm --filter frontend build
```

Pre-commit hooks are defined in `.pre-commit-config.yaml` (ruff, mypy, prettier, eslint, gitleaks).

## Project status

| Phase | Scope | Status |
|---|---|---|
| 0 | Foundation: monorepo, compose stack, CI, health endpoints | Complete |
| 1 | Dataset scripts, raw load, dbt staging, intermediate, marts, aggregates, tests | Built and verified on a fixture. Full-dataset run pending the Kaggle download |
| 2 | MetricFlow semantic models, 30 plan fixtures, rule resolver, time parser, pgvector catalog index | Built and verified. Fixture data only until the full Olist load |

The 5,000 order sample and the full-data row counts are produced once the Olist archive is available.

## Licenses and attribution

Dataset attribution and license notes: [dataset/README.md](dataset/README.md).
