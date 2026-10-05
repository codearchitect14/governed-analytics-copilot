"""Chart selection from the result shape. Rules only, no model calls.

Rules (first match wins):
- no rows: table
- one row, one numeric column: KPI card
- one time column and numeric columns: line chart
- one category column and one numeric column: bar chart (ranking) when at most 30 rows
- one category column, one second category column and one numeric column: grouped bar
- two numeric columns: scatter
- otherwise: table
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from typing import Any

from app.pipeline.shape import column_kinds, humanize

MAX_BAR_ROWS = 30
MAX_GROUPS = 12


def _label(value: Any) -> str:
    if isinstance(value, dt.datetime):
        return value.date().isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    return "" if value is None else str(value)


def _number(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def select_chart(columns: Sequence[str], rows: Sequence[Sequence[Any]]) -> dict[str, Any]:
    if not rows or not columns:
        return {"type": "table", "reason": "no rows"}
    kinds = column_kinds(columns, rows)
    numeric = [name for name in columns if kinds[name] == "number"]
    times = [name for name in columns if kinds[name] == "time"]
    categories = [name for name in columns if kinds[name] == "category"]

    if len(rows) == 1 and len(numeric) == 1 and len(columns) == 1:
        return {
            "type": "kpi",
            "metric": numeric[0],
            "value": _number(rows[0][columns.index(numeric[0])]),
        }
    if len(times) == 1 and numeric and not categories:
        return _line(columns, rows, times[0], numeric)
    if len(categories) == 1 and numeric and not times and len(rows) <= MAX_BAR_ROWS:
        return _bar(columns, rows, categories[0], numeric[0])
    if len(categories) == 2 and len(numeric) == 1 and not times:
        groups = {row[columns.index(categories[1])] for row in rows}
        if len(groups) <= MAX_GROUPS:
            return _grouped(columns, rows, categories[0], categories[1], numeric[0])
    if len(numeric) == 2 and not categories and not times:
        return _scatter(columns, rows, numeric[0], numeric[1])
    return {"type": "table", "reason": "no chart rule matched"}


def _axis_text() -> dict[str, Any]:
    return {"textStyle": {"color": "#4b5563"}}


def _line(
    columns: Sequence[str], rows: Sequence[Sequence[Any]], time_col: str, numeric: list[str]
) -> dict[str, Any]:
    t = columns.index(time_col)
    x_values = [_label(row[t]) for row in rows]
    series = [
        {
            "name": humanize(name),
            "type": "line",
            "smooth": True,
            "data": [_number(row[columns.index(name)]) for row in rows],
        }
        for name in numeric
    ]
    option = {
        "tooltip": {"trigger": "axis"},
        "legend": {"data": [humanize(name) for name in numeric]},
        "xAxis": {"type": "category", "data": x_values, "axisLabel": _axis_text()},
        "yAxis": {"type": "value", "axisLabel": _axis_text()},
        "series": series,
    }
    return {"type": "line", "option": option}


def _bar(
    columns: Sequence[str], rows: Sequence[Sequence[Any]], category: str, metric: str
) -> dict[str, Any]:
    c, m = columns.index(category), columns.index(metric)
    option = {
        "tooltip": {"trigger": "axis"},
        "xAxis": {
            "type": "category",
            "data": [_label(row[c]) for row in rows],
            "axisLabel": _axis_text(),
        },
        "yAxis": {"type": "value", "axisLabel": _axis_text()},
        "series": [
            {"name": humanize(metric), "type": "bar", "data": [_number(row[m]) for row in rows]}
        ],
    }
    return {"type": "bar", "option": option}


def _grouped(
    columns: Sequence[str], rows: Sequence[Sequence[Any]], first: str, second: str, metric: str
) -> dict[str, Any]:
    f, s, m = columns.index(first), columns.index(second), columns.index(metric)
    x_values = list(dict.fromkeys(_label(row[f]) for row in rows))
    groups = list(dict.fromkeys(_label(row[s]) for row in rows))
    lookup = {(_label(row[f]), _label(row[s])): _number(row[m]) for row in rows}
    series = [
        {
            "name": group,
            "type": "bar",
            "data": [lookup.get((x, group)) for x in x_values],
        }
        for group in groups
    ]
    option = {
        "tooltip": {"trigger": "axis"},
        "legend": {"data": groups},
        "xAxis": {"type": "category", "data": x_values, "axisLabel": _axis_text()},
        "yAxis": {"type": "value", "axisLabel": _axis_text()},
        "series": series,
    }
    return {"type": "grouped_bar", "option": option}


def _scatter(
    columns: Sequence[str], rows: Sequence[Sequence[Any]], x: str, y: str
) -> dict[str, Any]:
    xi, yi = columns.index(x), columns.index(y)
    option = {
        "tooltip": {"trigger": "item"},
        "xAxis": {"type": "value", "name": humanize(x), "axisLabel": _axis_text()},
        "yAxis": {"type": "value", "name": humanize(y), "axisLabel": _axis_text()},
        "series": [{"type": "scatter", "data": [[_number(r[xi]), _number(r[yi])] for r in rows]}],
    }
    return {"type": "scatter", "option": option}
