# Governed Analytics Copilot: End to End Build Plan

Working product name (configurable in one constants file): **Meridian Data Copilot**.

A natural language analyst for business users. It resolves questions against a semantic layer, generates SQL only when needed, enforces role based row level access, shows its SQL, logs every query, and ships with an accuracy evaluation harness.

Request flow: question -> cache and rule resolution -> semantic layer resolution -> SQL generation or compilation -> validation -> permission rewrite -> execution -> chart and explanation -> audit log.

---

## 0. Ground Rules For The Developer

1. Everything in this plan uses free and open source software, or free tiers only. No paid service is required anywhere.
2. Professional wording only, in code, comments, commit messages, UI copy, README and docs. No jokes, slang, filler or references to AI assistants or tools used to write the code.
3. Never use the em dash character in any file (code, docs, UI strings, README, commit messages). Use a hyphen, colon or comma.
4. Commit messages follow Conventional Commits. Every phase ends with a tagged release (`v0.1.0` and so on) and a green CI run.
5. A clear and professional `README.md` is a deliverable (see Phase 12). Update it at the end of every phase, not only at the end of the project.
6. Secrets never enter the repository. Only `.env.example` is committed.
7. Pin all dependency versions. Use `uv` for Python and `pnpm` for the frontend.

---

## 1. Tech Stack (all free)

| Layer | Choice |
|---|---|
| Language | Python 3.12, TypeScript 5 |
| Backend API | FastAPI, Pydantic v2, SQLAlchemy 2.0 (async), Alembic, psycopg 3, uvicorn, structlog |
| Warehouse and app database | PostgreSQL 16 with pgvector (Docker image `pgvector/pgvector:pg16`) |
| Transformations | dbt-core, dbt-postgres, dbt-utils |
| Semantic layer | MetricFlow (dbt-metricflow, Apache 2.0) YAML semantic models and metrics |
| SQL validation and rewriting | sqlglot (parse, allow list, predicate injection, column masking) |
| Embeddings | Hugging Face `BAAI/bge-small-en-v1.5` (384 dim, MIT) via `sentence-transformers`, running locally on CPU. Alternative: `sentence-transformers/all-MiniLM-L6-v2` |
| Vector search | pgvector with HNSW index, cosine distance |
| LLM providers | Groq `openai/gpt-oss-20b` (primary) and Google Gemini API `gemini-2.5-flash` with `gemini-2.5-flash-lite` as lighter option. Both on free tiers |
| LLM SDKs | `groq`, `google-genai` |
| Authentication | JWT access token (PyJWT), rotating refresh token in httpOnly cookie, `argon2-cffi` password hashing |
| Authorization | RBAC with policy rows in the database, plus PostgreSQL native Row Level Security |
| Orchestration and evaluation | Dagster with dagster-dbt, evaluation assets partitioned by model and prompt version |
| Frontend | React 18, Vite, TypeScript, React Router, TanStack Query, TanStack Table, Zustand, Tailwind CSS, shadcn/ui (Radix), Framer Motion, react-hook-form with zod |
| Charts | Apache ECharts (echarts-for-react) |
| SQL display | Shiki or Prism with `sql-formatter` |
| Icons and fonts | Lucide icons, Inter (UI) and IBM Plex Mono (code) from Google Fonts, self hosted |
| Testing | pytest, pytest-asyncio, hypothesis, Vitest, React Testing Library, Playwright, axe-core, Lighthouse CI |
| Quality and security tooling | ruff, mypy, pre-commit, ESLint, Prettier, bandit, pip-audit, pnpm audit, gitleaks, Trivy |
| Packaging and CI | Docker, Docker Compose, GitHub Actions |
| Optional free hosting | Frontend on Cloudflare Pages or Netlify, backend on Render or Fly.io free tier, database on Neon or Supabase (both offer pgvector) |

Warehouse decision: Olist is loaded into PostgreSQL so the app, dbt, RLS and pgvector share one engine. DuckDB is allowed only inside the evaluation harness for the Spider and BIRD SQLite files, which are evaluated in their native SQLite form.

---

## 2. Dataset Section

Create a top level `dataset/` folder. It must make the demo look like a real operating business.

### 2.1 Sources

| Dataset | Purpose | Where to get it |
|---|---|---|
| Olist Brazilian E-Commerce (public dataset) | Main warehouse. About 100k orders from 2016 to 2018, 9 relational tables | Kaggle: `olistbr/brazilian-ecommerce`. Command: `kaggle datasets download -d olistbr/brazilian-ecommerce` (free Kaggle account and API token required). Fallback: manual download from `https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce` |
| Olist Marketing Funnel (optional) | Extra lead and seller onboarding tables for a Marketing dashboard tab | Kaggle: `olistbr/marketing-funnel-olist` |
| BIRD Mini-Dev | Text to SQL accuracy benchmark. 500 question and SQL pairs over 11 databases | `https://github.com/bird-bench/mini_dev`. Archive: `https://bird-bench.oss-cn-beijing.aliyuncs.com/minidev.zip`. Leaderboard and full dev set: `https://bird-bench.github.io/` |
| Spider dev set | Text to SQL accuracy benchmark. 1,034 dev questions over 20 databases | Official page `https://yale-lily.github.io/spider` (dataset and test suite evaluation scripts). Hugging Face mirror: `xlangai/spider` |
| Brazil states GeoJSON | Choropleth map on the dashboard | IBGE based public GeoJSON, for example the `geodata-br-states` repository on GitHub. Store as `dataset/geo/brazil_states.geojson` |

