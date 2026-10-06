# Security model and threat model

## Scope

Meridian Data Copilot answers business questions over governed analytics marts. This document lists
the assets, the actors, the controls that protect the data, and the residual risks.

## Assets

| Asset | Why it matters |
|---|---|
| Analytics marts and aggregates (`analytics`) | Business and customer level data (order, payment, delivery, seller) |
| Customer identifiers | Personal data. Masked for the analyst role |
| User accounts, password hashes, refresh tokens | Access to the application |
| Audit log | Evidence of who asked what and what was returned |
| Provider API keys | Cost and misuse if leaked |

## Actors

| Actor | Trust |
|---|---|
| Authenticated business users | Trusted to log in, untrusted with respect to what they ask |
| Administrators | Manage users and policies, have no data tables by default |
| Language model output | Untrusted input. Never executed without the guard |
| Question text | Untrusted data. Never an instruction source |
| Anonymous internet clients | Untrusted |

## Controls by layer

| Layer | Control | Where |
|---|---|---|
| Transport and session | Argon2id passwords, lockout after 5 failures for 15 minutes, 15 minute access tokens, rotating refresh tokens in an httpOnly, Secure, SameSite=Strict cookie, family revocation on reuse | `app/auth`, `app/core/security.py` |
| Route RBAC (layer 1) | Role dependencies on every admin route, denials audited | `app/auth/deps.py` |
| Policy engine (layer 2) | Per user allowed tables, row filter scopes, masked columns, row cap, `policy_hash` | `app/policy` |
| SQL guard (layer 3) | sqlglot parse, one SELECT or WITH, analytics relations only, forbidden functions blocked, no comments or stacked statements, no cross joins, row cap injected, row filters and masks injected as literals | `app/pipeline/sql_guard.py` |
| Row level security (layer 4) | Database policies on every mart and aggregate read the per transaction setting `app.user_filters`. Without a setting, or without an entry for the table, no row is visible | `warehouse/dbt_project/macros/grant_warehouse_ro.sql`, `app/policy/rls.py` |
| Database roles | `warehouse_ro` reads marts and aggregates only, has no write privilege, and has a 10 second statement timeout. Staging and intermediate views are not readable because views run with owner rights | Bootstrap and dbt post-run macro |
| Cost gate | EXPLAIN cost ceiling before execution | `app/pipeline/executor.py` |
| Audit | One append only, hash chained row per request, including denials and errors. Verified by `make verify-audit` | `app/audit` |
| Abuse limits | Rate limits on login and chat, CORS allow list, security headers | `app/core` |

Layer 4 means that even a defect in the SQL guard cannot return rows outside a user's scope.
`backend/tests/test_governance.py` checks this by running raw SQL through the executor with the
guard skipped.

## Tests that enforce the model

- `dataset/golden/permission_tests.jsonl` runs one question per role and scope. Results must contain
  only the values that role may see, and different roles must get different results.
- `dataset/golden/adversarial.jsonl` contains prompt injection, DDL, catalog access, sleep, file
  reads, comment hiding, stacked statements and out of scope requests. None may return rows.
- Penetration style checks cover stacked statements, catalog access, `set_config`, `COPY`,
  `pg_sleep`, `lo_export` and cross joins.
- Property based tests (hypothesis) generate query shapes with aliases, quoting, CTEs, subqueries,
  unions and comments, and check that every accepted statement is filtered.

## Prompt injection

The question is placed inside a delimited block in every model prompt. The system prompts state that
the question is data. Model output is parsed, validated against a Pydantic schema, and passed through
the SQL guard. A model that returns forbidden SQL is refused and audited, and it is never executed.

## Residual risks

- **Dataset license:** Olist is CC BY-NC-SA 4.0. The license must be checked before any public use.
- **Masking is by hash:** `md5` masks identifiers for display. It is not anonymisation, and values
  remain linkable across queries.
- **Row level security and table owners:** the dbt loader owns the marts and bypasses row level
  security, as table owners do. The loader role is for builds only and is not exposed to the API.
- **Single process rate limits:** rate limits and LLM budgets are kept in memory per process.
  Several API instances would need shared storage.
- **Demo credentials:** the documented demo accounts exist only in local and test environments.
  Production must set strong secrets and must not seed demo users.
- **Model quality:** wrong answers are possible. The audit trail records every plan and SQL so
  that answers can be reviewed.
- **Not yet covered:** an external penetration test, backup and restore drills, and dependency
  and image scans in CI (planned in Phase 11).
