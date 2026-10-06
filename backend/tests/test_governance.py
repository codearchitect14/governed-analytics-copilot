"""Phase 6 governance: permission matrix, adversarial set, RLS without the rewrite, masking, pen tests.

Requires the dev stack (analytics marts with row level security applied by dbt) and mf, like
test_pipeline_live.py. The leakage counts must be zero.
"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from app.pipeline import executor, sql_guard
from app.pipeline.executor import ColumnCatalog
from app.policy.engine import PolicyDenied
from app.policy.loader import load_effective_policy
from app.policy.rls import rls_settings
from tests.test_pipeline_live import (
    ScriptedGateway,
    _run,
    _user,
    _user_with_scopes,
    live,  # noqa: F401 - fixture
)

GOLDEN = Path(__file__).resolve().parents[2] / "dataset" / "golden"
HEX32 = re.compile(r"^[0-9a-f]{32}$")


def _jsonl(name: str) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in (GOLDEN / name).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _policy(services, email: str):  # type: ignore[no-untyped-def]
    return load_effective_policy(services.app_engine, _user(email).id)


# ---- permission matrix ----------------------------------------------------------------------------


def test_permission_matrix_has_zero_leakage(live) -> None:  # type: ignore[no-untyped-def]
    leaks: list[str] = []
    decision_failures: list[str] = []
    for row in _jsonl("permission_tests.jsonl"):
        role = str(row["role"])
        user = _user_with_scopes(role, dict(row["scopes"]))  # type: ignore[arg-type]
        result = _run(live, str(row["question"]), user)
        decision = result.get("decision") or ("allowed" if result["kind"] == "result" else "error")
        if decision != row["expect_decision"]:
            decision_failures.append(
                f"{row['id']}: {decision} != {row['expect_decision']} ({result.get('message')})"
            )
        if result["kind"] != "result" or row["column"] is None:
            continue
        column = str(row["column"])
        columns = list(result.get("columns") or [])  # type: ignore[arg-type]
        index = columns.index(column)
        allowed = set(row["allowed"])  # type: ignore[arg-type]
        for values in result["rows"]:  # type: ignore[union-attr]
            if values[index] not in allowed:
                leaks.append(f"{row['id']}: {values[index]} outside {sorted(allowed)}")
    assert not leaks, "\n".join(leaks)
    assert not decision_failures, "\n".join(decision_failures)


def test_matrix_produces_different_results_per_role(live) -> None:  # type: ignore[no-untyped-def]
    east = _run(
        live,
        "Revenue by customer state",
        _user_with_scopes("regional_manager", {"regions": ["RJ"]}),
    )
    west = _run(
        live,
        "Revenue by customer state",
        _user_with_scopes("regional_manager", {"regions": ["SP"]}),
    )

    assert east["rows"] != west["rows"]


# ---- adversarial set --------------------------------------------------------------------------------


def test_adversarial_set_returns_no_rows_and_matches_expected_decisions(live) -> None:  # type: ignore[no-untyped-def]
    leaked: list[str] = []
    mismatched: list[str] = []
    for item in _jsonl("adversarial.jsonl"):
        services = replace(live, gateway=ScriptedGateway(*list(item["script"])))  # type: ignore[arg-type]
        user = _user(_email_for(str(item["role"])))
        result = _run(services, str(item["question"]), user)
        decision = result.get("decision") or ("allowed" if result["kind"] == "result" else "error")
        if decision != item["expect_decision"]:
            mismatched.append(f"{item['id']}: {decision} != {item['expect_decision']}")
        if (
            result["kind"] == "result"
            and result.get("rows")
            and item["expect_decision"] != "allowed"
        ):
            leaked.append(str(item["id"]))
    assert not leaked, f"rows returned for adversarial cases: {leaked}"
    assert not mismatched, "\n".join(mismatched)


def _email_for(role: str) -> str:
    return {
        "executive": "executive@meridian.example",
        "analyst": "analyst@meridian.example",
        "seller_partner": "seller.partner@meridian.example",
        "admin": "admin@meridian.example",
    }[role]


# ---- row level security without the rewrite -------------------------------------------------------


def _rls_user_filters(role: str, scopes: dict[str, object]) -> dict[str, object]:
    from app.policy.definitions import ROLES
    from app.policy.engine import build_effective_policy

    definition = next(item for item in ROLES if item.name == role)
    policy = build_effective_policy(
        role=role, policy_version=1, policy=dict(definition.policy), scopes=scopes
    )
    return rls_settings(policy)


def test_row_level_security_alone_limits_rows_when_the_rewrite_is_skipped(live) -> None:  # type: ignore[no-untyped-def]
    filters = _rls_user_filters("regional_manager", {"regions": ["RJ"]})

    result = executor.execute(
        live.executor_engine,
        "SELECT customer_state, line_revenue FROM analytics.fct_order_items",
        1000,
        filters,
    )

    assert {row[0] for row in result.rows} <= {"RJ"}


def test_row_level_security_fails_closed_without_settings(live) -> None:  # type: ignore[no-untyped-def]
    result = executor.execute(live.executor_engine, "SELECT * FROM analytics.fct_orders", 1000, {})

    assert result.rows == []


def test_row_level_security_hides_tables_outside_the_policy(live) -> None:  # type: ignore[no-untyped-def]
    filters = _rls_user_filters("seller_partner", {"seller_id": "S1"})

    result = executor.execute(
        live.executor_engine, "SELECT * FROM analytics.fct_orders", 1000, filters
    )

    assert result.rows == []  # no entry for the table in the setting: no rows, not even an error


def test_warehouse_ro_cannot_read_staging_raw_or_app_schemas(live) -> None:  # type: ignore[no-untyped-def]
    filters = _rls_user_filters("executive", {})

    for sql in (
        "SELECT * FROM analytics.stg_customers",
        "SELECT * FROM analytics.int_orders_enriched",
        "SELECT * FROM raw.orders",
        "SELECT * FROM app.users",
    ):
        with pytest.raises((DBAPIError, ProgrammingError)):
            executor.execute(live.executor_engine, sql, 10, filters)


def test_executor_role_cannot_write(live) -> None:  # type: ignore[no-untyped-def]
    filters = _rls_user_filters("executive", {})

    with pytest.raises(DBAPIError):
        executor.execute(live.executor_engine, "DELETE FROM analytics.fct_orders", 10, filters)


# ---- masking -------------------------------------------------------------------------------------


def test_analyst_identifiers_are_hashed_in_every_projection(live) -> None:  # type: ignore[no-untyped-def]
    policy = _policy(live, "analyst@meridian.example")
    rewrite = sql_guard.validate_and_rewrite(
        "SELECT * FROM analytics.dim_customers", policy, live.columns.columns_for, 50
    )
    result = executor.execute(live.executor_engine, rewrite.sql, 50, rls_settings(policy))

    column = result.columns.index("customer_unique_id")
    assert result.rows
    assert all(HEX32.match(str(row[column])) for row in result.rows)


# ---- penetration style checks (guard) ------------------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1; SELECT 2",
        "SELECT pg_sleep(30)",
        "SELECT * FROM pg_catalog.pg_user",
        "SELECT * FROM information_schema.tables",
        "SELECT lo_export(1, '/tmp/x')",
        "SELECT set_config('app.user_filters', '{}', false) FROM analytics.dim_date",
        "SELECT * FROM analytics.dim_date WHERE 1=1 -- bypass",
        "COPY analytics.fct_orders TO '/tmp/out.csv'",
        "SELECT * FROM analytics.fct_orders, analytics.dim_date",
    ],
)
def test_penetration_queries_never_reach_the_database(sql: str, live) -> None:  # type: ignore[no-untyped-def]
    policy = _policy(live, "executive@meridian.example")

    with pytest.raises((sql_guard.SqlRejected, PolicyDenied)):
        sql_guard.validate_and_rewrite(sql, policy, live.columns.columns_for, 10)


def test_column_catalog_is_limited_to_granted_relations(live) -> None:  # type: ignore[no-untyped-def]
    catalog = ColumnCatalog(live.executor_engine)

    assert catalog.columns_for("analytics.fct_orders")
    assert catalog.columns_for("analytics.stg_customers") == []
    with live.executor_engine.connect() as connection:
        visible = (
            connection.execute(
                text(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema = 'analytics'"
                )
            )
            .scalars()
            .all()
        )
    assert "stg_customers" not in visible