Verify each license before publishing. Olist is released under CC BY-NC-SA 4.0 (attribution and non commercial use), and BIRD and Spider use share alike licenses. Add attribution and license notes in `dataset/README.md` and the main README.

### 2.2 Folder layout

```
dataset/
  README.md                 sources, licenses, checksums, how to refresh
  checksums.sha256
  raw/olist/                original CSV files (git ignored, created by script)
  sample/olist/             5,000 order sample, committed, used by CI and quick start
  benchmarks/
    bird_mini_dev/          extracted minidev (git ignored)
    spider/                 extracted dev set and databases (git ignored)
  golden/
    olist_golden_v1.jsonl   hand verified question, expected metric plan, gold SQL, role, expected outcome
    permission_tests.jsonl  role based allow and deny cases
    adversarial.jsonl       prompt injection, DDL attempts, unanswerable questions
  semantic_seed/
    synonyms.yml            business vocabulary mapped to metrics and dimensions
    few_shot_examples.jsonl verified question to plan pairs used for retrieval
  geo/brazil_states.geojson
  images/                   product and marketing images with ATTRIBUTION.md
```

### 2.3 Scripts

- `scripts/download_data.py`: downloads Olist (Kaggle API), BIRD Mini-Dev and Spider, verifies checksums, extracts into the folders above. Prints clear manual steps if credentials are missing.
- `scripts/load_olist.py`: creates schema `raw` and loads the 9 CSV files with PostgreSQL `COPY`, then records row counts. Idempotent (truncate and reload).
- `make data` runs both scripts. `make data-sample` loads only the committed sample.

### 2.4 Olist tables and known data quirks (handle in dbt staging)

Tables: `customers`, `geolocation`, `order_items`, `order_payments`, `order_reviews`, `orders`, `products`, `sellers`, `product_category_name_translation`.

- `customer_id` is per order, `customer_unique_id` identifies the real customer. Use the latter for customer counts and repeat rate.
- Source columns `product_name_lenght` and `product_description_lenght` are misspelled. Rename in staging.
- A few product categories have no English translation. Fall back to the Portuguese name and flag them.
- `geolocation` has many rows per zip prefix. Aggregate to one row per prefix (median lat, lng) before joining.
- `order_reviews` can contain several reviews per order. Keep the latest.
- `order_payments` can contain several rows per order (installments, vouchers). Aggregate to order grain.
- Delivery timestamps are null for non delivered orders. Compute `delivery_days`, `delay_days` and `is_late` only for delivered orders.
- Data ends in 2018. Define `data_as_of` (max purchase date) and make every relative phrase such as "last month" or "this year" resolve against `data_as_of`, not the system clock.
- Currency is Brazilian Real (BRL). Show "R$" in the UI.

### 2.5 Demo history for operations dashboards

Olist has no usage history. Write `scripts/seed_demo_history.py` to backfill 90 days of audit and LLM usage rows with realistic daily patterns, flagged `is_synthetic = true`. The Operations dashboard must show a visible "Demo data" badge for those rows. Real usage is added on top.

---

## 3. Architecture And Contracts

### 3.1 Repository layout

```
repo/
  backend/app/{api,core,auth,policy,semantic,llm,pipeline,validator,executor,charts,audit,dashboard,evals,db}
  backend/tests/
  warehouse/dbt_project/{models/staging,models/marts,models/semantic,tests,seeds}
  orchestration/dagster_project/
  frontend/src/{site,app,components,lib,styles}
  dataset/
  scripts/
  docs/
  docker-compose.yml
  Makefile
  README.md
```

### 3.2 Databases and roles

One PostgreSQL instance, three schemas, three database roles:

| Schema | Content | DB role |
|---|---|---|
| `raw` | Loaded Olist CSV tables | `loader` (write) |
| `analytics` | dbt staging and marts, the only surface users can query | `warehouse_ro` (SELECT only, statement timeout 10 s) |
| `app` | users, roles, policies, sessions, audit log, LLM usage, caches, embeddings, eval results | `app_rw` |

### 3.3 Mart design (grain and denormalization for simple policies)

- `analytics.fct_order_items` (grain: order item): order and item ids, purchase timestamp and date keys, item price, freight, line revenue, product category (English), seller id and state, customer state, review score, delivery fields.
- `analytics.fct_orders` (grain: order): status, purchase date, payment total, installments, payment type, delivery days, delay days, is_late, customer state, review score.
- `analytics.dim_customers`, `dim_products`, `dim_sellers`, `dim_date`.
- Denormalize `customer_state`, `seller_id` and `product_category_en` onto the fact tables so every row filter is a single table predicate.
- Pre aggregated tables for dashboards: `agg_revenue_monthly`, `agg_category_monthly`, `agg_state_monthly`, `agg_delivery_monthly`, `agg_cohort_retention`.

### 3.4 Application tables (`app` schema)

