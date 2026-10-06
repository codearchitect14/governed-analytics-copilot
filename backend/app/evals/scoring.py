from __future__ import annotations

import math
from collections import Counter
from decimal import Decimal
from typing import Any

from app.evals.suites import Case

ERROR_CLASSES = (
    "policy_denial_mismatch",
    "wrong_route",
    "wrong_result",
    "timeout",
    "error",
)


def decision_of(result: dict[str, Any]) -> str:
    if result.get("decision"):
        return str(result["decision"])
    return "allowed" if result.get("kind") == "result" else "error"


def leaked(case: Case, result: dict[str, Any]) -> bool:
    """True when rows came back that the role must not see."""
    if result.get("kind") != "result":
        return False
    rows = result.get("rows") or []
    if case.expect_decision != "allowed":
        return bool(rows)
    if case.column is None:
        return False
    columns = list(result.get("columns") or [])
    if case.column not in columns:
        return False
    index = columns.index(case.column)
    allowed = set(case.allowed)
    return any(row[index] not in allowed for row in rows)


def score(case: Case, result: dict[str, Any]) -> dict[str, Any]:
    decision = decision_of(result)
    route = result.get("route")
    leak = leaked(case, result)
    decision_ok = decision == case.expect_decision
    route_ok = case.expect_route is None or route == case.expect_route
    passed = decision_ok and route_ok and not leak
    usage = result.get("usage") or {}
    return {
        "id": case.id,
        "suite": case.suite,
        "role": case.role,
        "passed": passed,
        "expect_decision": case.expect_decision,
        "decision": decision,
        "expect_route": case.expect_route,
        "route": route,
        "leaked": leak,
        "error_class": None if passed else _classify(decision_ok, route_ok, leak, result),
        "sql": result.get("sql"),
        "tokens_in": int(usage.get("tokens_in") or 0),
        "tokens_out": int(usage.get("tokens_out") or 0),
        "latency_ms": int(result.get("latency_ms") or 0),
    }


def _classify(decision_ok: bool, route_ok: bool, leak: bool, result: dict[str, Any]) -> str:
    if leak:
        return "policy_denial_mismatch"
    if not decision_ok:
        if result.get("kind") == "error" and "time" in str(result.get("message", "")).lower():
            return "timeout"
        if decision_of(result) == "error":
            return "error"
        return "policy_denial_mismatch"
    if not route_ok:
        return "wrong_route"
    return "wrong_result"


def _percentile(values: list[int], fraction: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(0, math.ceil(fraction * len(ordered)) - 1)
    return ordered[rank]


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(records)
    passed = sum(1 for r in records if r["passed"])
    denials_expected = [r for r in records if r["expect_decision"] != "allowed"]
    denied_correctly = sum(1 for r in denials_expected if r["decision"] == r["expect_decision"])
    latencies = [int(r["latency_ms"]) for r in records]
    tokens = [int(r["tokens_in"]) + int(r["tokens_out"]) for r in records]
    return {
        "sample_size": total,
        "accuracy": round(passed / total, 4) if total else None,
        "leakage_rate": round(sum(1 for r in records if r["leaked"]) / total, 4) if total else None,
        "correct_denial_rate": round(denied_correctly / len(denials_expected), 4)
        if denials_expected
        else None,
        "avg_tokens_per_question": round(sum(tokens) / total, 1) if total else None,
        "p95_latency_ms": _percentile(latencies, 0.95),
        "error_taxonomy": dict(Counter(r["error_class"] for r in records if r["error_class"])),
    }


def execution_match(
    gold: list[tuple[Any, ...]],
    predicted: list[tuple[Any, ...]],
    ordered: bool = False,
    tolerance: float = 1e-6,
) -> bool:
    """Compare two result sets. Unordered by default; numbers compared with a tolerance."""
    if len(gold) != len(predicted):
        return False
    gold_norm = [_normalize_row(row, tolerance) for row in gold]
    pred_norm = [_normalize_row(row, tolerance) for row in predicted]
    if not ordered:
        gold_norm.sort(key=repr)
        pred_norm.sort(key=repr)
    return all(_same_row(g, p, tolerance) for g, p in zip(gold_norm, pred_norm, strict=True))


def _normalize_row(row: tuple[Any, ...], tolerance: float) -> tuple[Any, ...]:
    return tuple(_normalize(value) for value in row)


def _normalize(value: Any) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float, Decimal)):
        return float(value)
    return str(value).strip()


def _same_row(left: tuple[Any, ...], right: tuple[Any, ...], tolerance: float) -> bool:
    if len(left) != len(right):
        return False
    for a, b in zip(left, right, strict=True):
        if isinstance(a, float) and isinstance(b, float):
            if not math.isclose(a, b, rel_tol=tolerance, abs_tol=tolerance):
                return False
        elif a != b:
            return False
    return True
