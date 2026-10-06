from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

GOLDEN_DIR = Path(__file__).resolve().parents[3] / "dataset" / "golden"

SUITE_FILES: dict[str, str] = {
    "pipeline": "pipeline_questions_v1.jsonl",
    "permission": "permission_tests.jsonl",
    "adversarial": "adversarial.jsonl",
}


@dataclass(frozen=True)
class Case:
    id: str
    suite: str
    role: str
    question: str
    expect_decision: str
    expect_route: str | None
    scopes: dict[str, Any]
    column: str | None
    allowed: tuple[str, ...]
    script: tuple[str, ...]
    raw: dict[str, Any]


def load_suite(name: str, golden_dir: Path = GOLDEN_DIR) -> list[Case]:
    if name not in SUITE_FILES:
        raise ValueError(f"unknown suite {name!r}; expected one of {sorted(SUITE_FILES)}")
    path = golden_dir / SUITE_FILES[name]
    rows = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    return [_to_case(name, row) for row in rows]


def _to_case(suite: str, row: dict[str, Any]) -> Case:
    return Case(
        id=str(row["id"]),
        suite=suite,
        role=str(row["role"]),
        question=str(row["question"]),
        expect_decision=str(row.get("expect_decision", "allowed")),
        expect_route=row.get("expect_route"),
        scopes=dict(row.get("scopes") or {}),
        column=row.get("column"),
        allowed=tuple(row.get("allowed") or ()),
        script=tuple(row.get("script") or ()),
        raw=row,
    )


def select(
    cases: Sequence[Case],
    limit: int | None = None,
    stratified: bool = False,
    stratum: Callable[[Case], str] = lambda case: case.expect_decision,
) -> list[Case]:
    """Deterministic subset. Stratified selection takes cases round robin across strata."""
    if limit is None or limit >= len(cases):
        return list(cases)
    if not stratified:
        return list(cases[:limit])
    buckets: dict[str, list[Case]] = defaultdict(list)
    for case in cases:
        buckets[stratum(case)].append(case)
    chosen: list[Case] = []
    keys = sorted(buckets)
    index = 0
    while len(chosen) < limit:
        progressed = False
        for key in keys:
            if index < len(buckets[key]) and len(chosen) < limit:
                chosen.append(buckets[key][index])
                progressed = True
        if not progressed:
            break
        index += 1
    return chosen