`users`, `roles`, `role_policies` (allowed_tables, allowed_columns, row_filters jsonb, masked_columns, max_rows, allow_sql_fallback), `refresh_tokens`, `chat_sessions`, `chat_messages`, `saved_queries`, `audit_log` (append only), `llm_usage` (daily counters per provider), `query_cache` (exact hash), `semantic_cache` (embedding, plan, sql, policy_hash), `catalog_embeddings` (metrics, dimensions, few shot examples), `eval_runs`, `eval_results`, `prompt_versions`.

### 3.5 Roles seeded for the demo

| Role | Access |
|---|---|
| `executive` | All rows, all marts, aggregated metrics, no raw SQL fallback |
| `regional_manager` | Rows where `customer_state` is in the user's region list (for example SP, RJ, MG, ES) |
| `category_manager` | `fct_order_items` rows where `product_category_en` is in the user's category list. `fct_orders` is not in the allow list |
| `seller_partner` | Rows where `seller_id` equals the user's seller id |
| `analyst` | All rows, SQL fallback allowed, customer identifiers masked |
| `admin` | User and policy management, audit access, evaluation and operations pages |

Seed one demo user per role. Document the demo credentials in the README with a note that they are for local demonstration only.

### 3.6 Core API (all under `/api/v1`)

| Endpoint | Purpose |
|---|---|
| `POST /auth/login`, `POST /auth/refresh`, `POST /auth/logout`, `GET /auth/me` | Authentication |
| `POST /chat/query` (SSE stream) | Runs the pipeline, streams step events then the final payload |
| `GET /chat/sessions`, `GET /chat/sessions/{id}` | History |
| `POST /saved-queries`, `GET /saved-queries`, `POST /saved-queries/{id}/run` | Saved questions |
| `GET /catalog/metrics`, `GET /catalog/dimensions` | Semantic catalog filtered by the user's policy |
| `GET /dashboard/overview`, `/sales`, `/customers`, `/logistics`, `/sellers` | Business dashboard data, governed by the same policy engine |
| `GET /admin/audit` (filters, pagination, CSV export), `GET /admin/ops/*`, `GET /admin/evals/*` | Admin analytics |
| `GET/POST/PATCH /admin/users`, `/admin/roles` | Administration |
| `GET /health`, `GET /ready` | Probes |

Final payload of `/chat/query`: `answer_text`, `route`, `plan`, `sql` (generated and final rewritten), `columns`, `rows` (capped), `chart_spec` (ECharts option), `explanation`, `policy_notes` (filters applied, columns masked), `usage` (provider, model, tokens, latency), `audit_id`.

---

## 4. LLM Strategy And Token Minimization

The design target is zero or one LLM call for most questions, and at most three for the hardest ones.

### 4.1 Cost ladder (stop at the first step that answers)

1. **Exact cache**: hash of normalized question plus policy hash. Zero tokens. The SQL is re-validated and re-executed so data stays fresh and permissions stay current.
2. **Semantic cache**: embed the question locally, search `semantic_cache` with cosine similarity of 0.93 or higher and the same policy hash. Zero tokens.
3. **Rule resolver**: match synonyms and metric names with `pg_trgm` and the synonym file, parse time phrases with a local parser anchored to `data_as_of`. If exactly one metric is found with high confidence, build the plan without any LLM call. Target: 30 to 40 percent of the golden set.
4. **LLM call 1, plan**: structured JSON output selecting metrics, dimensions, filters, time range, order and limit from a small retrieved catalog. MetricFlow compiles SQL deterministically, so there is no SQL hallucination on this path.
5. **LLM call 2, SQL fallback**: only when the plan reports that the question cannot be expressed with the semantic layer and the role allows fallback. The prompt contains only retrieved columns of at most 3 marts.
6. **LLM call 3, repair**: only after a validator or execution error, with the error text and previous SQL, maximum one attempt.

Explanations and chart choice are deterministic (templates and rules over the result shape: top item, share of total, change versus previous period). An optional "Generate narrative" button makes one capped LLM call using at most 30 aggregated rows with identifiers masked.

### 4.2 Prompt budget

- Static system prompt first (kept stable so provider prompt caching applies). Target 600 tokens or fewer.
- Retrieved context: top 6 metrics, top 8 dimensions, top 3 verified few shot examples, in compact `name: description (type)` form. Target 600 tokens.
- Total input target: 1,500 tokens or fewer for the plan call, 2,500 or fewer for SQL fallback. Output cap: 300 tokens for plan, 500 for SQL.
- No result rows are ever sent to the LLM except in the optional narrative call.
- Use low reasoning effort for the Groq model and disable reasoning text in the response where the parameter is supported. Use JSON schema structured output where supported, otherwise JSON mode with Pydantic validation.
- Record `tokens_in`, `tokens_out`, provider and route on every request.

### 4.3 Provider router (`backend/app/llm/`)

- Common `LLMProvider` interface with `groq_provider.py` and `gemini_provider.py`. Same internal prompt format, adapters translate to each API.
- Configuration in `.env` and `llm_config.yml`: priority order, model names, per minute and per day request and token ceilings. Free tier limits change often and sources disagree, so read the real values from each provider console and set them in config. Reference values at planning time: Groq `gpt-oss-20b` about 30 requests per minute, 1,000 per day, 8,000 tokens per minute, 200,000 tokens per day. Gemini 2.5 Flash class models have lower per minute limits than Flash-Lite. Both are enforced per organization or project, not per key.
- Local token bucket per provider (requests and tokens per minute) plus daily counters in `llm_usage`. Choose the provider with remaining budget in priority order.
- Failover on 429, 5xx or timeout with one retry on the other provider and a 60 second circuit breaker. Read rate limit response headers when present.
- Admin setting: `auto`, `groq_only`, `gemini_only`. Show the active provider and remaining budget in the Operations page.
- Prompts live in `backend/app/llm/prompts/` with a version in the filename and a row in `prompt_versions`. The version is stored in every audit and evaluation record.
- Treat all model output as untrusted input. Never execute it without the validator.

