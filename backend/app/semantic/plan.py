"""Structured metric plans.

A plan selects governed metrics and dimensions. It is the only input the MetricFlow compiler
accepts, so model output never reaches the compiler as free text.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

NAME_PATTERN = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*(__[a-z][a-z0-9]*(_[a-z0-9]+)*)?$")
FORBIDDEN_VALUE_FRAGMENTS = (
    '"',
    "\\",
    ";",
    "--",
    "/*",
    "*/",
    "{",
    "}",
)  # quotes are escaped by the compiler
MAX_VALUE_LENGTH = 100
TIME_DIMENSION = "metric_time"
TIME_GRAINS = ("day", "week", "month", "quarter", "year")

Operator = Literal["=", "!=", ">=", "<=", ">", "<", "in"]
FilterValue = str | int | float | list[str] | list[int] | list[float]


def _check_name(name: str) -> str:
    if not NAME_PATTERN.match(name):
        raise ValueError(f"invalid name {name!r}: use snake_case, optional entity__ prefix")
    return name


class Filter(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dimension: str
    operator: Operator = "="
    value: FilterValue

    @field_validator("dimension")
    @classmethod
    def _dimension_name(cls, value: str) -> str:
        return _check_name(value)

    @model_validator(mode="after")
    def _value_is_safe(self) -> Filter:
        values = self.value if isinstance(self.value, list) else [self.value]
        if self.operator == "in" and not isinstance(self.value, list):
            raise ValueError("operator 'in' requires a list value")
        if self.operator != "in" and isinstance(self.value, list):
            raise ValueError("a list value requires operator 'in'")
        for item in values:
            if isinstance(item, str):
                if len(item) > MAX_VALUE_LENGTH:
                    raise ValueError("filter value is too long")
                if any(fragment in item for fragment in FORBIDDEN_VALUE_FRAGMENTS):
                    raise ValueError(f"filter value contains a forbidden character: {item!r}")
        return self


class TimeWindow(BaseModel):
    """Half open range on the metric time dimension: start <= t < end."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    start: date
    end: date
    grain: Literal["day", "week", "month", "quarter", "year"] = "day"

    @model_validator(mode="after")
    def _ordered(self) -> TimeWindow:
        if self.end <= self.start:
            raise ValueError("time window end must be after start")
        return self


class MetricPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metrics: list[str] = Field(min_length=1, max_length=5)
    group_by: list[str] = Field(default_factory=list, max_length=4)
    filters: list[Filter] = Field(default_factory=list, max_length=10)
    time_window: TimeWindow | None = None
    order_by: list[str] = Field(default_factory=list, max_length=2)
    limit: int | None = Field(default=None, ge=1, le=1000)

    @field_validator("metrics", "group_by")
    @classmethod
    def _names(cls, values: list[str]) -> list[str]:
        for value in values:
            _check_name(value)
        return values

    @field_validator("order_by")
    @classmethod
    def _order_names(cls, values: list[str]) -> list[str]:
        for value in values:
            _check_name(value.removeprefix("-"))
        return values

    def time_grain(self) -> str | None:
        """Grain of the metric time group-by, if the plan groups by time."""
        for name in self.group_by:
            if name.startswith(f"{TIME_DIMENSION}__"):
                grain = name.removeprefix(f"{TIME_DIMENSION}__")
                if grain in TIME_GRAINS:
                    return grain
        return None
