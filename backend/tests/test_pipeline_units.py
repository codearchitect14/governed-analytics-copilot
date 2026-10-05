"""SQL guard, chart selection and explanations. No database needed."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from app.pipeline import charts, explain, sql_guard
from app.policy.definitions import ROLES
from app.policy.engine import EffectivePolicy, PolicyDenied, build_effective_policy

COLUMNS = {
    "analytics.fct_orders": [
        "order_id",
        "customer_id",
        "customer_unique_id",
        "customer_state",
        "items_total",
        "is_canceled",
        "purchased_at",
    ],
    "analytics.fct_order_items": [
        "order_item_key",
        "order_id",
        "order_item_id",
        "product_id",
        "seller_id",
        "seller_state",
        "customer_id",
        "customer_unique_id",
        "customer_state",
        "product_category_en",
        "order_status",
        "is_canceled",
        "purchased_at",
        "line_revenue",
        "line_freight",
        "line_gmv",
        "review_score",
        "delivered_customer_at",
        "delivery_days",
        "delay_days",
        "is_late",
        "shipping_limit_at",
        "category_translation_status",
    ],
    "analytics.dim_customers": [
        "customer_id",
        "customer_unique_id",
        "zip_code_prefix",
        "city",
        "state",
    ],
}


def columns_for(table: str) -> list[str]:
    return COLUMNS.get(table, [])


def policy_for(role: str, scopes: dict[str, object]) -> EffectivePolicy:
    definition = next(item for item in ROLES if item.name == role)
    return build_effective_policy(
        role=role, policy_version=1, policy=dict(definition.policy), scopes=scopes
    )


# ---- SQL guard: accepted queries ----------------------------------------------------------------


def test_simple_select_over_an_allowed_mart_is_accepted_and_limited() -> None:
    policy = policy_for("executive", {})

    result = sql_guard.validate_and_rewrite(
        "SELECT line_revenue FROM analytics.fct_order_items", policy, columns_for, max_rows=50
    )

    assert "LIMIT 50" in result.sql
    assert result.tables == ("analytics.fct_order_items",)
    assert result.filtered_tables == ()


def test_with_query_is_accepted() -> None:
    policy = policy_for("executive", {})
    sql = (
        "WITH totals AS (SELECT customer_state, SUM(line_revenue) AS revenue "
        "FROM analytics.fct_order_items GROUP BY customer_state) SELECT * FROM totals"
    )

    result = sql_guard.validate_and_rewrite(sql, policy, columns_for, max_rows=10)

    assert result.tables == ("analytics.fct_order_items",)


def test_row_filter_is_injected_as_a_predicate() -> None:
    policy = policy_for("regional_manager", {"regions": ["SP", "RJ"]})

    result = sql_guard.validate_and_rewrite(
        "SELECT customer_state, line_revenue FROM analytics.fct_order_items",
        policy,
        columns_for,
        max_rows=100,
    )

    assert "customer_state IN ('SP', 'RJ')" in result.sql
    assert result.filtered_tables == ("analytics.fct_order_items",)


def test_missing_scope_becomes_a_false_predicate() -> None:
    policy = policy_for("seller_partner", {})

    result = sql_guard.validate_and_rewrite(
        "SELECT line_revenue FROM analytics.fct_order_items", policy, columns_for, max_rows=100
    )

    assert "FALSE" in result.sql.upper()


def test_masked_columns_are_hashed_in_the_rewrite() -> None:
    policy = policy_for("analyst", {})

    result = sql_guard.validate_and_rewrite(
        "SELECT customer_unique_id, order_id FROM analytics.fct_orders",
        policy,
        columns_for,
        max_rows=100,
    )

    assert "MD5(customer_unique_id) AS customer_unique_id" in result.sql
    assert "order_id" in result.sql.lower()
    assert any("customer_unique_id" in item for item in result.masked)


def test_alias_is_kept_so_outer_references_still_resolve() -> None:
    policy = policy_for("regional_manager", {"regions": ["SP"]})
    sql = (
        "SELECT o.customer_state, COUNT(*) FROM analytics.fct_orders AS o GROUP BY o.customer_state"
    )

    result = sql_guard.validate_and_rewrite(sql, policy, columns_for, max_rows=100)

    assert "AS o" in result.sql
    assert "o.customer_state" in result.sql


def test_values_with_quotes_are_escaped_not_concatenated() -> None:
    policy = policy_for("regional_manager", {"regions": ["S'P"]})

    result = sql_guard.validate_and_rewrite(
        "SELECT customer_state FROM analytics.fct_orders", policy, columns_for, max_rows=10
    )

    assert "'S''P'" in result.sql


# ---- SQL guard: rejected queries ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("sql", "rule"),
    [
        ("DROP TABLE analytics.fct_orders", "statement_type"),
        ("DELETE FROM analytics.fct_orders", "statement_type"),
        ("SELECT 1; SELECT 2", "text"),
        ("SELECT 1 -- hidden", "text"),
        ("SELECT pg_sleep(10)", "function"),
        ("SELECT dblink('x', 'select 1')", "function"),
        ("SELECT * FROM information_schema.tables", "relation"),
        ("SELECT * FROM pg_catalog.pg_user", "relation"),
        ("SELECT * FROM public.users", "relation"),
        ("SELECT * FROM app.users", "relation"),
        ("SELECT * FROM analytics.fct_orders a CROSS JOIN analytics.fct_orders b", "cross_join"),
        ("SELECT * FROM generate_series(1, 1000000)", "relation"),
        ("", "empty"),
    ],
)
def test_dangerous_queries_are_rejected(sql: str, rule: str) -> None:
    policy = policy_for("executive", {})

    with pytest.raises(sql_guard.SqlRejected) as rejected:
        sql_guard.validate_and_rewrite(sql, policy, columns_for, max_rows=10)

    assert rejected.value.rule == rule


def test_admin_role_cannot_read_any_table() -> None:
    policy = policy_for("admin", {})

    with pytest.raises(PolicyDenied):
        sql_guard.validate_and_rewrite(
            "SELECT 1 FROM analytics.fct_orders", policy, columns_for, max_rows=10
        )


def test_category_manager_cannot_query_the_orders_mart() -> None:
    policy = policy_for("category_manager", {"categories": ["bed_bath_table"]})

    with pytest.raises(PolicyDenied) as denied:
        sql_guard.validate_and_rewrite(
            "SELECT customer_state FROM analytics.fct_orders", policy, columns_for, max_rows=10
        )

    assert "analytics.fct_orders" in denied.value.tables


def test_row_cap_lowers_an_existing_larger_limit() -> None:
    policy = policy_for("executive", {})

    result = sql_guard.validate_and_rewrite(
        "SELECT line_revenue FROM analytics.fct_order_items LIMIT 99999",
        policy,
        columns_for,
        max_rows=20,
    )

    assert "LIMIT 20" in result.sql


# ---- charts -------------------------------------------------------------------------------------


def test_single_value_is_a_kpi() -> None:
    assert charts.select_chart(["revenue"], [[1234.5]])["type"] == "kpi"


def test_time_series_is_a_line_chart() -> None:
    rows = [[dt.date(2017, 1, 1), 10.0], [dt.date(2017, 2, 1), 12.0]]

    chart = charts.select_chart(["metric_time__month", "revenue"], rows)

    assert chart["type"] == "line"
    assert chart["option"]["xAxis"]["data"] == ["2017-01-01", "2017-02-01"]


def test_category_ranking_is_a_bar_chart() -> None:
    assert charts.select_chart(["state", "revenue"], [["SP", 5.0], ["RJ", 3.0]])["type"] == "bar"


def test_two_categories_are_a_grouped_bar() -> None:
    rows = [["2017-01-01", "SP", 5.0], ["2017-01-01", "RJ", 3.0]]

    assert charts.select_chart(["month", "state", "revenue"], rows)["type"] == "grouped_bar"


def test_two_numeric_columns_are_a_scatter() -> None:
    assert charts.select_chart(["price", "freight"], [[1.0, 2.0], [3.0, 4.0]])["type"] == "scatter"


def test_no_rows_is_a_table() -> None:
    assert charts.select_chart(["state", "revenue"], [])["type"] == "table"


def test_decimal_values_are_numbers() -> None:
    assert charts.select_chart(["state", "revenue"], [["SP", Decimal("5.00")]])["type"] == "bar"


# ---- explanations -------------------------------------------------------------------------------


def test_explanation_names_the_top_contributor_and_its_share() -> None:
    lines = explain.build_explanation(
        columns=["customer_state", "revenue"],
        rows=[["SP", 300.0], ["RJ", 100.0]],
        metrics=["revenue"],
        metric_descriptions={"revenue": "Item prices on orders that are not canceled."},
        filters=[],
        time_text=None,
        truncated=False,
    )

    assert "SP" in lines[0]
    assert "75.0%" in lines[0]


def test_explanation_reports_period_change() -> None:
    rows = [[dt.date(2017, 1, 1), 100.0], [dt.date(2017, 2, 1), 150.0]]

    lines = explain.build_explanation(
        columns=["metric_time__month", "revenue"],
        rows=rows,
        metrics=["revenue"],
        metric_descriptions={},
        filters=["Customer state = SP"],
        time_text="2017-01-01 to 2017-02-28",
        truncated=True,
    )

    assert any("up 50.0%" in line for line in lines)
    assert "Filters applied: Customer state = SP." in lines
    assert any("first rows" in line for line in lines)


def test_empty_result_has_a_plain_message() -> None:
    lines = explain.build_explanation(
        columns=["revenue"],
        rows=[],
        metrics=["revenue"],
        metric_descriptions={},
        filters=[],
        time_text=None,
        truncated=False,
    )

    assert lines[0].startswith("No rows match")