---

## 5. Data Security, Authentication And Authorization

### 5.1 Authentication

- Argon2id password hashing. Password policy: minimum 12 characters. Account lockout after 5 failures for 15 minutes.
- Access JWT with 15 minute expiry (claims: `sub`, `role`, `policy_version`, `jti`). Refresh token with 7 day expiry, stored hashed in `refresh_tokens`, rotated on each use, set as `httpOnly; Secure; SameSite=Strict` cookie. Reuse of a rotated token revokes the whole token family.
- Frontend keeps the access token in memory only. No tokens in localStorage.

### 5.2 Authorization (defense in depth, four layers)

1. **Route level RBAC**: FastAPI dependencies check role per endpoint.
2. **Policy engine**: loads `role_policies` for the user. Produces allowed tables, allowed columns, row filters, masked columns and a `policy_hash`.
3. **SQL rewrite with sqlglot**: every table reference is replaced with a filtered subquery containing the row predicate. Masked columns are replaced with a hash or a null expression. Columns outside the allow list cause a denial with a clear reason.
4. **PostgreSQL Row Level Security**: policies on `analytics` tables read `current_setting('app.user_filters')`. The executor opens a transaction, runs `SET LOCAL` for session variables, executes with the `warehouse_ro` role. Even a validator bug cannot return forbidden rows.

### 5.3 SQL validator rules (sqlglot, Postgres dialect)

- Exactly one statement, SELECT or WITH only. Reject DDL, DML, COPY, SET, CALL, multiple statements and comments containing directives.
- Allow listed relations only (`analytics.*` views allowed for the role). Block `pg_catalog`, `information_schema`, system functions (`pg_read_file`, `dblink`, `pg_sleep` and similar) and set returning abuse.
- Require a LIMIT (inject the role `max_rows`, default 1,000). Reject cross joins without predicates and queries whose `EXPLAIN` estimated cost exceeds a configured ceiling.
- Qualify columns, resolve aliases, and reject unknown columns before execution.

### 5.4 Other controls

- Prompt injection: user text is only placed inside a delimited data field. System rules state that the question is never an instruction source. Adversarial cases in `adversarial.jsonl` are part of the evaluation.
- Least privilege database roles, `statement_timeout`, `idle_in_transaction_session_timeout`, row cap in the executor.
- Audit log is append only (trigger blocks UPDATE and DELETE) with a hash chain (`prev_hash`, `row_hash`) and a verification script `scripts/verify_audit_chain.py`.
- Rate limiting with `slowapi` (per user and per IP). CORS allow list. Security headers: CSP, HSTS, X-Content-Type-Options, Referrer-Policy, frame protections.
- Input size limits, strict Pydantic models, generic error messages to the client, detailed errors only in server logs with request ids.
- Supply chain and scanning in CI: pip-audit, pnpm audit, bandit, gitleaks, Trivy image scan.
- Document the threat model briefly in `docs/security.md` (assets, actors, controls, residual risk).

### 5.5 Audit record (one row per request, including denied ones)

`id, ts, user_id, role, session_id, question, normalized_question, route (cache, semantic_cache, rule, llm_plan, llm_sql), provider, model, prompt_version, tokens_in, tokens_out, plan_json, generated_sql, final_sql, validation_result, policy_hash, decision (allowed, denied, clarify, error), denial_reason, row_count, exec_ms, total_ms, is_synthetic, prev_hash, row_hash`.

---

## 6. Phase Wise Development Plan

Estimates assume one full time developer. Total about 10 to 12 weeks.

### Phase 0: Foundation (2 days)

**Tasks**
- Create the monorepo structure from section 3.1. Initialize `uv` workspace, `pnpm` workspace, `.editorconfig`, `.gitignore`, pre-commit hooks (ruff, mypy, prettier, eslint, gitleaks).
- Write `docker-compose.yml` with services: `postgres` (pgvector image, healthcheck, init SQL creating schemas, roles and extensions `vector`, `pg_trgm`), `api`, `web`, `dagster`.
- `Makefile` targets: `up`, `down`, `data`, `dbt`, `seed`, `test`, `lint`, `eval`.
- GitHub Actions: lint, type check, unit tests, build images, security scans.
- `.env.example` with every variable documented.

**Acceptance**: `make up` starts a healthy stack. CI is green on an empty app with a `/health` endpoint.

### Phase 1: Dataset And Warehouse (4 days)

**Tasks**
- Implement `download_data.py` and `load_olist.py` (section 2.3). Create the committed 5,000 order sample with referential integrity preserved.
- Build dbt project: staging models (one per raw table with renames, typing, quirk fixes from 2.4), intermediate models, marts from 3.3, aggregate tables for dashboards.
- Add dbt tests: unique, not_null, relationships, accepted_values, plus custom tests (revenue reconciliation between item and order grain, no negative delivery days). Generate dbt docs.
- Create `analytics` read only views and grants for `warehouse_ro`.

