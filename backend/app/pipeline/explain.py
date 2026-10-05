"""Deterministic explanations built from the result shape, the plan and the metric definitions."""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

from app.pipeline.shape import column_kinds, humanize

PERIOD_LABELS = {
    "day": "day",
    "week": "week",
    "month": "month",
    "quarter": "quarter",
    "year": "year",
}


def _format_number(value: float) -> str:
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:,.2f} M"
    if abs(value) >= 1000:
        return f"{value:,.0f}"
    return f"{value:,.2f}"


def _money_or_number(metric: str, value: float) -> str:
    text = _format_number(value)
    money_words = ("revenue", "gmv", "freight", "payment", "value", "aov", "order_value")
    if any(word in metric for word in money_words):
        return f"R$ {text}"
    return text


def _number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        return float(value)
    return None


def build_explanation(
    *,
    columns: Sequence[str],
    rows: Sequence[Sequence[Any]],
    metrics: Sequence[str],
    metric_descriptions: Mapping[str, str],
    filters: Sequence[str],
    time_text: str | None,
    truncated: bool,
) -> list[str]:
    lines: list[str] = []
    if not rows:
        lines.append("No rows match this question for your role and the selected period.")
    else:
        kinds = column_kinds(columns, rows)
        numeric = [name for name in columns if kinds[name] == "number"]
        categories = [name for name in columns if kinds[name] == "category"]
        times = [name for name in columns if kinds[name] == "time"]
        metric = metrics[0] if metrics else (numeric[0] if numeric else "value")

        if len(rows) == 1 and len(columns) == 1 and numeric:
            value = _number(rows[0][0])
            if value is not None:
                lines.append(f"{humanize(metric)} is {_money_or_number(metric, value)}.")

        if categories and numeric and not times:
            key_index = columns.index(categories[0])
            value_index = columns.index(numeric[0])
            ranked = sorted(
                (row for row in rows if _number(row[value_index]) is not None),
                key=lambda row: _number(row[value_index]) or 0.0,
                reverse=True,
            )
            total = sum(_number(row[value_index]) or 0.0 for row in rows)
            if ranked:
                top = ranked[0]
                top_value = _number(top[value_index]) or 0.0
                share = (top_value / total * 100) if total else 0.0
                lines.append(
                    f"The largest {humanize(categories[0]).lower()} is {top[key_index]} with "
                    f"{_money_or_number(numeric[0], top_value)} ({share:.1f}% of the total across {len(rows)} groups)."
                )

        if times and numeric:
            time_index = columns.index(times[0])
            value_index = columns.index(numeric[0])
            series = [
                (row[time_index], _number(row[value_index]))
                for row in rows
                if _number(row[value_index]) is not None
            ]
            series.sort(key=lambda item: _sort_key(item[0]))
            if len(series) >= 2 and series[-2][1]:
                last_label, last_value = series[-1]
                last = last_value or 0.0
                previous = series[-2][1] or 0.0
                change = (last - previous) / previous * 100 if previous else 0.0
                direction = "up" if change >= 0 else "down"
                lines.append(
                    f"Latest period ({_label(last_label)}): {_money_or_number(numeric[0], last or 0.0)}, "
                    f"{direction} {abs(change):.1f}% on the previous period."
                )

    if time_text:
        lines.append(f"Period: {time_text}.")
    if filters:
        lines.append("Filters applied: " + "; ".join(filters) + ".")
    for name in metrics:
        description = metric_descriptions.get(name)
        if description:
            lines.append(f"{humanize(name)}: {description}")
    if truncated:
        lines.append("Only the first rows are shown. Narrow the question to see the full result.")
    return lines


def _sort_key(value: Any) -> tuple[int, str]:
    if isinstance(value, dt.datetime):
        return (0, value.isoformat())
    if isinstance(value, dt.date):
        return (0, value.isoformat())
    return (1, str(value))


def _label(value: Any) -> str:
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()[:10]
    return str(value)


def answer_text(explanation: Sequence[str]) -> str:
    return explanation[0] if explanation else "Here is the result for your question."
