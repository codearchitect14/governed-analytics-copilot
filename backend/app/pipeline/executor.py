"""Query executor for the read only role (warehouse_ro).

Every query runs in a READ ONLY transaction with a statement timeout. An EXPLAIN cost gate
rejects expensive plans before execution. The row cap is applied in the SQL itself.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Engine, text

from app.policy.engine import ANALYTICS_SCHEMA

STATEMENT_TIMEOUT = "10s"


class CostRejected(Exception):
    def __init__(self, estimated: float, ceiling: float) -> None:
        super().__init__(f"estimated cost {estimated:.0f} exceeds the limit {ceiling:.0f}")
        self.estimated = estimated
        self.ceiling = ceiling


@dataclass(frozen=True)
class ExecutionResult:
    columns: list[str]
    rows: list[list[Any]]
    truncated: bool
    exec_ms: int


class ColumnCatalog:
    """Column names of analytics relations, read once per process from information_schema."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._cache: dict[str, list[str]] = {}
        self._lock = threading.Lock()

    def columns_for(self, qualified: str) -> list[str]:
        with self._lock:
            if qualified in self._cache:
                return self._cache[qualified]
        schema, name = qualified.split(".", 1)
        if schema != ANALYTICS_SCHEMA:
            return []
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT column_name FROM information_schema.columns
                    WHERE table_schema = :schema AND table_name = :name
                    ORDER BY ordinal_position
                    """
                ),
                {"schema": schema, "name": name},
            ).all()
        columns = [str(row[0]) for row in rows]
        with self._lock:
            self._cache[qualified] = columns
        return columns


def _apply_row_filters(connection: Any, user_filters: Mapping[str, Any]) -> None:
    """Set the per transaction row level setting that the database policies read."""
    connection.execute(
        text("SELECT set_config('app.user_filters', :settings, true)"),
        {"settings": json.dumps(user_filters, sort_keys=True)},
    )


def estimated_cost(engine: Engine, sql: str, user_filters: Mapping[str, Any]) -> float:
    with engine.connect() as connection, connection.begin():
        connection.execute(text("SET TRANSACTION READ ONLY"))
        _apply_row_filters(connection, user_filters)
        plan = connection.exec_driver_sql(f"EXPLAIN (FORMAT JSON) {sql}").scalar()
    document: Any = json.loads(plan) if isinstance(plan, str) else plan
    return float(document[0]["Plan"]["Total Cost"])


def enforce_cost_ceiling(
    engine: Engine, sql: str, ceiling: float, user_filters: Mapping[str, Any]
) -> float:
    cost = estimated_cost(engine, sql, user_filters)
    if cost > ceiling:
        raise CostRejected(cost, ceiling)
    return cost


def execute(
    engine: Engine, sql: str, max_rows: int, user_filters: Mapping[str, Any]
) -> ExecutionResult:
    """Run the rewritten SQL with a row cap. Row level security applies to every read.

    The row filter setting is required: without it the database returns no rows.
    """
    started = time.perf_counter()
    # The SQL was validated and rewritten by sql_guard; the row cap is an integer.
    wrapped = f"SELECT * FROM ({sql}) AS result_set LIMIT {int(max_rows) + 1}"  # noqa: S608
    with engine.connect() as connection, connection.begin():
        connection.execute(text("SET TRANSACTION READ ONLY"))
        connection.execute(text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT}'"))
        _apply_row_filters(connection, user_filters)
        result = connection.exec_driver_sql(wrapped)
        columns = list(result.keys())
        fetched = [list(row) for row in result.fetchall()]
    truncated = len(fetched) > max_rows
    rows = fetched[:max_rows]
    return ExecutionResult(
        columns=columns,
        rows=rows,
        truncated=truncated,
        exec_ms=int((time.perf_counter() - started) * 1000),
    )
