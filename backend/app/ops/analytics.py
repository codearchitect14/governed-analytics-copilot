"""Operations figures for the admin dashboard. Synthetic (demo) rows are counted and reported."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Engine, text

from app.llm.gateway import LLMGateway

LLM_ROUTES = ("llm_plan", "llm_sql")
CACHE_ROUTES = ("cache", "semantic_cache")
WINDOW = "event = 'query' AND ts >= now() - make_interval(days => :days)"


def _rows(engine: Engine, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    with engine.connect() as connection:
        return [dict(row) for row in connection.execute(text(sql), params).mappings()]


def _totals(engine: Engine, params: dict[str, Any]) -> dict[str, Any]:
    return _rows(
        engine,
        f"""
        SELECT count(*) AS requests,
               sum(case when decision = 'allowed' then 1 else 0 end) AS allowed,
               sum(case when decision = 'denied' then 1 else 0 end) AS denied,
               sum(case when decision = 'error' then 1 else 0 end) AS errors,
               sum(case when decision = 'clarify' then 1 else 0 end) AS clarify,
               sum(case when is_synthetic then 1 else 0 end) AS synthetic_rows,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY total_ms) AS latency_p50_ms,
               percentile_cont(0.95) WITHIN GROUP (ORDER BY total_ms) AS latency_p95_ms
        FROM app.audit_log WHERE {WINDOW}
        """,
        params,
    )[0]


def summary(engine: Engine, days: int, gateway: LLMGateway | None) -> dict[str, Any]:
    params = {"days": days}
    totals = _totals(engine, params)
    per_day = _rows(
        engine,
        f"""
        SELECT cast(date_trunc('day', ts) AS date) AS day, count(*) AS requests,
               sum(case when decision = 'allowed' then 1 else 0 end) AS allowed,
               sum(case when decision in ('denied', 'error') then 1 else 0 end) AS failed
        FROM app.audit_log WHERE {WINDOW} GROUP BY 1 ORDER BY 1
        """,
        params,
    )
    route_mix = _rows(
        engine,
        f"""
        SELECT route, count(*) AS requests FROM app.audit_log
        WHERE {WINDOW} AND decision = 'allowed' GROUP BY 1 ORDER BY 2 DESC
        """,
        params,
    )
    failures = _rows(
        engine,
        f"""
        SELECT decision, coalesce(denial_reason, 'unspecified') AS reason, count(*) AS requests
        FROM app.audit_log WHERE {WINDOW} AND decision IN ('denied', 'error')
        GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 10
        """,
        params,
    )
    questions = _rows(
        engine,
        f"""
        SELECT normalized_question AS question, count(*) AS asked FROM app.audit_log
        WHERE {WINDOW} AND normalized_question IS NOT NULL
        GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 10
        """,
        params,
    )
    tokens = _rows(
        engine,
        """
        SELECT provider, is_synthetic, sum(requests) AS requests,
               sum(tokens_in) AS tokens_in, sum(tokens_out) AS tokens_out
        FROM app.llm_usage WHERE usage_date >= current_date - make_interval(days => :days)
        GROUP BY 1, 2 ORDER BY 1, 2
        """,
        params,
    )
    per_llm = _rows(
        engine,
        f"""
        SELECT avg(coalesce(tokens_in, 0) + coalesce(tokens_out, 0)) AS avg_tokens
        FROM app.audit_log WHERE {WINDOW} AND route IN ('llm_plan', 'llm_sql') AND decision = 'allowed'
        """,
        params,
    )

    requests = int(totals["requests"] or 0)
    allowed = int(totals["allowed"] or 0)
    denied = int(totals["denied"] or 0)
    cache_hits = sum(int(row["requests"]) for row in route_mix if row["route"] in CACHE_ROUTES)
    avg_llm_tokens = float(per_llm[0]["avg_tokens"] or 0.0)
    synthetic = int(totals["synthetic_rows"] or 0)
    return {
        "days": days,
        "requests": requests,
        "allowed": allowed,
        "denied": denied,
        "errors": int(totals["errors"] or 0),
        "clarify": int(totals["clarify"] or 0),
        "success_rate": round(allowed / requests, 4) if requests else None,
        "denial_rate": round(denied / requests, 4) if requests else None,
        "cache_hit_rate": round(cache_hits / allowed, 4) if allowed else None,
        "route_mix": [
            {"route": row["route"], "requests": int(row["requests"])} for row in route_mix
        ],
        "requests_per_day": [
            {
                "day": row["day"].isoformat(),
                "requests": int(row["requests"]),
                "allowed": int(row["allowed"] or 0),
                "failed": int(row["failed"] or 0),
            }
            for row in per_day
        ],
        "latency_ms": {
            "p50": round(float(totals["latency_p50_ms"]), 1)
            if totals["latency_p50_ms"] is not None
            else None,
            "p95": round(float(totals["latency_p95_ms"]), 1)
            if totals["latency_p95_ms"] is not None
            else None,
        },
        "failure_categories": [
            {"decision": row["decision"], "reason": row["reason"], "requests": int(row["requests"])}
            for row in failures
        ],
        "most_asked": [
            {"question": row["question"], "asked": int(row["asked"])} for row in questions
        ],
        "tokens_by_provider": [
            {
                "provider": row["provider"],
                "synthetic": bool(row["is_synthetic"]),
                "requests": int(row["requests"] or 0),
                "tokens_in": int(row["tokens_in"] or 0),
                "tokens_out": int(row["tokens_out"] or 0),
            }
            for row in tokens
        ],
        "tokens_saved_estimate": round(cache_hits * avg_llm_tokens),
        "provider_budgets": gateway.provider_status() if gateway is not None else [],
        "synthetic_rows": synthetic,
        "demo_data": synthetic > 0 or any(bool(row["is_synthetic"]) for row in tokens),
    }


def evaluation_runs(engine: Engine) -> list[dict[str, Any]]:
    return _rows(
        engine,
        """
        SELECT id::text AS id, suite, model, prompt_version, sample_size, status, metrics,
               cast(started_at AS text) AS started_at
        FROM app.eval_runs ORDER BY started_at DESC LIMIT 50
        """,
        {},
    )