**Acceptance**: full load plus `dbt build` succeeds with all tests passing. Row counts match the Olist source (about 99,441 orders). Reconciliation test passes.

### Phase 2: Semantic Layer And Catalog Index (4 days)

**Tasks**
- Write MetricFlow semantic models (`fct_order_items`, `fct_orders`, dimensions) with entities, measures, time dimensions (day, week, month, quarter, year).
- Define metrics with clear business definitions: `revenue` (item price on non canceled orders), `gmv`, `orders`, `items_sold`, `aov`, `freight_revenue`, `payment_value`, `unique_customers`, `repeat_customer_rate`, `avg_review_score`, `avg_delivery_days`, `on_time_delivery_rate`, `late_delivery_rate`, `cancellation_rate`, `avg_installments`. Each has `description`, `label`, `synonyms` (in `meta`), and a plain language definition.
- Dimensions: purchase date grains, `customer_state`, `customer_city`, `product_category_en`, `seller_id`, `seller_state`, `payment_type`, `order_status`, `review_score`, `delivery_status`.
- Write `semantic_seed/synonyms.yml` (for example "sales" and "turnover" map to `revenue`; "region" maps to `customer_state`; "SP" maps to filter value).
- Build the catalog indexer: embed each metric, dimension and verified few shot example with the local embedding model and store in `catalog_embeddings` with an HNSW index. Cache the model on disk, load once at API startup.
- Build `semantic/compiler.py`: given a validated plan JSON, call MetricFlow to produce SQL (wrap `mf query --explain` or the Python API in a service with timeout). Add a golden SQL comparison test for at least 30 plans.
- Build `semantic/rule_resolver.py` and `semantic/time_parser.py` (anchored to `data_as_of`).

**Acceptance**: `mf validate-configs` passes. 30 plan fixtures compile to SQL that matches gold results. Top 3 retrieval recall at least 95 percent on the golden metric and dimension mentions.

### Phase 3: Backend Core, Authentication And Authorization (5 days)

**Tasks**
- FastAPI app factory, settings (pydantic-settings), structured logging with request ids, error handlers, OpenAPI metadata.
- Alembic migrations for all `app` tables. Seed script for roles, policies and demo users.
- Implement section 5.1 fully: login, refresh rotation, logout, lockout, `/auth/me`.
- Implement policy engine and `policy_hash` (section 5.2 layers 1 and 2).
- Implement the append only audit writer with hash chain and the verification script.
- Rate limiting and security headers.

**Acceptance**: auth test suite covers expiry, rotation, token reuse revocation, lockout, wrong role access. Audit chain verification passes and detects a manual tamper in a test.

### Phase 4: LLM Gateway (3 days)

**Tasks**
- Implement the provider interface, the two adapters, the budget tracker, failover and circuit breaker (section 4.3).
- Structured output handling with Pydantic validation and a single schema repair retry.
- Prompt files with versions. Plan prompt and SQL fallback prompt and repair prompt.
- Token accounting into `llm_usage` and the audit row.
- Provider contract tests using recorded fixtures (no network in CI). A manual live smoke test script `scripts/smoke_llm.py`.

**Acceptance**: simulated 429 on one provider fails over to the other within one request. Daily counters reset correctly. Prompt token counts stay within section 4.2 budgets on the golden set.

### Phase 5: Query Pipeline (6 days)

Implement as a state machine in `backend/app/pipeline/` with each step timed and streamed as an SSE event (`resolving`, `planning`, `generating`, `validating`, `applying_policy`, `executing`, `charting`, `done`).

**Tasks**
1. Normalize question, exact cache lookup, semantic cache lookup (section 4.1 steps 1 and 2).
2. Rule resolver, then LLM plan call with retrieved catalog. Handle intents: `metric_query`, `sql_fallback`, `clarify` (ambiguous metric or period, return one short question), `refuse` (out of scope or policy).
3. Compile via MetricFlow or run fallback generation. Fallback is allowed only if the role policy allows it.
4. Validator (section 5.3) with one repair attempt.
5. Policy rewrite (section 5.2 layer 3) and `EXPLAIN` cost gate.
6. Executor: transaction, `SET LOCAL` session variables, timeout, row cap, return typed columns.
7. Chart selector: rules over column types and cardinality (line for time series, bar for category ranking, grouped bar for two dimensions, scatter for two measures, KPI card for a single value, table otherwise). Output an ECharts option object.
8. Explanation builder: deterministic template with top contributors, share of total, period change, applied filters and definitions of the metrics used.
9. Write the audit row for every outcome, including denials and errors.
10. Save results to cache tables only after a successful execution.

**Acceptance**: 20 curated questions run end to end in all route types. Denied requests return a clear policy explanation and are audited. Median latency under 2.5 seconds on cache miss with a provider response, under 400 ms on cache hit.

### Phase 6: Governance Hardening (3 days)

