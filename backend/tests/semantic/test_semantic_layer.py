"""Unit tests for the semantic layer: plans, compiler arguments, time windows and the resolver.

These tests read the real seed files and the dbt metrics file, so a renamed metric breaks them.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.semantic import compiler
from app.semantic.plan import Filter, MetricPlan, TimeWindow
from app.semantic.rule_resolver import resolve
from app.semantic.time_parser import parse_time_phrase
from app.semantic.vocabulary import Vocabulary, load_vocabulary

REPO_ROOT = Path(__file__).resolve().parents[3]
SYNONYMS = REPO_ROOT / "dataset" / "semantic_seed" / "synonyms.yml"
METRICS = REPO_ROOT / "warehouse" / "dbt_project" / "models" / "semantic" / "metrics.yml"
EXAMPLES = REPO_ROOT / "dataset" / "semantic_seed" / "few_shot_examples.jsonl"
MENTIONS = REPO_ROOT / "dataset" / "semantic_seed" / "retrieval_mentions.jsonl"
DATA_AS_OF = date(2018, 1, 3)


@pytest.fixture(scope="module")
def vocabulary() -> Vocabulary:
    return load_vocabulary(SYNONYMS, METRICS)


# --- plans -----------------------------------------------------------------------------------


def test_plan_accepts_a_valid_structure() -> None:
    plan = MetricPlan(
        metrics=["revenue"],
        group_by=["metric_time__month", "order_item__customer_state"],
        filters=[Filter(dimension="order_item__customer_state", value="SP")],
        limit=10,
    )

    assert plan.time_grain() == "month"


@pytest.mark.parametrize(
    "value",
    ["SP'; DROP TABLE x; --", "a\\b", "x -- y", "{{ Dimension('x') }}", "x" * 101],
)
def test_filter_rejects_unsafe_values(value: str) -> None:
    with pytest.raises(ValidationError):
        Filter(dimension="order_item__customer_state", value=value)


@pytest.mark.parametrize("name", ["Revenue", "revenue; select 1", "order__", "a__b__c", ""])
def test_plan_rejects_malformed_names(name: str) -> None:
    with pytest.raises(ValidationError):
        MetricPlan(metrics=[name])


def test_plan_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        MetricPlan.model_validate({"metrics": ["revenue"], "sql": "select 1"})


def test_list_value_requires_in_operator() -> None:
    with pytest.raises(ValidationError):
        Filter(dimension="order__payment_type", operator="=", value=["boleto", "voucher"])


def test_time_window_must_be_ordered() -> None:
    with pytest.raises(ValidationError):
        TimeWindow(start=date(2018, 2, 1), end=date(2018, 1, 1))


# --- compiler --------------------------------------------------------------------------------


def test_render_filter_quotes_and_escapes_values() -> None:
    rendered = compiler.render_filter(Filter(dimension="order__customer_city", value="o'brien"))

    assert rendered == "{{ Dimension('order__customer_city') }} = 'o''brien'"


def test_render_in_filter_builds_a_list() -> None:
    rendered = compiler.render_filter(
        Filter(dimension="order__payment_type", operator="in", value=["boleto", "voucher"])
    )

    assert rendered == "{{ Dimension('order__payment_type') }} IN ('boleto', 'voucher')"


def test_time_window_renders_half_open_bounds() -> None:
    window = TimeWindow(start=date(2017, 2, 1), end=date(2017, 3, 1), grain="month")

    clauses = compiler.render_time_window(window)

    assert clauses == [
        "{{ TimeDimension('metric_time', 'month') }} >= '2017-02-01'",
        "{{ TimeDimension('metric_time', 'month') }} < '2017-03-01'",
    ]


def test_build_arguments_is_a_plain_argument_list() -> None:
    plan = MetricPlan(
        metrics=["revenue", "orders"],
        group_by=["metric_time__month"],
        filters=[Filter(dimension="order_item__customer_state", value="SP")],
        order_by=["-revenue"],
        limit=5,
    )

    arguments = compiler.build_arguments(plan, executable="mf", csv_path=Path("out.csv"))

    assert arguments[:5] == ["mf", "query", "--metrics", "revenue,orders", "--group-by"]
    assert "--order" in arguments and "-revenue" in arguments
    assert arguments[-2:] == ["--csv", "out.csv"]
    assert all(isinstance(item, str) for item in arguments)


def test_extract_sql_reads_explain_block() -> None:
    output = "- Initiating query\n🔎 SQL (remove --explain to see data):\n\nSELECT 1\nFROM t\n"

    assert compiler.extract_sql(output) == "SELECT 1\nFROM t"


# --- time parsing ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("phrase", "start", "end", "grain"),
    [
        ("revenue last month", date(2017, 12, 1), date(2018, 1, 1), "month"),
        ("orders this month", date(2018, 1, 1), date(2018, 2, 1), "month"),
        ("sales last quarter", date(2017, 10, 1), date(2018, 1, 1), "quarter"),
        ("this year so far", date(2018, 1, 1), date(2018, 1, 4), "month"),
        ("last year", date(2017, 1, 1), date(2018, 1, 1), "month"),
        ("last 7 days", date(2017, 12, 28), date(2018, 1, 4), "day"),
        ("last 3 months", date(2017, 11, 1), date(2018, 2, 1), "month"),
        ("in 2017", date(2017, 1, 1), date(2018, 1, 1), "month"),
        ("since 2017-02", date(2017, 2, 1), date(2018, 2, 1), "month"),
    ],
)
def test_time_phrases_anchor_to_data_as_of(phrase: str, start: date, end: date, grain: str) -> None:
    parsed = parse_time_phrase(phrase, DATA_AS_OF)

    assert parsed is not None
    assert (parsed.window.start, parsed.window.end, parsed.window.grain) == (start, end, grain)


def test_no_time_phrase_returns_none() -> None:
    assert parse_time_phrase("what is the average review score", DATA_AS_OF) is None


def test_month_arithmetic_crosses_year_boundary() -> None:
    parsed = parse_time_phrase("last 14 months", date(2018, 3, 15))

    assert parsed is not None
    assert parsed.window.start == date(2017, 2, 1)


# --- rule resolver ---------------------------------------------------------------------------


def test_single_metric_with_grouping_and_time_resolves(vocabulary: Vocabulary) -> None:
    result = resolve("revenue by customer state last month", vocabulary, DATA_AS_OF)

    assert result.resolved
    assert result.plan is not None
    assert result.plan.metrics == ["revenue"]
    assert result.plan.group_by == ["order_item__customer_state"]
    assert result.plan.time_window is not None
    assert result.plan.time_window.start == date(2017, 12, 1)


def test_synonym_maps_to_metric(vocabulary: Vocabulary) -> None:
    result = resolve("what were our total sales", vocabulary, DATA_AS_OF)

    assert result.resolved
    assert result.plan is not None
    assert result.plan.metrics == ["revenue"]


def test_monthly_trend_groups_by_month(vocabulary: Vocabulary) -> None:
    result = resolve("monthly orders", vocabulary, DATA_AS_OF)

    assert result.resolved
    assert result.plan is not None
    assert result.plan.group_by == ["metric_time__month"]


def test_value_mention_becomes_filter(vocabulary: Vocabulary) -> None:
    result = resolve("revenue in sao paulo", vocabulary, DATA_AS_OF)

    assert result.resolved
    assert result.plan is not None
    assert result.plan.filters == [
        Filter(dimension="order_item__customer_state", operator="=", value="SP")
    ]


def test_two_metrics_are_not_resolved_by_rules(vocabulary: Vocabulary) -> None:
    result = resolve("revenue and orders by month", vocabulary, DATA_AS_OF)

    assert result.status == "multi_metric"
    assert result.plan is None


def test_question_without_metric_is_not_resolved(vocabulary: Vocabulary) -> None:
    result = resolve("tell me a joke about data", vocabulary, DATA_AS_OF)

    assert result.status == "no_match"


def test_question_text_is_treated_as_data_not_sql(vocabulary: Vocabulary) -> None:
    result = resolve("revenue'; drop table orders; --", vocabulary, DATA_AS_OF)

    assert result.plan is None or result.plan.filters == []


# --- seed data consistency -------------------------------------------------------------------


def test_every_value_mapping_targets_a_known_dimension(vocabulary: Vocabulary) -> None:
    dimension_names = vocabulary.dimension_names()
    for mapping in vocabulary.values:
        assert mapping.dimension in dimension_names, mapping


def test_few_shot_examples_are_valid_plans(vocabulary: Vocabulary) -> None:
    records = [
        json.loads(line) for line in EXAMPLES.read_text(encoding="utf-8").splitlines() if line
    ]

    assert len(records) >= 10
    for record in records:
        plan = MetricPlan.model_validate(record["plan"])
        assert set(plan.metrics) <= vocabulary.metric_names(), record["id"]


def test_retrieval_mentions_reference_known_catalog_names(vocabulary: Vocabulary) -> None:
    records = [
        json.loads(line) for line in MENTIONS.read_text(encoding="utf-8").splitlines() if line
    ]

    for record in records:
        if record["kind"] == "metric":
            assert record["name"] in vocabulary.metric_names(), record
        else:
            assert record["name"] in vocabulary.dimension_names(), record
