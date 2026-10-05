"""Shared helpers for result shape and labels (no imports from the other pipeline modules)."""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

NUMERIC = (int, float, Decimal)


def column_kinds(columns: Sequence[str], rows: Sequence[Sequence[Any]]) -> dict[str, str]:
    """Classify each column as time, number or category using the first non empty value."""
    kinds: dict[str, str] = {}
    for index, name in enumerate(columns):
        sample = next((row[index] for row in rows if row[index] is not None), None)
        if isinstance(sample, (dt.date, dt.datetime)):
            kinds[name] = "time"
        elif isinstance(sample, bool):
            kinds[name] = "category"
        elif isinstance(sample, NUMERIC):
            kinds[name] = "number"
        else:
            kinds[name] = "category"
    return kinds


def humanize(name: str) -> str:
    """customer_state -> Customer state; order_item__customer_state -> Customer state."""
    base = name.split("__", 1)[-1]
    return base.replace("_", " ").strip().capitalize()
