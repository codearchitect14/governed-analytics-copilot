"""Property based tests for the SQL guard (hypothesis). No database needed.

Generated queries vary aliases, quoting, CTEs, subqueries, unions and comments. For every query
the guard must either reject it or return SQL that is one statement, contains no dangerous
function, and carries the row filter of every restricted table it reads.
"""

from __future__ import annotations

import sqlglot
from hypothesis import given, settings
from hypothesis import strategies as st

from app.pipeline import sql_guard
from app.policy.definitions import ROLES
from app.policy.engine import EffectivePolicy, PolicyDenied, build_effective_policy
from tests.test_pipeline_units import columns_for

ALIAS = st.from_regex(r"a_[a-z]{1,6}", fullmatch=True)
TABLES = st.sampled_from(
    [
        "analytics.fct_orders",
        '"analytics"."fct_orders"',
        "analytics.fct_order_items",
        "analytics.dim_customers",
    ]
)
SHAPES = st.sampled_from(["plain", "cte", "subquery", "union", "quoted_alias", "comment"])
FORBIDDEN = ("pg_sleep", "dblink", "pg_read_file", "set_config", "information_schema", "pg_catalog")
FORBIDDEN_FUNCTIONS = frozenset({"pg_sleep", "dblink", "pg_read_file", "set_config", "lo_export"})


def _policy(role: str, scopes: dict[str, object]) -> EffectivePolicy:
    definition = next(item for item in ROLES if item.name == role)
    return build_effective_policy(
        role=role, policy_version=1, policy=dict(definition.policy), scopes=scopes
    )


def _build(table: str, alias: str, shape: str) -> str:
    column = "customer_state"
    if shape == "plain":
        return f"SELECT {alias}.{column} FROM {table} AS {alias}"
    if shape == "cte":
        return f"WITH {alias} AS (SELECT {column} FROM {table}) SELECT {column} FROM {alias}"
    if shape == "subquery":
        return f"SELECT {column} FROM (SELECT {column} FROM {table}) AS {alias}"
    if shape == "union":
        return f"SELECT {column} FROM {table} UNION SELECT {column} FROM {table}"
    if shape == "quoted_alias":
        return f'SELECT "{alias}"."{column}" FROM {table} AS "{alias}"'
    return f"SELECT {column} FROM {table} /* {alias} */"


@settings(max_examples=120, deadline=None)
@given(table=TABLES, alias=ALIAS, shape=SHAPES)
def test_regional_rows_are_always_filtered_or_the_query_is_rejected(
    table: str, alias: str, shape: str
) -> None:
    policy = _policy("regional_manager", {"regions": ["SP", "RJ"]})
    sql = _build(table, alias, shape)
    try:
        result = sql_guard.validate_and_rewrite(sql, policy, columns_for, 100)
    except (sql_guard.SqlRejected, PolicyDenied):
        return
    assert len(sqlglot.parse(result.sql, read="postgres")) == 1
    assert not any(name in result.sql.lower() for name in FORBIDDEN)
    if "fct_orders" in table or "fct_order_items" in table:
        assert "customer_state IN ('SP', 'RJ')" in result.sql


@settings(max_examples=80, deadline=None)
@given(alias=ALIAS, shape=SHAPES)
def test_admin_never_gets_data_whatever_the_shape(alias: str, shape: str) -> None:
    policy = _policy("admin", {})
    sql = _build("analytics.fct_orders", alias, shape)
    try:
        sql_guard.validate_and_rewrite(sql, policy, columns_for, 100)
    except (sql_guard.SqlRejected, PolicyDenied):
        return
    raise AssertionError(f"admin query was accepted: {sql}")


@settings(max_examples=80, deadline=None)
@given(
    function=st.sampled_from(sorted(FORBIDDEN_FUNCTIONS)),
    alias=ALIAS,
    shape=SHAPES,
)
def test_forbidden_functions_are_rejected_in_every_shape(
    function: str, alias: str, shape: str
) -> None:
    policy = _policy("executive", {})
    base = _build("analytics.fct_orders", alias, shape)
    sql = f"SELECT {function}(1) AS f FROM ({base}) AS {alias}_outer"
    try:
        sql_guard.validate_and_rewrite(sql, policy, columns_for, 100)
    except (sql_guard.SqlRejected, PolicyDenied):
        return
    raise AssertionError(f"forbidden function accepted: {sql}")


@settings(max_examples=60, deadline=None)
@given(
    payload=st.text(alphabet=st.characters(blacklist_categories=("Cs",)), min_size=1, max_size=40)
)
def test_arbitrary_text_never_produces_unfiltered_sql(payload: str) -> None:
    """Whatever the model returns, an accepted statement is a single filtered SELECT."""
    policy = _policy("regional_manager", {"regions": ["RJ"]})
    sql = f"SELECT customer_state FROM analytics.fct_orders WHERE customer_state = '{payload}'"
    try:
        result = sql_guard.validate_and_rewrite(sql, policy, columns_for, 100)
    except (sql_guard.SqlRejected, PolicyDenied):
        return
    assert "customer_state IN ('RJ')" in result.sql or "customer_state = 'RJ'" in result.sql
