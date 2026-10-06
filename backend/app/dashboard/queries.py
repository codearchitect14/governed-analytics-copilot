"""SQL for the business dashboards. Each builder returns one statement over analytics marts.

Every statement is validated and row filtered by the same guard as chat answers, so a dashboard
can never show more than the user's policy allows. Inputs are validated by Filters before use,
and literals are rendered with the compiler's quoting.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import Literal

from app.semantic.compiler import render_value

Compare = Literal["none", "previous", "yoy"]
STATE = re.compile(r"^[A-Z]{2}$")
CATEGORY = re.compile(r"^[a-z][a-z_]{1,59}$")
MAX_RANGE_MONTHS = 36


class FilterError(ValueError):
    """A dashboard filter failed validation. The message is safe to return to the user."""


@dataclass(frozen=True)
class Filters:
    start: dt.date
    end: dt.date  # exclusive
    state: str | None = None
    category: str | None = None
    compare: Compare = "none"

    def __post_init__(self) -> None:
        if self.end <= self.start:
            raise FilterError("end must be after start")
        months = (self.end.year - self.start.year) * 12 + self.end.month - self.start.month
        if months > MAX_RANGE_MONTHS:
            raise FilterError(f"the range can be at most {MAX_RANGE_MONTHS} months")
        if self.state is not None and not STATE.match(self.state):
            raise FilterError("state must be a two letter Brazilian state code, for example SP")
        if self.category is not None and not CATEGORY.match(self.category):
            raise FilterError("category must be an English category name in lower case")


def quote(value: str) -> str:
    return str(render_value(value))


def _period_clause(column: str, start: dt.date, end: dt.date) -> str:
    return f"{column} >= {quote(start.isoformat())} AND {column} < {quote(end.isoformat())}"


def _items_where(f: Filters, start: dt.date, end: dt.date) -> str:
    clauses = [_period_clause("purchased_at", start, end), "NOT coalesce(is_canceled, false)"]
    if f.state:
        clauses.append(f"customer_state = {quote(f.state)}")
    if f.category:
        clauses.append(f"product_category_en = {quote(f.category)}")
    return " AND ".join(clauses)


def _orders_where(f: Filters, start: dt.date, end: dt.date) -> str:
    clauses = [_period_clause("purchased_at", start, end), "NOT coalesce(is_canceled, false)"]
    if f.state:
        clauses.append(f"customer_state = {quote(f.state)}")
    return " AND ".join(clauses)


def months_before(day: dt.date, months: int) -> dt.date:
    index = day.year * 12 + (day.month - 1) - months
    return dt.date(index // 12, index % 12 + 1, 1)


def comparison_window(f: Filters) -> tuple[dt.date, dt.date] | None:
    if f.compare == "none":
        return None
    if f.compare == "previous":
        length = (f.end - f.start).days
        return f.start - dt.timedelta(days=length), f.start
    return months_before(f.start, 12), months_before(f.end, 12)


def kpi_totals(f: Filters, start: dt.date, end: dt.date) -> str:
    return (
        "SELECT sum(line_revenue) AS revenue, count(distinct order_id) AS orders, "
        "count(distinct customer_unique_id) AS customers "
        f"FROM analytics.fct_order_items WHERE {_items_where(f, start, end)}"
    )


def order_quality(f: Filters, start: dt.date, end: dt.date) -> str:
    return (
        "SELECT count(delivery_days) AS delivered, sum(case when is_late then 1 else 0 end) AS late, "
        "avg(review_score)::numeric(10, 3) AS avg_review "
        f"FROM analytics.fct_orders WHERE {_orders_where(f, start, end)}"
    )


def monthly_revenue(f: Filters, start: dt.date, end: dt.date) -> str:
    return (
        "SELECT cast(date_trunc('month', purchased_at) AS date) AS month, "
        "sum(line_revenue) AS revenue, count(distinct order_id) AS orders "
        f"FROM analytics.fct_order_items WHERE {_items_where(f, start, end)} GROUP BY 1 ORDER BY 1"
    )


def revenue_by_category(f: Filters) -> str:
    return (
        "SELECT product_category_en AS category, sum(line_revenue) AS revenue, "
        "count(distinct order_id) AS orders "
        f"FROM analytics.fct_order_items WHERE {_items_where(f, f.start, f.end)} GROUP BY 1 ORDER BY 2 DESC"
    )


def revenue_by_state(f: Filters) -> str:
    clauses = [_period_clause("purchased_at", f.start, f.end), "NOT coalesce(is_canceled, false)"]
    if f.category:
        clauses.append(f"product_category_en = {quote(f.category)}")
    return (
        "SELECT customer_state AS state, sum(line_revenue) AS revenue, count(distinct order_id) AS orders, "
        "count(distinct customer_unique_id) AS customers "
        f"FROM analytics.fct_order_items WHERE {' AND '.join(clauses)} GROUP BY 1 ORDER BY 2 DESC"
    )


def payment_mix(f: Filters) -> str:
    return (
        "SELECT payment_type_primary AS payment_type, count(*) AS orders, sum(payment_total) AS value "
        f"FROM analytics.fct_orders WHERE {_orders_where(f, f.start, f.end)} GROUP BY 1 ORDER BY 2 DESC"
    )


def order_status(f: Filters) -> str:
    clauses = [_period_clause("purchased_at", f.start, f.end)]
    if f.state:
        clauses.append(f"customer_state = {quote(f.state)}")
    return (
        "SELECT order_status AS status, count(*) AS orders "
        f"FROM analytics.fct_orders WHERE {' AND '.join(clauses)} GROUP BY 1 ORDER BY 2 DESC"
    )


def weekday_hour(f: Filters) -> str:
    return (
        "SELECT extract(isodow FROM purchased_at)::int AS weekday, extract(hour FROM purchased_at)::int AS hour, "
        "count(distinct order_id) AS orders, sum(line_revenue) AS revenue "
        f"FROM analytics.fct_order_items WHERE {_items_where(f, f.start, f.end)} GROUP BY 1, 2"
    )


def category_window_totals(f: Filters, start: dt.date, end: dt.date) -> str:
    return (
        "SELECT product_category_en AS category, sum(line_revenue) AS revenue "
        f"FROM analytics.fct_order_items WHERE {_items_where(f, start, end)} GROUP BY 1"
    )


def top_products(f: Filters, limit: int = 10) -> str:
    return (
        "SELECT product_id, product_category_en AS category, sum(line_revenue) AS revenue, "
        "count(*) AS items "
        f"FROM analytics.fct_order_items WHERE {_items_where(f, f.start, f.end)} "
        f"GROUP BY 1, 2 ORDER BY 3 DESC LIMIT {int(limit)}"
    )


def new_vs_repeat(f: Filters) -> str:
    return (
        "SELECT cast(date_trunc('month', purchased_at) AS date) AS month, "
        "sum(case when customer_order_seq = 1 then 1 else 0 end) AS new_customers, "
        "sum(case when customer_order_seq > 1 then 1 else 0 end) AS repeat_customers "
        f"FROM analytics.fct_orders WHERE {_orders_where(f, f.start, f.end)} GROUP BY 1 ORDER BY 1"
    )


def cohort_matrix(f: Filters) -> str:
    return (
        "SELECT cohort_month, months_since_cohort, cohort_size, active_customers, retention_rate "
        "FROM analytics.agg_cohort_retention "
        f"WHERE {_period_clause('cohort_month', f.start, f.end)} ORDER BY 1, 2"
    )


def geography(f: Filters) -> str:
    return (
        "SELECT customer_state AS state, count(distinct customer_unique_id) AS customers, "
        "count(distinct order_id) AS orders, sum(line_revenue) AS revenue "
        f"FROM analytics.fct_order_items WHERE {_items_where(f, f.start, f.end)} GROUP BY 1 ORDER BY 4 DESC"
    )


def delivery_days_distribution(f: Filters) -> str:
    return (
        "SELECT delivery_days AS days, count(*) AS orders "
        f"FROM analytics.fct_orders WHERE delivery_days IS NOT NULL AND {_orders_where(f, f.start, f.end)} "
        "GROUP BY 1 ORDER BY 1"
    )


def delivery_monthly(f: Filters) -> str:
    return (
        "SELECT cast(date_trunc('month', purchased_at) AS date) AS month, "
        "avg(delivery_days)::numeric(10, 2) AS actual_days, "
        "avg(estimated_delivery_at::date - purchase_date_key)::numeric(10, 2) AS estimated_days, "
        "avg(case when is_late then 1.0 else 0.0 end)::numeric(6, 4) AS late_rate "
        f"FROM analytics.fct_orders WHERE delivery_days IS NOT NULL AND {_orders_where(f, f.start, f.end)} "
        "GROUP BY 1 ORDER BY 1"
    )


def late_by_state(f: Filters) -> str:
    return (
        "SELECT customer_state AS state, avg(case when is_late then 1.0 else 0.0 end)::numeric(6, 4) AS late_rate, "
        "count(delivery_days) AS delivered "
        f"FROM analytics.fct_orders WHERE delivery_days IS NOT NULL AND {_orders_where(f, f.start, f.end)} "
        "GROUP BY 1 ORDER BY 1"
    )


def freight_share(f: Filters) -> str:
    return (
        "SELECT sum(line_freight) AS freight, sum(line_revenue) AS revenue "
        f"FROM analytics.fct_order_items WHERE {_items_where(f, f.start, f.end)}"
    )


def top_sellers(f: Filters, limit: int = 10) -> str:
    return (
        "SELECT seller_id, max(seller_state) AS seller_state, sum(line_revenue) AS revenue, "
        "count(distinct order_id) AS orders, avg(review_score)::numeric(10, 3) AS avg_review "
        f"FROM analytics.fct_order_items WHERE {_items_where(f, f.start, f.end)} "
        f"GROUP BY 1 ORDER BY 3 DESC LIMIT {int(limit)}"
    )


def seller_monthly(f: Filters, seller_ids: list[str]) -> str:
    if not seller_ids:
        seller_ids = [""]
    values = ", ".join(quote(value) for value in seller_ids)
    return (
        "SELECT seller_id, cast(date_trunc('month', purchased_at) AS date) AS month, sum(line_revenue) AS revenue "
        f"FROM analytics.fct_order_items WHERE {_items_where(f, f.start, f.end)} AND seller_id IN ({values}) "
        "GROUP BY 1, 2 ORDER BY 1, 2"
    )


def seller_state_distribution(f: Filters) -> str:
    return (
        "SELECT seller_state AS state, count(distinct seller_id) AS sellers, sum(line_revenue) AS revenue "
        f"FROM analytics.fct_order_items WHERE {_items_where(f, f.start, f.end)} GROUP BY 1 ORDER BY 3 DESC"
    )


def review_distribution(f: Filters) -> str:
    return (
        "SELECT review_score AS score, count(*) AS orders "
        f"FROM analytics.fct_orders WHERE review_score IS NOT NULL AND {_orders_where(f, f.start, f.end)} "
        "GROUP BY 1 ORDER BY 1"
    )