**Tasks**
- Create PostgreSQL RLS policies and `SET LOCAL` integration (section 5.2 layer 4).
- Column masking for `analyst` (hash customer identifiers).
- Write the permission test matrix from `permission_tests.jsonl`: the same question asked as each role must return different, correct results, and cross role leakage must be zero.
- Property based tests (hypothesis) for the validator and rewriter using generated SQL variations (aliases, CTEs, subqueries, unions, quoted identifiers, comments).
- Penetration style tests: stacked queries, `pg_sleep`, catalog access, `SELECT *` on masked tables, prompt injection strings.

**Acceptance**: leakage rate 0 percent on all permission and adversarial cases. Disabling the rewrite layer in a test still yields zero leakage because of RLS.

### Phase 7: Dashboard APIs And Operations Analytics (4 days)

**Tasks**
- Implement `/dashboard/*` endpoints reading dbt aggregate tables through the same policy engine so each role sees only its own slice. Support filters (date range, state, category), comparison (previous period, same period last year) and ETag caching.
- Business dashboard datasets: KPI summary with deltas and sparklines, revenue time series with MoM and YoY and 3 month moving average, revenue by category, revenue and orders by state, weekday by hour order heatmap, payment type mix, order status funnel, cohort retention matrix, delivery performance (estimated versus actual, late rate trend), review score distribution, top sellers and top products tables.
- Operations endpoints (admin only): queries per day, success and denial rate, route mix (cache, rule, llm), cache hit rate, tokens by provider, tokens saved versus a no cache baseline, latency p50 and p95, failure categories, most asked questions, eval accuracy trend by run.
- Run `seed_demo_history.py` and verify numbers are consistent across charts.

**Acceptance**: every dashboard endpoint responds under 300 ms with warm cache. Totals on the dashboard reconcile with a chat answer to the same question.

### Phase 8: Frontend Foundation And Marketing Website (6 days)

Goal: a public site that looks like a Fortune 100 enterprise software company, with a clear "Sign in" entry to the application.

**Design system (build first, in `frontend/src/styles` and `components/ui`)**
- Tokens: deep navy primary (`#0B1F3A`), electric blue accent (`#0A66FF`), teal secondary (`#00A3A3`), neutral gray scale, semantic success, warning and danger colors. Light and dark themes via CSS variables. Chart palette is color blind safe.
- Typography: Inter for UI, IBM Plex Mono for code. Type scale with 1.25 ratio. 8 point spacing grid. Consistent radius, elevation and focus ring tokens.
- Components: Button, Input, Select, Tabs, Card, Badge, Table, Dialog, Drawer, Tooltip, Toast, Skeleton, EmptyState, Breadcrumbs, Pagination, DateRangePicker, KpiCard, CodeBlock.
- Standards: WCAG 2.2 AA, keyboard navigation, reduced motion support, responsive from 360 px to 1920 px.

**Public pages and content**
- **Global header**: sticky, logo wordmark, mega menu (Platform, Solutions, Security, Benchmarks, Resources), a "Sign in" text link and a primary "Request a demo" button. Language and theme toggles. Slim announcement bar.
- **Home**
  1. Hero: headline "Trusted answers from your data, in plain language", subheading about governed metrics, role based access and full auditability. Primary CTA "Sign in to the workspace", secondary CTA "Watch product tour". Right side shows a real product screenshot of the chat UI with chart and SQL panel.
  2. Credibility strip: "Built on open standards" with PostgreSQL, dbt, MetricFlow, FastAPI, Dagster, React logos (grayscale, from Simple Icons).
  3. Value pillars (3 cards): Governed metrics, Role based access, Auditable by design. Short copy and an icon each.
  4. "How it works" 6 step horizontal timeline matching the request flow, with a small illustration per step.
  5. Product showcase: tabbed section (Ask, Inspect SQL, Visualize, Audit) with screenshots captured from the live app.
  6. Metrics band: counters from the real evaluation results JSON (accuracy on the Olist golden set, percentage answered with zero model calls, average tokens per question, permission leakage rate of zero).
  7. Role based use cases: Executive, Regional manager, Category manager, Seller partner, Analyst, each with a sample question and a sample answer card.
  8. Security and governance section with a layered diagram (policy engine, SQL validation, database row level security, audit log).
  9. Dashboard preview: large screenshot of the revenue dashboard with a "Explore the dashboard" link to sign in.
  10. FAQ accordion (8 to 10 items), final call to action band, and a rich footer.
- **Platform page**: architecture diagram (SVG), semantic layer explanation, supported metrics catalog table.
- **Solutions page**: one section per role with a business scenario.
- **Security page**: authentication, authorization layers, audit, data handling statements. Honest scope, no unverified compliance claims.
- **Benchmarks page**: live table and chart from `evals` results (Olist golden set, BIRD Mini-Dev, Spider dev), methodology, model and prompt version, run date.
- **Resources page**: documentation links, API reference link, README link, data dictionary.
- **About and Contact**: short company style page and a contact form (stored in a table, validated, rate limited).
- **Legal**: Privacy, Terms, Cookie notice, Accessibility statement, Data attribution. Clearly marked as demonstration documents.
- **404 and error pages** styled consistently.
- **Footer**: sitemap columns, social placeholders, copyright, legal links, dataset attribution line.

