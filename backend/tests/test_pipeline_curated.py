"""Curated pipeline questions across every route type (dataset/golden/pipeline_questions_v1.jsonl).

Requires the same environment as test_pipeline_live.py. Latency is measured per question and
reported in the test output; it is not asserted, because it depends on the machine.
"""

from __future__ import annotations

import json
import statistics
import time
from dataclasses import replace
from pathlib import Path

import pytest

from tests.test_pipeline_live import (  # noqa: F401 - fixture
    ScriptedGateway,
    _run,
    _user,
    _user_with_scopes,
    live,
)

CURATED = Path(__file__).resolve().parents[2] / "dataset" / "golden" / "pipeline_questions_v1.jsonl"
ROLE_EMAILS = {
    "executive": "executive@meridian.example",
    "analyst": "analyst@meridian.example",
    "admin": "admin@meridian.example",
    "category_manager": "category.manager@meridian.example",
    "seller_partner": "seller.partner@meridian.example",
}


def _load() -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in CURATED.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _user_for(role: str):  # type: ignore[no-untyped-def]
    if role == "regional_manager":
        return _user_with_scopes("regional_manager", {"regions": ["SP", "RJ", "MG", "ES"]})
    return _user(ROLE_EMAILS[role])


def test_curated_set_has_twenty_questions_across_route_types() -> None:
    items = _load()

    assert len(items) == 20
    routes = {str(item["expect_route"]) for item in items}
    assert {"rule", "llm_plan", "llm_sql", "none"} <= routes


def test_curated_questions_run_end_to_end(live) -> None:  # type: ignore[no-untyped-def]
    timings: list[float] = []
    failures: list[str] = []
    for item in _load():
        script = item.get("script") or []
        services = replace(live, gateway=ScriptedGateway(*script) if script else None)  # type: ignore[arg-type]
        started = time.perf_counter()
        result = _run(services, str(item["question"]), _user_for(str(item["role"])))
        if str(item["expect_route"]) == "rule":
            timings.append((time.perf_counter() - started) * 1000)
        decision = result.get("decision") or ("allowed" if result["kind"] == "result" else "error")
        route = result.get("route")
        if decision != item["expect_decision"]:
            failures.append(
                f"{item['id']}: decision {decision} != {item['expect_decision']} ({result.get('message')})"
            )
        if (
            result["kind"] == "result"
            and str(item["expect_route"]) != "none"
            and route != item["expect_route"]
        ):
            failures.append(f"{item['id']}: route {route} != {item['expect_route']}")
    if timings:
        print(
            f"\nrule route latency ms: median={statistics.median(timings):.0f} max={max(timings):.0f} n={len(timings)}"
        )
    assert not failures, "\n".join(failures)


def test_curated_denials_are_audited(live) -> None:  # type: ignore[no-untyped-def]
    denied = [item for item in _load() if item["expect_decision"] == "denied"]
    for item in denied:
        script = item.get("script") or []
        services = replace(live, gateway=ScriptedGateway(*script) if script else None)  # type: ignore[arg-type]
        result = _run(services, str(item["question"]), _user_for(str(item["role"])))
        assert result.get("audit_id") is not None, item["id"]
        assert pytest  # keeps the import used
