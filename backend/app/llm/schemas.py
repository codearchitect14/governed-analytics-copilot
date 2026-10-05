"""Structured output the model must produce. Every model output is validated before use."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.semantic.plan import Filter, TimeWindow

Intent = Literal["metric_query", "sql_fallback", "clarify", "refuse"]


class PlanOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    intent: Intent
    metrics: list[str] = Field(default_factory=list, max_length=3)
    group_by: list[str] = Field(default_factory=list, max_length=4)
    filters: list[Filter] = Field(default_factory=list, max_length=10)
    time_window: TimeWindow | None = None
    order_by: list[str] = Field(default_factory=list, max_length=2)
    limit: int | None = Field(default=None, ge=1, le=1000)
    clarification: str | None = Field(default=None, max_length=300)
    refusal_reason: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def _intent_fields(self) -> PlanOutput:
        if self.intent == "metric_query" and not self.metrics:
            raise ValueError("metric_query requires at least one metric")
        if self.intent == "clarify" and not self.clarification:
            raise ValueError("clarify requires a clarification question")
        if self.intent == "refuse" and not self.refusal_reason:
            raise ValueError("refuse requires a refusal reason")
        return self


class SqlOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sql: str = Field(min_length=6, max_length=4000)


def reference_date_text(day: date) -> str:
    return day.isoformat()
