"""Dashboard service: runs the dashboard queries through the policy engine and shapes the payloads."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.auth.service import CurrentUser
from app.dashboard import queries as q
from app.dashboard.queries import Filters
from app.pipeline import executor, sql_guard
from app.pipeline.orchestrator import Services
from app.policy.engine import EffectivePolicy, PolicyDenied
from app.policy.rls import rls_settings
from app.semantic.time_parser import add_months

CACHE_SECONDS = 300.0
CACHE_ENTRIES = 256
DASHBOARD_MAX_ROWS = 5000
MOVING_AVERAGE_MONTHS = 3
SPARKLINE_MONTHS = 12


class SectionUnavailable(Exception):
    """A dashboard section needs a table that the user's role cannot read."""


@dataclass(frozen=True)
class CacheEntry:
    stored_at: float
    body: dict[str, Any]
    etag: str


class ResponseCache:
    """Small in process cache keyed by endpoint, filters and the user's policy hash."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._entries: dict[str, CacheEntry] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> CacheEntry | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None or self._clock() - entry.stored_at > CACHE_SECONDS:
                self._entries.pop(key, None)
                return None
            return entry

    def put(self, key: str, body: dict[str, Any]) -> CacheEntry:
        etag = hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()[
            :32
        ]
        entry = CacheEntry(stored_at=self._clock(), body=body, etag=etag)
        with self._lock:
            if len(self._entries) >= CACHE_ENTRIES:
                self._entries.pop(next(iter(self._entries)))
            self._entries[key] = entry
        return entry


CACHE = ResponseCache()


def default_filters(as_of: dt.date) -> Filters:
    """Trailing twelve months ending with the reference month (data_as_of)."""
    end = add_months(as_of.replace(day=1), 1)
    start = add_months(as_of.replace(day=1), -11)
    return Filters(start=start, end=end)


def _num(value: Any) -> float:
    return float(value) if value is not None else 0.0


def _delta(current: float, previous: float | None) -> float | None:
    if previous is None or previous == 0:
        return None
    return round((current - previous) / previous * 100, 2)


class DashboardService:
    def __init__(self, services: Services, policy: EffectivePolicy, as_of: dt.date) -> None:
        self._s = services
        self._policy = policy
        self._as_of = as_of
        self._filters = rls_settings(policy)

    # ---- query execution -------------------------------------------------------------------------

    def run(self, sql: str) -> list[dict[str, Any]]:
        try:
            rewrite = sql_guard.validate_and_rewrite(
                sql, self._policy, self._s.columns.columns_for, DASHBOARD_MAX_ROWS
            )
        except PolicyDenied as denied:
            raise SectionUnavailable(denied.reason) from denied
        result = executor.execute(
            self._s.executor_engine, rewrite.sql, DASHBOARD_MAX_ROWS, self._filters
        )
        return [dict(zip(result.columns, row, strict=True)) for row in result.rows]

    def section(self, build: Callable[[], Any], fallback: Any) -> dict[str, Any]:
        try:
            return {"available": True, "data": build()}
        except SectionUnavailable as error:
            return {
                "available": False,
                "reason": error.args[0] if error.args else "not available",
                "data": fallback,
            }

    # ---- overview ------------------------------------------------------------------------------------

    def overview(self, f: Filters) -> dict[str, Any]:
        window = q.comparison_window(f)
        current = self.run(q.kpi_totals(f, f.start, f.end))[0]
        previous = self.run(q.kpi_totals(f, *window))[0] if window else None
        revenue = _num(current["revenue"])
        orders = _num(current["orders"])
        customers = _num(current["customers"])
        aov = revenue / orders if orders else 0.0
        prev_revenue = _num(previous["revenue"]) if previous else None
        prev_orders = _num(previous["orders"]) if previous else None
        prev_customers = _num(previous["customers"]) if previous else None
        prev_aov = prev_revenue / prev_orders if prev_revenue is not None and prev_orders else None

        series = self.run(q.monthly_revenue(f, self._history_start(f), f.end))
        trend = self._trend(series, f.start)
        sparkline = [point["revenue"] for point in trend][-SPARKLINE_MONTHS:]

        quality = self.section(lambda: self.run(q.order_quality(f, f.start, f.end))[0], {})
        on_time = None
        review = None
        if quality["available"] and quality["data"]:
            delivered = _num(quality["data"].get("delivered"))
            late = _num(quality["data"].get("late"))
            on_time = round((delivered - late) / delivered, 4) if delivered else None
            review = (
                _num(quality["data"].get("avg_review"))
                if quality["data"].get("avg_review") is not None
                else None
            )

        kpis = {
            "revenue": {
                "value": round(revenue, 2),
                "previous": prev_revenue,
                "delta_pct": _delta(revenue, prev_revenue),
                "sparkline": sparkline,
            },
            "orders": {
                "value": int(orders),
                "previous": prev_orders,
                "delta_pct": _delta(orders, prev_orders),
            },
            "aov": {
                "value": round(aov, 2),
                "previous": prev_aov,
                "delta_pct": _delta(aov, prev_aov),
            },
            "unique_customers": {
                "value": int(customers),
                "previous": prev_customers,
                "delta_pct": _delta(customers, prev_customers),
            },
            "on_time_delivery_rate": {"value": on_time, "available": quality["available"]},
            "avg_review_score": {
                "value": round(review, 3) if review is not None else None,
                "available": quality["available"],
            },
        }
        return {
            "period": {
                "start": f.start.isoformat(),
                "end": f.end.isoformat(),
                "compare": f.compare,
            },
            "filters": {"state": f.state, "category": f.category},
            "kpis": kpis,
            "revenue_trend": trend,
            "revenue_by_category": self.section(lambda: self.run(q.revenue_by_category(f)), []),
            "revenue_by_state": self.section(lambda: self.run(q.revenue_by_state(f)), []),
            "payment_mix": self.section(lambda: self.run(q.payment_mix(f)), []),
            "order_status_funnel": self.section(lambda: self.run(q.order_status(f)), []),
        }

    def _history_start(self, f: Filters) -> dt.date:
        return add_months(f.start, -14)

    def _trend(self, series: list[dict[str, Any]], start: dt.date) -> list[dict[str, Any]]:
        values = {row["month"]: _num(row["revenue"]) for row in series}
        months = sorted(values)
        result: list[dict[str, Any]] = []
        for index, month in enumerate(months):
            if month < start:
                continue
            revenue = values[month]
            previous_month = values[months[index - 1]] if index >= 1 else None
            same_last_year = values.get(add_months(month, -12))
            window = [
                values[m] for m in months[max(0, index - MOVING_AVERAGE_MONTHS + 1) : index + 1]
            ]
            result.append(
                {
                    "month": month.isoformat(),
                    "revenue": round(revenue, 2),
                    "mom_pct": _delta(revenue, previous_month),
                    "yoy_pct": _delta(revenue, same_last_year),
                    "moving_average_3m": round(sum(window) / len(window), 2),
                }
            )
        return result

    # ---- sales --------------------------------------------------------------------------------------

    def sales(self, f: Filters) -> dict[str, Any]:
        series = self.run(q.monthly_revenue(f, f.start, f.end))
        window = q.comparison_window(f)
        growth: list[dict[str, Any]] = []
        if window:
            now = {
                row["category"]: _num(row["revenue"])
                for row in self.run(q.category_window_totals(f, f.start, f.end))
            }
            before = {
                row["category"]: _num(row["revenue"])
                for row in self.run(q.category_window_totals(f, *window))
            }
            for category in sorted(
                set(now) | set(before), key=lambda name: now.get(name, 0.0), reverse=True
            ):
                growth.append(
                    {
                        "category": category,
                        "revenue": round(now.get(category, 0.0), 2),
                        "previous": round(before.get(category, 0.0), 2),
                        "growth_pct": _delta(now.get(category, 0.0), before.get(category)),
                    }
                )
        return {
            "monthly": [
                {
                    "month": row["month"].isoformat(),
                    "revenue": round(_num(row["revenue"]), 2),
                    "orders": int(row["orders"]),
                }
                for row in series
            ],
            "weekday_hour_heatmap": [
                {
                    "weekday": int(row["weekday"]),
                    "hour": int(row["hour"]),
                    "orders": int(row["orders"]),
                    "revenue": round(_num(row["revenue"]), 2),
                }
                for row in self.run(q.weekday_hour(f))
            ],
            "category_growth": growth,
            "top_products": [
                {
                    "product_id": row["product_id"],
                    "category": row["category"],
                    "revenue": round(_num(row["revenue"]), 2),
                    "items": int(row["items"]),
                }
                for row in self.run(q.top_products(f))
            ],
        }

    # ---- customers --------------------------------------------------------------------------------

    def customers(self, f: Filters) -> dict[str, Any]:
        return {
            "new_vs_repeat": [
                {
                    "month": row["month"].isoformat(),
                    "new": int(row["new_customers"] or 0),
                    "repeat": int(row["repeat_customers"] or 0),
                }
                for row in self.run(q.new_vs_repeat(f))
            ],
            "cohort_retention": self.section(
                lambda: [
                    {
                        "cohort_month": row["cohort_month"].isoformat(),
                        "months_since": int(row["months_since_cohort"]),
                        "cohort_size": int(row["cohort_size"]),
                        "retention_rate": float(row["retention_rate"] or 0),
                    }
                    for row in self.run(q.cohort_matrix(f))
                ],
                [],
            ),
            "geography": [
                {
                    "state": row["state"],
                    "customers": int(row["customers"]),
                    "orders": int(row["orders"]),
                    "revenue": round(_num(row["revenue"]), 2),
                }
                for row in self.run(q.geography(f))
            ],
        }

    # ---- logistics --------------------------------------------------------------------------------

    def logistics(self, f: Filters) -> dict[str, Any]:
        freight = self.run(q.freight_share(f))[0]
        revenue = _num(freight["revenue"])
        return {
            "delivery_days_distribution": [
                {"days": int(row["days"]), "orders": int(row["orders"])}
                for row in self.run(q.delivery_days_distribution(f))
            ],
            "estimated_vs_actual": [
                {
                    "month": row["month"].isoformat(),
                    "actual_days": _num(row["actual_days"]),
                    "estimated_days": _num(row["estimated_days"]),
                    "late_rate": _num(row["late_rate"]),
                }
                for row in self.run(q.delivery_monthly(f))
            ],
            "late_rate_by_state": [
                {
                    "state": row["state"],
                    "late_rate": _num(row["late_rate"]),
                    "delivered": int(row["delivered"]),
                }
                for row in self.run(q.late_by_state(f))
            ],
            "freight_share_of_revenue": round(_num(freight["freight"]) / revenue, 4)
            if revenue
            else None,
        }

    # ---- sellers ----------------------------------------------------------------------------------

    def sellers(self, f: Filters) -> dict[str, Any]:
        top = self.run(q.top_sellers(f))
        ids = [str(row["seller_id"]) for row in top]
        monthly: dict[str, list[float]] = {}
        if ids:
            for row in self.run(q.seller_monthly(f, ids)):
                monthly.setdefault(str(row["seller_id"]), []).append(_num(row["revenue"]))
        return {
            "top_sellers": [
                {
                    "seller_id": row["seller_id"],
                    "seller_state": row["seller_state"],
                    "revenue": round(_num(row["revenue"]), 2),
                    "orders": int(row["orders"]),
                    "avg_review": _num(row["avg_review"])
                    if row["avg_review"] is not None
                    else None,
                    "sparkline": [
                        round(value, 2) for value in monthly.get(str(row["seller_id"]), [])
                    ],
                }
                for row in top
            ],
            "seller_state_distribution": [
                {
                    "state": row["state"],
                    "sellers": int(row["sellers"]),
                    "revenue": round(_num(row["revenue"]), 2),
                }
                for row in self.run(q.seller_state_distribution(f))
            ],
            "review_score_distribution": [
                {"score": int(row["score"]), "orders": int(row["orders"])}
                for row in self.run(q.review_distribution(f))
            ],
        }


def cached(
    key_parts: tuple[object, ...],
    user: CurrentUser,
    policy: EffectivePolicy,
    build: Callable[[], dict[str, Any]],
) -> CacheEntry:
    key = "|".join(str(part) for part in (*key_parts, policy.policy_hash, user.role))
    entry = CACHE.get(key)
    if entry is None:
        entry = CACHE.put(key, build())
    return entry