**Imagery and content rules**
- Use free licensed assets only: Unsplash and Pexels photography (analytics, teams, offices, data centers, e-commerce logistics), unDraw illustrations, Simple Icons, Lucide. Download into `frontend/public/images/`, optimize to WebP/AVIF with responsive `srcset`, and record every source and license in `dataset/images/ATTRIBUTION.md`. Do not hotlink.
- Product screenshots are generated by a Playwright script (`scripts/capture_screenshots.ts`) from the running app with demo data, so they are always real and current.
- No fabricated customer logos, quotes or compliance badges. Use only truthful, demonstration appropriate content.

**Acceptance**: Lighthouse scores of 90 or higher for performance, accessibility, best practices and SEO on the home page. Zero axe critical issues. Site renders correctly on mobile, tablet and desktop.

### Phase 9: Application Frontend (8 days)

Routes under `/app` behind an auth guard. The access token stays in memory and silent refresh runs through the cookie.

**Login page**: split layout (brand panel with imagery and short value statement, form panel), email and password, inline validation, error handling for lockout, demo account quick fill chips (local mode only), link back to the site.

**App shell**: left navigation (Chat, Dashboard, Catalog, History, Saved, and Admin group for admins), top bar with global search, theme toggle, user menu with role badge. Breadcrumbs. Empty and loading states everywhere.

**Chat workspace (`/app/chat`)**
- Message list with user questions and structured answer cards.
- Live pipeline progress from SSE (resolving, planning, validating, executing) with timings.
- Answer card tabs: Answer (text, key figures, chart), Data (virtualized TanStack table, sort, CSV export), SQL (formatted, copy button, toggle between generated SQL and final SQL after policy rewrite), Plan (metrics, dimensions, filters, period), Governance (role, row filters applied, masked columns, route, provider, tokens, latency, audit id).
- Chart toolbar: switch chart type, download PNG.
- Suggested questions by role, follow up chips, clarification prompts rendered as quick reply buttons, thumbs up and down feedback stored for evaluation.
- Save question, rerun, share link to the audit entry for admins.
- Error and denial states written in plain professional language.

**Business dashboard (`/app/dashboard`)**
- Tabs: Executive Overview, Sales, Customers, Logistics, Sellers.
- Global filter bar: date range with presets (anchored to `data_as_of`), state, category, compare toggle (previous period or same period last year).
- Overview: 6 KPI cards with sparkline and delta (Revenue, Orders, AOV, Unique customers, On time delivery rate, Average review score), revenue trend area chart with MoM and YoY overlays and moving average, revenue by category bar and treemap, Brazil state choropleth, payment mix donut, order status funnel.
- Sales: revenue and orders by month, weekday by hour heatmap, category growth ranking, top products table.
- Customers: new versus repeat customers, cohort retention heatmap, geography table.
- Logistics: delivery days distribution, estimated versus actual delivery, late rate trend by state, freight share of revenue.
- Sellers: top sellers table with sparkline, seller state distribution, review score distribution.
- Chart quality rules: ECharts theme matching the design tokens, formatted axes and tooltips in BRL, legends, consistent colors per entity, loading skeletons, empty states, responsive resize, CSV and PNG export on every card, "Ask about this" button that opens chat with a prefilled question.
- Historical coverage: the full 2016 to 2018 range is available, with year selector and trailing 12 month view.

**Catalog (`/app/catalog`)**: searchable metrics and dimensions with definitions, synonyms, example questions, filtered by the user's policy.

**History and Saved**: searchable, filterable lists with rerun.

**Admin (admin role only)**
- Audit explorer: filters (user, role, route, decision, date, free text), detail drawer showing question, plan, both SQL versions, policy applied and hash status, CSV export, chain verification status badge.
- Users and roles: create user, assign role and region, category or seller scope, edit policies.
- Operations dashboard: charts from Phase 7 with a visible demo data badge for synthetic rows, provider budget gauges and the provider mode switch.
- Evaluation page: run history table, accuracy trend line by model and prompt version, per category breakdown, failure case viewer with expected versus generated SQL.

**Acceptance**: Playwright end to end tests cover login, each role asking the same question with different results, SQL toggle, dashboard filtering, admin audit search, and logout. No console errors. Core pages pass Lighthouse accessibility 90 or higher.

### Phase 10: Evaluation Harness With Dagster (6 days)

**Datasets and metrics**

| Suite | Size | Path under test | Metrics |
|---|---|---|---|
| Olist golden set v1 | 150 questions (easy, medium, hard, multi period, ambiguous, unanswerable) | Full product pipeline | Execution accuracy, semantic layer hit rate, zero call rate, SQL validity, clarification correctness, refusal correctness, average tokens per question, p95 latency |
| Permission and adversarial set | 60 cases | Full pipeline per role | Leakage rate (must be 0), correct denial rate, injection resistance |
| BIRD Mini-Dev | 500 questions (stratified sample of 150 for routine runs) | SQL fallback path with schema retrieval, evaluated on the provided SQLite databases | Execution accuracy, soft F1, by difficulty |
| Spider dev | 1,034 questions (stratified sample of 150 for routine runs) | Same as above | Execution accuracy, by difficulty |

- Execution accuracy compares result sets (order insensitive unless ORDER BY is required, numeric tolerance) between generated and gold SQL.
- For BIRD and Spider, run the same schema retrieval (embeddings plus pruned DDL and sample values) and the same prompt builder used in production, so the published numbers describe the real fallback path. State clearly in the README that these are raw text to SQL numbers without the semantic layer.
- Free tier constraint: the Groq model has a daily token cap, so full suites need chunking. Implement checkpoint and resume in the eval runner, a global rate limiter shared with the gateway, response caching keyed by (model, prompt version, question), and a `--limit` and `--stratified` option. Spread full BIRD and Spider runs over several days if needed.

