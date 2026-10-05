"""MetricFlow compiler wrapper.

MetricFlow turns a validated plan into SQL deterministically. This module only builds the
command line from a MetricPlan, runs the `mf` executable with a timeout, and reads the result.
No shell is used, and every value rendered into a where clause is quoted here.
"""

from __future__ import annotations

import csv
import os
import subprocess
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from app.semantic.plan import TIME_DIMENSION, Filter, MetricPlan, TimeWindow


class CompilerError(RuntimeError):
    """MetricFlow could not compile or run the plan."""


@dataclass(frozen=True)
class QueryResult:
    columns: list[str]
    rows: list[list[str]]


def _quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def render_value(value: object) -> str:
    if isinstance(value, bool):
        raise CompilerError("boolean filter values are not supported")
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return _quote(value)
    if isinstance(value, list):
        return "(" + ", ".join(render_value(item) for item in value) + ")"
    raise CompilerError(f"unsupported filter value type {type(value).__name__}")


def dimension_expression(name: str, grain: str = "day") -> str:
    """Jinja expression MetricFlow understands for a dimension or a time dimension."""
    if name == TIME_DIMENSION or name.startswith(f"{TIME_DIMENSION}__"):
        return f"{{{{ TimeDimension('{TIME_DIMENSION}', '{grain}') }}}}"
    return f"{{{{ Dimension('{name}') }}}}"


def render_filter(filter_: Filter) -> str:
    expression = dimension_expression(filter_.dimension)
    sql_operator = "IN" if filter_.operator == "in" else filter_.operator
    return f"{expression} {sql_operator} {render_value(filter_.value)}"


def render_time_window(window: TimeWindow) -> list[str]:
    lower = dimension_expression(TIME_DIMENSION, window.grain)
    return [
        f"{lower} >= {_quote(window.start.isoformat())}",
        f"{lower} < {_quote(window.end.isoformat())}",
    ]


def build_arguments(
    plan: MetricPlan,
    *,
    executable: str,
    csv_path: Path | None = None,
    explain: bool = False,
) -> list[str]:
    """Return the full `mf query` argument list for a plan. Never passed through a shell."""
    arguments = [executable, "query", "--metrics", ",".join(plan.metrics)]
    if plan.group_by:
        arguments += ["--group-by", ",".join(plan.group_by)]

    where: list[str] = [render_filter(item) for item in plan.filters]
    if plan.time_window is not None:
        where += render_time_window(plan.time_window)
    for clause in where:
        arguments += ["--where", clause]

    if plan.order_by:
        arguments += ["--order", ",".join(plan.order_by)]
    if plan.limit is not None:
        arguments += ["--limit", str(plan.limit)]
    if explain:
        arguments.append("--explain")
    elif csv_path is not None:
        arguments += ["--csv", str(csv_path)]
    return arguments


def extract_sql(explain_output: str) -> str:
    """Return the SQL block from `mf query --explain` output."""
    lines = explain_output.splitlines()
    for index, line in enumerate(lines):
        if line.startswith("SQL (") or line.startswith("🔎 SQL ("):
            sql_lines = [item for item in lines[index + 1 :] if item.strip()]
            return "\n".join(sql_lines).strip()
    raise CompilerError("MetricFlow explain output did not contain a SQL block")


class MetricFlowCompiler:
    """Runs `mf` from the dbt project directory, with a timeout and a clean environment."""

    def __init__(
        self,
        project_dir: Path,
        *,
        executable: str = "mf",
        timeout_seconds: float = 60.0,
        profiles_dir: Path | None = None,
    ) -> None:
        self.project_dir = project_dir
        self.executable = executable
        self.timeout_seconds = timeout_seconds
        self.profiles_dir = profiles_dir or project_dir

    def _environment(self) -> dict[str, str]:
        return {
            **os.environ,
            "DBT_PROFILES_DIR": str(self.profiles_dir),
            "PYTHONIOENCODING": "utf-8",
        }

    def _run(self, arguments: Sequence[str]) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(  # noqa: S603 - fixed argument list, no shell
                list(arguments),
                cwd=self.project_dir,
                env=self._environment(),
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=self.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise CompilerError(
                f"MetricFlow did not finish within {self.timeout_seconds:.0f} seconds"
            ) from error

    def explain(self, plan: MetricPlan) -> str:
        completed = self._run(build_arguments(plan, executable=self.executable, explain=True))
        if completed.returncode != 0:
            raise CompilerError(f"MetricFlow failed: {completed.stderr[-500:]}")
        return extract_sql(completed.stdout)

    def run(self, plan: MetricPlan) -> QueryResult:
        with tempfile.TemporaryDirectory() as directory:
            csv_path = Path(directory) / "result.csv"
            completed = self._run(
                build_arguments(plan, executable=self.executable, csv_path=csv_path)
            )
            if completed.returncode != 0 or not csv_path.exists():
                raise CompilerError(f"MetricFlow failed: {completed.stderr[-500:]}")
            with csv_path.open("r", encoding="utf-8", newline="") as handle:
                rows = [row for row in csv.reader(handle) if any(cell.strip() for cell in row)]
        if not rows:
            return QueryResult(columns=[], rows=[])
        return QueryResult(columns=rows[0], rows=rows[1:])
