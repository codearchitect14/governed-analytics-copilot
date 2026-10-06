"""Dagster code location for the Meridian Data Copilot pipelines.

Evaluation runs execute the backend runner in a subprocess so this code location does not need
the application package. The command is taken from EVAL_RUNNER_COMMAND.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path

from dagster import (
    AssetExecutionContext,
    DefaultScheduleStatus,
    Definitions,
    MultiPartitionsDefinition,
    ScheduleDefinition,
    StaticPartitionsDefinition,
    asset,
    define_asset_job,
    job,
    op,
)

REPO_ROOT = Path(os.environ.get("MERIDIAN_REPO_ROOT", Path(__file__).resolve().parents[3]))
GOLDEN_DIR = REPO_ROOT / "dataset" / "golden"
RUNNER = os.environ.get("EVAL_RUNNER_COMMAND", "python -m app.evals.runner")

MODELS = StaticPartitionsDefinition(["groq:openai/gpt-oss-20b", "gemini:gemini-2.5-flash"])
PROMPTS = StaticPartitionsDefinition(["v1"])
EVAL_PARTITIONS = MultiPartitionsDefinition({"model": MODELS, "prompt_version": PROMPTS})


def _run_runner(args: list[str], context: AssetExecutionContext | None = None) -> None:
    command = [*shlex.split(RUNNER), *args]
    completed = subprocess.run(  # noqa: S603
        command, cwd=REPO_ROOT / "backend", capture_output=True, text=True, check=False
    )
    message = completed.stdout[-4000:] or completed.stderr[-4000:]
    if context is not None:
        context.log.info(message)
    if completed.returncode != 0:
        raise RuntimeError(
            f"evaluation runner failed ({completed.returncode}): {completed.stderr[-2000:]}"
        )


@asset(group_name="evaluation")
def eval_dataset_olist(context: AssetExecutionContext) -> None:
    """Golden question set. Gold SQL is not committed yet, so only route and decision are scored."""
    path = GOLDEN_DIR / "pipeline_questions_v1.jsonl"
    count = sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    context.add_output_metadata({"questions": count, "path": str(path)})


@asset(group_name="evaluation", partitions_def=EVAL_PARTITIONS, deps=[eval_dataset_olist])
def eval_run(context: AssetExecutionContext) -> None:
    keys = context.partition_key.keys_by_dimension
    _run_runner(
        [
            "--suite",
            "pipeline",
            "--model",
            keys["model"],
            "--prompt-version",
            keys["prompt_version"],
        ],
        context,
    )


@asset(group_name="evaluation", deps=[eval_run])
def eval_report(context: AssetExecutionContext) -> None:
    completed = subprocess.run(  # noqa: S603
        [sys.executable, str(REPO_ROOT / "scripts" / "publish_results.py")],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    context.log.info(completed.stdout or completed.stderr)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr[-2000:])


@op
def nightly_small_eval() -> None:
    _run_runner(
        [
            "--suite",
            "pipeline",
            "--limit",
            "50",
            "--stratified",
            "--model",
            "groq:openai/gpt-oss-20b",
        ]
    )
    _run_runner(["--suite", "permission", "--model", "groq:openai/gpt-oss-20b"])
    _run_runner(["--suite", "adversarial", "--model", "groq:openai/gpt-oss-20b"])


@job
def nightly_regression() -> None:
    nightly_small_eval()


nightly_regression_schedule = ScheduleDefinition(
    job=nightly_regression,
    cron_schedule="0 3 * * *",
    default_status=DefaultScheduleStatus.STOPPED,
)

evaluation_job = define_asset_job(
    "evaluation_job", selection=["eval_dataset_olist", "eval_run", "eval_report"]
)

defs = Definitions(
    assets=[eval_dataset_olist, eval_run, eval_report],
    jobs=[evaluation_job, nightly_regression],
    schedules=[nightly_regression_schedule],
)