**Dagster project**
- Assets: `olist_raw`, dbt assets (via dagster-dbt), `catalog_embeddings`, `eval_dataset_olist`, `eval_dataset_bird`, `eval_dataset_spider`, `eval_run` (partitioned by `model x prompt_version` using a multi partition definition), `eval_report`.
- Each run writes to `eval_runs` and `eval_results` (per question: generated plan, SQL, correctness, tokens, latency, error class) and a JSON summary `evals/results/<run_id>.json`.
- Sensors or schedule: nightly small stratified run for regression. Manual full run through the Dagster UI.
- Regression gate in CI using the cached small suite: fail if Olist execution accuracy drops by more than 3 points versus the stored baseline or if leakage is above 0.
- Error taxonomy for failures: wrong metric, wrong dimension, wrong filter, wrong period, wrong join, syntax, policy denial mismatch, timeout. Show counts in the Evaluation page.
- Script `scripts/publish_results.py` converts the latest summary to a Markdown table and a Benchmarks page JSON, and updates the README results block between marker comments.

**Acceptance**: a prompt change and a model switch each produce a new tracked run visible in Dagster and in the Evaluation page. README contains real measured numbers with run date, model, prompt version and sample size.

### Phase 11: Quality, Security Review And Performance (4 days)

**Tasks**
- Raise backend coverage to at least 80 percent. Add load test with Locust or k6 (free) against cached and uncached paths.
- Run the security checklist: OWASP ASVS level 1 items relevant to this app, dependency and container scans, secrets scan, RLS bypass attempts, token handling review.
- Add database indexes based on `EXPLAIN` of dashboard and audit queries. Add pagination everywhere.
- Frontend performance: route level code splitting, image optimization, ECharts tree shaking, font subsetting.
- Add observability basics: request id propagation, structured logs, `/metrics` Prometheus endpoint (optional Grafana in compose).
- Backup and restore scripts for the database.

**Acceptance**: no high or critical findings open. All CI gates green. Dashboard and chat meet the latency targets in Phases 5 and 7.

### Phase 12: Documentation, Demo And Release (3 days)

**README.md requirements (mandatory, professional, no marketing exaggeration)**
1. Title, one paragraph summary, badges (CI, license, Python, Node).
2. Hero GIF or screenshots of chat, SQL panel, dashboard and audit view.
3. Features list grouped by Governance, Analytics, Evaluation, Platform.
4. Architecture: Mermaid diagram of the request flow and a component diagram. Short explanation of the token minimization ladder.
5. Tech stack table.
6. Quick start in five commands or fewer: clone, copy `.env.example`, add free API keys (links to Groq and Google AI Studio), `make up`, `make data seed`. Include expected output and URLs.
7. Dataset section: sources, licenses, how to download, how to reload, sample mode.
8. Demo accounts table (role, email, what to try, example questions).
9. Configuration reference: environment variables, provider switching, rate limit settings.
10. Evaluation: how to run, how results are computed, **results table with real numbers** (suite, model, prompt version, sample size, execution accuracy, tokens per question, date), known limitations and failure categories.
11. Security model summary with a link to `docs/security.md`.
12. Project structure, API reference link (`/docs`), testing commands, troubleshooting, contribution notes, license, dataset attribution, roadmap.

**Other docs**: `docs/architecture.md`, `docs/semantic_layer.md` (how to add a metric), `docs/evaluation.md`, `docs/security.md`, `docs/runbook.md`, dbt docs site, CHANGELOG.

**Release tasks**: record a 3 to 5 minute demo walkthrough script (questions per role, a denied query, SQL inspection, dashboard drill down, audit review, evaluation run). Tag `v1.0.0`.

**Acceptance**: a new developer can clone the repository and reach a working demo using only the README. The demo script runs without manual fixes.

---

## 7. Golden Set Authoring Guide (used in Phases 2, 5, 10)

- Author 150 questions across: single metric, metric by dimension, time series, top N, ratio metrics, filters by state and category, period comparison, multi step comparisons (fallback), ambiguous questions needing clarification, unanswerable questions (not in data), policy sensitive questions.
- Each record: `id, question, role, difficulty, expected_route, expected_plan, gold_sql, expected_outcome (answer, clarify, refuse), notes`.
- Gold SQL is written by hand against `analytics` marts and reviewed. Store expected result checksums to detect data drift.
- Reuse about 40 verified items as retrieval few shot examples, and keep them disjoint from the evaluation items to avoid contamination.

---

## 8. Definition Of Done (project level)

- All phase acceptance criteria met and CI green.
- Demo runs end to end for all six roles with correct, different results per role.
- Zero leakage across permission and adversarial suites.
- Typical question path uses zero or one LLM call and stays within the token budgets in section 4.2.
- Dashboards show 2016 to 2018 history with professional, consistent charts and exports.
- README contains architecture, dataset instructions and published accuracy numbers.
- No em dash character, no unprofessional wording and no assistant or tool authorship references anywhere in the repository.
