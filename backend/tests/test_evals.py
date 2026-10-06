"""Evaluation harness: suite loading, scoring, result comparison, resumable runs and the gate.

These tests stub the per-question executor, so they run without the database or a model.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.evals import gate, runner
from app.evals.scoring import execution_match, score, summarize
from app.evals.suites import Case, load_suite, select


def _case(**overrides: Any) -> Case:
    base: dict[str, Any] = {
        "id": "C1",
        "suite": "permission",
        "role": "regional_manager",
        "question": "Revenue by customer state",
        "expect_decision": "allowed",
        "expect_route": None,
        "scopes": {"regions": ["RJ"]},
        "column": "order_item__customer_state",
        "allowed": ("RJ",),
        "script": (),
        "raw": {},
    }
    base.update(overrides)
    return Case(**base)


def test_golden_suites_load_with_expected_sizes() -> None:
    assert len(load_suite("pipeline")) == 20
    assert len(load_suite("permission")) == 10
    assert len(load_suite("adversarial")) == 16
    for name in ("pipeline", "permission", "adversarial"):
        ids = [case.id for case in load_suite(name)]
        assert len(ids) == len(set(ids))


def test_select_limits_and_stratifies_across_strata() -> None:
    cases = [_case(id=f"A{i}", expect_decision="allowed") for i in range(6)]
    cases += [_case(id=f"D{i}", expect_decision="denied") for i in range(2)]

    chosen = select(cases, limit=4, stratified=True)

    assert [c.expect_decision for c in chosen].count("denied") == 2
    assert len(chosen) == 4
    assert select(cases, limit=3) == cases[:3]


def test_execution_match_ignores_order_and_tolerates_float_noise() -> None:
    gold = [("a", 1.0), ("b", 2.0)]
    predicted = [("b", 2.0000000001), ("a", 1.0)]

    assert execution_match(gold, predicted)
    assert not execution_match(gold, predicted, ordered=True)
    assert not execution_match(gold, [("a", 1.0)])
    assert not execution_match(gold, [("a", 1.0), ("b", 2.5)])


def test_permission_leakage_is_flagged_when_rows_fall_outside_scope() -> None:
    result = {
        "kind": "result",
        "decision": "allowed",
        "route": "rule",
        "columns": ["order_item__customer_state", "revenue"],
        "rows": [["RJ", 10], ["SP", 99]],
    }

    scored = score(_case(), result)

    assert scored["leaked"] is True
    assert scored["passed"] is False


def test_adversarial_case_with_rows_counts_as_leakage() -> None:
    case = _case(suite="adversarial", expect_decision="denied", column=None, allowed=())
    result = {"kind": "result", "decision": "allowed", "rows": [[1]], "columns": ["x"]}

    assert score(case, result)["leaked"] is True


def test_route_mismatch_is_classified() -> None:
    case = _case(suite="pipeline", expect_route="rule", column=None, scopes={}, allowed=())
    result = {"kind": "result", "decision": "allowed", "route": "llm_plan", "rows": []}

    scored = score(case, result)

    assert scored["passed"] is False
    assert scored["error_class"] == "wrong_route"


def test_summary_reports_accuracy_leakage_and_taxonomy() -> None:
    records = [
        {
            "passed": True,
            "leaked": False,
            "expect_decision": "allowed",
            "decision": "allowed",
            "error_class": None,
            "latency_ms": 100,
            "tokens_in": 10,
            "tokens_out": 5,
        },
        {
            "passed": False,
            "leaked": True,
            "expect_decision": "denied",
            "decision": "allowed",
            "error_class": "policy_denial_mismatch",
            "latency_ms": 300,
            "tokens_in": 0,
            "tokens_out": 0,
        },
    ]

    metrics = summarize(records)

    assert metrics["sample_size"] == 2
    assert metrics["accuracy"] == 0.5
    assert metrics["leakage_rate"] == 0.5
    assert metrics["correct_denial_rate"] == 0.0
    assert metrics["error_taxonomy"] == {"policy_denial_mismatch": 1}
    assert metrics["avg_tokens_per_question"] == 7.5


def test_run_resumes_from_checkpoint_without_rerunning_done_cases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    results = tmp_path / "results"
    results.mkdir()
    cases = [_case(id="C1"), _case(id="C2")]
    done = {
        "id": "C1",
        "suite": "permission",
        "role": "regional_manager",
        "passed": True,
        "expect_decision": "allowed",
        "decision": "allowed",
        "expect_route": None,
        "route": "rule",
        "leaked": False,
        "error_class": None,
        "sql": None,
        "tokens_in": 0,
        "tokens_out": 0,
        "latency_ms": 1,
    }
    (results / "run-1.checkpoint.jsonl").write_text(json.dumps(done) + "\n", encoding="utf-8")
    calls: list[str] = []

    def fake_execute(_services: object, case: Case) -> dict[str, Any]:
        calls.append(case.id)
        return {"kind": "result", "decision": "allowed", "route": "rule", "rows": [], "columns": []}

    monkeypatch.setattr(runner, "execute_case", fake_execute)

    summary = runner.run_suite(
        object(),  # type: ignore[arg-type]
        "permission",
        cases,
        run_id="run-1",
        model="test-model",
        prompt_version="v1",
        use_cache=False,
        results_dir=results,
        cache_dir=tmp_path / "cache",
    )

    assert calls == ["C2"]
    assert summary["metrics"]["sample_size"] == 2


def test_response_cache_avoids_a_second_model_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def fake_execute(_services: object, case: Case) -> dict[str, Any]:
        calls.append(case.id)
        return {"kind": "result", "decision": "allowed", "route": "rule", "rows": [], "columns": []}

    monkeypatch.setattr(runner, "execute_case", fake_execute)
    kwargs: dict[str, Any] = {
        "model": "m",
        "prompt_version": "v1",
        "use_cache": True,
        "results_dir": tmp_path / "a",
        "cache_dir": tmp_path / "cache",
    }

    runner.run_suite(object(), "permission", [_case()], run_id="r1", **kwargs)  # type: ignore[arg-type]
    runner.run_suite(object(), "permission", [_case()], run_id="r2", **kwargs)  # type: ignore[arg-type]

    assert calls == ["C1"]


def test_gate_fails_on_leakage_and_on_large_accuracy_drop() -> None:
    summary = {"suite": "pipeline", "metrics": {"accuracy": 0.84, "leakage_rate": 0.0}}
    baseline = {"suite": "pipeline", "metrics": {"accuracy": 0.85, "leakage_rate": 0.0}}

    assert gate.check(summary, baseline) == []
    assert gate.check(
        {"suite": "pipeline", "metrics": {"accuracy": 0.80, "leakage_rate": 0.0}},
        {"suite": "pipeline", "metrics": {"accuracy": 0.90, "leakage_rate": 0.0}},
    )
    assert gate.check(
        {"suite": "permission", "metrics": {"accuracy": 1.0, "leakage_rate": 0.1}}, None
    )
