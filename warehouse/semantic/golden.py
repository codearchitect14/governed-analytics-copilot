"""Golden check for the semantic layer.

For every plan fixture, MetricFlow compiles and executes the plan, and the gold SQL is executed
against the same analytics marts as the read only executor role. The two result sets must match.

Usage (from the repository root, with .env loaded):
    uv run --package governed-analytics-warehouse python warehouse/semantic/golden.py
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import psycopg

REPO_ROOT = Path(__file__).resolve().parents[2]
PROJECT_DIR = REPO_ROOT / "warehouse" / "dbt_project"
FIXTURES = REPO_ROOT / "dataset" / "semantic_seed" / "plan_fixtures.jsonl"
MF_TIMEOUT_SECONDS = 120
DATE_PREFIX = re.compile(r"^(\d{4}-\d{2}-\d{2})")
NUMERIC_PLACES = 6
DATE_LENGTH = 10


@dataclass
class PlanFixture:
    id: str
    question: str
    plan: dict[str, Any]
    gold_sql: str


@dataclass
class Comparison:
    fixture_id: str
    matched: bool
    message: str
    mf_rows: int = 0
    gold_rows: int = 0
    details: list[str] = field(default_factory=list)


def load_fixtures(path: Path = FIXTURES) -> list[PlanFixture]:
    fixtures: list[PlanFixture] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        fixtures.append(
            PlanFixture(
                id=record["id"],
                question=record["question"],
                plan=record["plan"],
                gold_sql=record["gold_sql"],
            )
        )
    return fixtures


def build_mf_args(plan: dict[str, Any], csv_path: Path) -> list[str]:
    """Translate a plan into a `mf query` command line."""
    args = ["mf", "query", "--metrics", ",".join(plan["metrics"]), "--csv", str(csv_path)]
    if plan.get("group_by"):
        args += ["--group-by", ",".join(plan["group_by"])]
    for condition in plan.get("where", []):
        args += ["--where", condition]
    if plan.get("order_by"):
        args += ["--order", ",".join(plan["order_by"])]
    if plan.get("limit"):
        args += ["--limit", str(plan["limit"])]
    return args


def run_metricflow(plan: dict[str, Any], csv_path: Path) -> tuple[list[str], list[list[str]]]:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    command = build_mf_args(plan, csv_path)
    completed = subprocess.run(  # noqa: S603 - fixed argument list, no shell
        command,
        cwd=PROJECT_DIR,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=MF_TIMEOUT_SECONDS,
        check=False,
    )
    if completed.returncode != 0 or not csv_path.exists():
        raise RuntimeError(
            f"mf query failed (exit {completed.returncode}): {completed.stderr[-800:]}"
        )
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        # mf writes \r\r\n line endings on Windows, which yields empty rows between records
        rows = [row for row in csv.reader(handle) if any(cell.strip() for cell in row)]
    return rows[0], rows[1:]


def run_gold(
    connection: psycopg.Connection[tuple[Any, ...]], sql: str
) -> tuple[list[str], list[list[str]]]:
    with connection.cursor() as cursor:
        cursor.execute(sql)  # type: ignore[arg-type] - gold SQL is curated and reviewed
        if cursor.description is None:
            raise RuntimeError("gold SQL returned no result set")
        columns = [column.name for column in cursor.description]
        rows = [[_render(value) for value in row] for row in cursor.fetchall()]
    return columns, rows


def _render(value: object) -> str:
    if value is None:
        return ""
    return str(value)


def normalize_cell(value: str) -> str:
    """Make numeric and date representations comparable between MetricFlow and PostgreSQL."""
    text = value.strip()
    if text == "":
        return ""
    date_match = DATE_PREFIX.match(text)
    if date_match and (
        len(text) == DATE_LENGTH or text[DATE_LENGTH : DATE_LENGTH + 1] in {"T", " "}
    ):
        return date_match.group(1)
    try:
        return f"{round(float(text), NUMERIC_PLACES):.{NUMERIC_PLACES}f}"
    except ValueError:
        return text


def compare_results(
    fixture_id: str,
    mf_columns: list[str],
    mf_rows: list[list[str]],
    gold_columns: list[str],
    gold_rows: list[list[str]],
) -> Comparison:
    if sorted(mf_columns) != sorted(gold_columns):
        return Comparison(
            fixture_id,
            False,
            f"column mismatch: mf={mf_columns} gold={gold_columns}",
            len(mf_rows),
            len(gold_rows),
        )

    order = [gold_columns.index(column) for column in mf_columns]
    gold_aligned = [[row[index] for index in order] for row in gold_rows]

    def canonical(rows: list[list[str]]) -> list[tuple[str, ...]]:
        return sorted(tuple(normalize_cell(cell) for cell in row) for row in rows)

    left = canonical(mf_rows)
    right = canonical(gold_aligned)
    if len(left) != len(right):
        return Comparison(
            fixture_id,
            False,
            f"row count differs: mf={len(left)} gold={len(right)}",
            len(left),
            len(right),
        )
    differences = [f"mf={a} gold={b}" for a, b in zip(left, right, strict=True) if a != b][:5]
    if differences:
        return Comparison(
            fixture_id,
            False,
            "values differ",
            len(left),
            len(right),
            differences,
        )
    return Comparison(fixture_id, True, "match", len(left), len(right))


def check_fixture(
    fixture: PlanFixture, connection: psycopg.Connection[tuple[Any, ...]]
) -> Comparison:
    with tempfile.TemporaryDirectory() as tmp:
        csv_path = Path(tmp) / "result.csv"
        try:
            mf_columns, mf_rows = run_metricflow(fixture.plan, csv_path)
        except (RuntimeError, subprocess.TimeoutExpired) as error:
            return Comparison(fixture.id, False, f"metricflow error: {error}")
    gold_columns, gold_rows = run_gold(connection, fixture.gold_sql)
    return compare_results(fixture.id, mf_columns, mf_rows, gold_columns, gold_rows)


def run_all(database_url: str, only: Sequence[str] | None = None) -> list[Comparison]:
    selected = [f for f in load_fixtures() if not only or f.id in only]
    results: list[Comparison] = []
    with psycopg.connect(database_url, autocommit=True) as connection:
        for fixture in selected:
            results.append(check_fixture(fixture, connection))
    return results


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ids", nargs="*", help="Run only these fixture ids")
    args = parser.parse_args(argv)

    database_url = os.environ.get("WAREHOUSE_RO_DATABASE_URL", "")
    if not database_url:
        print(
            "WAREHOUSE_RO_DATABASE_URL is not set. Copy .env.example to .env first.",
            file=sys.stderr,
        )
        return 2

    results = run_all(database_url, args.ids)
    failures = [result for result in results if not result.matched]
    for result in results:
        status = "PASS" if result.matched else "FAIL"
        print(
            f"{status} {result.fixture_id}  mf_rows={result.mf_rows} "
            f"gold_rows={result.gold_rows}  {result.message}"
        )
        for detail in result.details:
            print(f"      {detail}")
    print(f"{len(results) - len(failures)}/{len(results)} plans match the gold results")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
