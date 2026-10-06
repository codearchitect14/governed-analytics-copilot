"""Backfill synthetic demo history for the operations dashboard.

Writes realistic daily patterns (weekday peaks, a gentle growth trend, varied latency) as audit rows
and usage counters flagged is_synthetic = true. Audit rows go through the same hash chain writer as
real requests, so the chain still verifies. Run once per environment:

    uv run --package governed-analytics-backend python -m app.ops.seed_history --days 90
"""

from __future__ import annotations

import argparse
import datetime as dt
import math
import random
import sys
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import Engine, text

from app.audit.writer import AuditEvent, append_event
from app.core.config import get_settings
from app.db.engine import get_engine

ISO_SATURDAY = 6
PROVIDERS = (("groq", "openai/gpt-oss-20b", 0.7), ("gemini", "gemini-2.5-flash", 0.3))
QUESTIONS = (
    "Revenue by month",
    "Orders by month",
    "Revenue by customer state",
    "Average order value by month",
    "Revenue by product category",
    "Unique customers by month",
    "Items sold by seller state",
    "On time delivery rate",
    "Cancellation rate",
    "Payment value by payment type",
)
DENIAL_REASONS = (
    "Your role cannot query: analytics.fct_orders",
    "Your role does not allow free form SQL questions.",
    "Outside the data available to you.",
)


@dataclass(frozen=True)
class Outcome:
    weight: float
    route: str
    decision: str


OUTCOMES: tuple[Outcome, ...] = (
    Outcome(0.45, "rule", "allowed"),
    Outcome(0.22, "cache", "allowed"),
    Outcome(0.08, "semantic_cache", "allowed"),
    Outcome(0.10, "llm_plan", "allowed"),
    Outcome(0.04, "llm_sql", "allowed"),
    Outcome(0.08, "rule", "denied"),
    Outcome(0.03, "none", "clarify"),
)


def _pick(rng: random.Random, outcomes: Sequence[Outcome]) -> Outcome:
    roll = rng.random() * sum(item.weight for item in outcomes)
    for item in outcomes:
        roll -= item.weight
        if roll <= 0:
            return item
    return outcomes[-1]


def _latency(rng: random.Random, route: str) -> int:
    if route in ("cache", "semantic_cache"):
        return int(rng.uniform(40, 220))
    if route in ("llm_plan", "llm_sql"):
        return int(rng.uniform(1400, 3600))
    return int(math.exp(rng.gauss(math.log(900), 0.45)))


def _daily_volume(
    rng: random.Random, day: dt.date, index_from_end: int, days: int, base: int
) -> int:
    weekend = 0.72 if day.isoweekday() >= ISO_SATURDAY else 1.0
    growth = 1.0 + 0.35 * (days - index_from_end) / days
    return max(1, int(base * weekend * growth * rng.uniform(0.85, 1.15)))


def existing_synthetic_rows(engine: Engine) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                text("SELECT count(*) FROM app.audit_log WHERE is_synthetic")
            ).scalar_one()
        )


def seed(
    engine: Engine, days: int = 90, base_per_day: int = 60, seed_value: int = 20260101
) -> dict[str, int]:
    rng = random.Random(seed_value)  # noqa: S311 - demo data, not security sensitive
    today = dt.datetime.now(dt.UTC).date()
    written = 0
    llm_tokens: dict[tuple[dt.date, str, str], list[int]] = {}
    for index_from_end in range(days):
        day = today - dt.timedelta(days=index_from_end)
        volume = _daily_volume(rng, day, index_from_end, days, base_per_day)
        with engine.begin() as connection:
            for _ in range(volume):
                outcome = _pick(rng, OUTCOMES)
                stamp = dt.datetime.combine(day, dt.time(), tzinfo=dt.UTC) + dt.timedelta(
                    seconds=rng.randint(0, 86399)
                )
                latency = _latency(rng, outcome.route)
                tokens_in = tokens_out = 0
                provider = model = None
                if outcome.route in ("llm_plan", "llm_sql"):
                    tokens_in, tokens_out = rng.randint(900, 1400), rng.randint(60, 220)
                    name, model_name, _share = (
                        PROVIDERS[0] if rng.random() < PROVIDERS[0][2] else PROVIDERS[1]
                    )
                    provider, model = name, model_name
                    bucket = llm_tokens.setdefault((day, provider, model), [0, 0, 0])
                    bucket[0] += 1
                    bucket[1] += tokens_in
                    bucket[2] += tokens_out
                question = rng.choice(QUESTIONS)
                denial = rng.choice(DENIAL_REASONS) if outcome.decision == "denied" else None
                append_event(
                    connection,
                    AuditEvent(
                        event="query",
                        decision=outcome.decision,  # type: ignore[arg-type]
                        question=question,
                        normalized_question=question.lower(),
                        route=outcome.route,
                        provider=provider,
                        model=model,
                        tokens_in=tokens_in,
                        tokens_out=tokens_out,
                        denial_reason=denial,
                        row_count=rng.randint(1, 40) if outcome.decision == "allowed" else None,
                        exec_ms=int(latency * 0.2) if outcome.decision == "allowed" else None,
                        total_ms=latency,
                        is_synthetic=True,
                        request_id=f"demo-{written}",
                    ),
                    now=stamp,
                )
                written += 1
        _write_usage(engine, day, llm_tokens)
        llm_tokens = {key: value for key, value in llm_tokens.items() if key[0] != day}
    return {"audit_rows": written, "days": days}


def _write_usage(
    engine: Engine, day: dt.date, buckets: dict[tuple[dt.date, str, str], list[int]]
) -> None:
    rows = [(key, value) for key, value in buckets.items() if key[0] == day]
    if not rows:
        return
    with engine.begin() as connection:
        for (usage_day, provider, model), (requests, tokens_in, tokens_out) in rows:
            connection.execute(
                text(
                    """
                    INSERT INTO app.llm_usage (usage_date, provider, model, requests, tokens_in, tokens_out, is_synthetic)
                    VALUES (:day, :provider, :model, :requests, :tokens_in, :tokens_out, TRUE)
                    ON CONFLICT (usage_date, provider, model, is_synthetic) DO UPDATE SET
                        requests = app.llm_usage.requests + EXCLUDED.requests,
                        tokens_in = app.llm_usage.tokens_in + EXCLUDED.tokens_in,
                        tokens_out = app.llm_usage.tokens_out + EXCLUDED.tokens_out
                    """
                ),
                {
                    "day": usage_day,
                    "provider": provider,
                    "model": model,
                    "requests": requests,
                    "tokens_in": tokens_in,
                    "tokens_out": tokens_out,
                },
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0] if __doc__ else "Seed demo history"
    )
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument(
        "--force", action="store_true", help="Add history even if synthetic rows already exist"
    )
    args = parser.parse_args(argv)
    settings = get_settings()
    if settings.app_env not in ("local", "test"):
        print("Demo history is seeded only in the local and test environments.", file=sys.stderr)
        return 2
    engine = get_engine(settings)
    if existing_synthetic_rows(engine) and not args.force:
        print("Synthetic history already exists. Use --force to add more.", file=sys.stderr)
        return 1
    result = seed(engine, days=args.days)
    print(f"Wrote {result['audit_rows']} synthetic audit rows over {result['days']} days.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
