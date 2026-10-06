"""Run a golden suite through the production pipeline.

Example: python -m app.evals.runner --suite permission --model groq:openai/gpt-oss-20b
Runs checkpoint after every question, so an interrupted run continues with --resume <run_id>.
"""

from __future__ import annotations

import argparse
import json
import time
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, text

from app.auth.service import CurrentUser, RequestContext
from app.core.config import get_settings
from app.core.security import hash_password
from app.db.engine import get_engine
from app.evals.scoring import score, summarize
from app.evals.store import Checkpoint, ResponseCache
from app.evals.suites import Case, load_suite, select
from app.llm.providers import LLMRequest, LLMResponse
from app.pipeline.orchestrator import QueryPipeline, Services
from app.pipeline.services import build_services

REPO_ROOT = Path(__file__).resolve().parents[3]
RESULTS_DIR = REPO_ROOT / "evals" / "results"
CACHE_DIR = REPO_ROOT / "evals" / "cache"
REQUEST_CONTEXT = RequestContext(client_ip="127.0.0.1", request_id="eval-run")
ROLE_EMAILS = {
    "executive": "executive@meridian.example",
    "analyst": "analyst@meridian.example",
    "seller_partner": "seller.partner@meridian.example",
    "admin": "admin@meridian.example",
    "regional_manager": "regional.manager@meridian.example",
}


class ScriptedGateway:
    """Replays canned model outputs in order, so adversarial cases do not need a live model."""

    def __init__(self, *texts: str) -> None:
        self._texts = list(texts)

    def complete(self, request: LLMRequest) -> LLMResponse:
        output = (
            self._texts.pop(0)
            if self._texts
            else '{"intent": "refuse", "refusal_reason": "no script"}'
        )
        return LLMResponse(
            text=output,
            provider="scripted",
            model="scripted",
            tokens_in=0,
            tokens_out=0,
            latency_ms=0,
        )


def _user_by_email(engine: Engine, email: str) -> CurrentUser:
    with engine.connect() as connection:
        row = (
            connection.execute(
                text("SELECT id, email, full_name, role, scopes FROM app.users WHERE email = :e"),
                {"e": email},
            )
            .mappings()
            .one()
        )
    return CurrentUser(
        id=row["id"],
        email=row["email"],
        full_name=row["full_name"],
        role=row["role"],
        policy_version=1,
        scopes=dict(row["scopes"] or {}),
    )


def _user_for_role(engine: Engine, role: str) -> CurrentUser:
    return _user_by_email(engine, ROLE_EMAILS[role])


def _scoped_user(engine: Engine, role: str, scopes: dict[str, Any]) -> CurrentUser:
    email = f"eval-{uuid.uuid4().hex[:10]}@meridian.example"
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO app.users (email, full_name, password_hash, role, scopes)
                VALUES (:email, 'Evaluation User', :hash, :role, CAST(:scopes AS JSONB))
                """
            ),
            {
                "email": email,
                "hash": hash_password(uuid.uuid4().hex),
                "role": role,
                "scopes": json.dumps(scopes),
            },
        )
    return _user_by_email(engine, email)


def execute_case(services: Services, case: Case) -> dict[str, Any]:
    if case.suite == "adversarial":
        services = replace(services, gateway=ScriptedGateway(*case.script))  # type: ignore[arg-type]
        user = _user_for_role(services.app_engine, case.role)
    elif case.suite == "permission":
        user = _scoped_user(services.app_engine, case.role, case.scopes)
    else:
        user = _user_for_role(services.app_engine, case.role)

    started = time.perf_counter()
    events = list(QueryPipeline(services).run(case.question, user, REQUEST_CONTEXT))
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    final = events[-1]
    return {"kind": final.kind, "latency_ms": elapsed_ms, **final.data}


def cache_key(case: Case) -> str:
    return json.dumps(
        [case.id, case.role, case.scopes, case.question, list(case.script)], sort_keys=True
    )


def run_suite(
    services: Services,
    suite: str,
    cases: list[Case],
    *,
    run_id: str,
    model: str,
    prompt_version: str,
    use_cache: bool,
    results_dir: Path = RESULTS_DIR,
    cache_dir: Path = CACHE_DIR,
) -> dict[str, Any]:
    checkpoint = Checkpoint(results_dir, run_id)
    done = checkpoint.load()
    cache = ResponseCache(cache_dir, model, prompt_version)
    started_at = datetime.now(UTC)
    records: list[dict[str, Any]] = []

    for case in cases:
        if case.id in done:
            records.append(done[case.id])
            continue
        cached = cache.get(cache_key(case)) if use_cache else None
        result = cached if cached is not None else execute_case(services, case)
        if use_cache and cached is None:
            cache.put(cache_key(case), result)
        record = score(case, result)
        checkpoint.append(record)
        records.append(record)

    finished_at = datetime.now(UTC)
    return {
        "run_id": run_id,
        "suite": suite,
        "model": model,
        "prompt_version": prompt_version,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "metrics": summarize(records),
        "records": records,
    }


def persist(engine: Engine, summary: dict[str, Any]) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO app.eval_runs (id, suite, model, prompt_version, sample_size, status,
                    metrics, started_at, finished_at)
                VALUES (CAST(:id AS UUID), :suite, :model, :prompt, :n, 'succeeded',
                    CAST(:metrics AS JSONB), :started, :finished)
                ON CONFLICT (id) DO UPDATE SET status = 'succeeded', metrics = EXCLUDED.metrics,
                    sample_size = EXCLUDED.sample_size, finished_at = EXCLUDED.finished_at
                """
            ),
            {
                "id": summary["run_id"],
                "suite": summary["suite"],
                "model": summary["model"],
                "prompt": summary["prompt_version"],
                "n": summary["metrics"]["sample_size"],
                "metrics": json.dumps(summary["metrics"]),
                "started": summary["started_at"],
                "finished": summary["finished_at"],
            },
        )
        connection.execute(
            text("DELETE FROM app.eval_results WHERE run_id = CAST(:id AS UUID)"),
            {"id": summary["run_id"]},
        )
        for record in summary["records"]:
            connection.execute(
                text(
                    """
                    INSERT INTO app.eval_results (run_id, question_id, passed, route, generated_sql,
                        error_class, tokens_in, tokens_out, latency_ms, details)
                    VALUES (CAST(:run AS UUID), :qid, :passed, :route, :sql, :err, :tin, :tout,
                        :lat, CAST(:details AS JSONB))
                    """
                ),
                {
                    "run": summary["run_id"],
                    "qid": record["id"],
                    "passed": record["passed"],
                    "route": record.get("route"),
                    "sql": record.get("sql"),
                    "err": record.get("error_class"),
                    "tin": record["tokens_in"],
                    "tout": record["tokens_out"],
                    "lat": record["latency_ms"],
                    "details": json.dumps(
                        {"role": record["role"], "leaked": record["leaked"]}, default=str
                    ),
                },
            )


def write_summary(summary: dict[str, Any], results_dir: Path = RESULTS_DIR) -> Path:
    results_dir.mkdir(parents=True, exist_ok=True)
    path = results_dir / f"{summary['run_id']}.json"
    path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run an evaluation suite through the pipeline.")
    parser.add_argument("--suite", choices=["pipeline", "permission", "adversarial"], required=True)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--stratified", action="store_true")
    parser.add_argument(
        "--resume", default=None, help="run id whose checkpoint should be continued"
    )
    parser.add_argument(
        "--model", required=True, help="label stored with the run, e.g. groq:openai/gpt-oss-20b"
    )
    parser.add_argument("--prompt-version", default="v1")
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--no-db", action="store_true", help="write only the JSON summary")
    args = parser.parse_args(argv)

    run_id = args.resume or str(uuid.uuid4())
    settings = get_settings()
    services = build_services(settings)
    services = replace(services, app_engine=get_engine(settings))

    cases = select(
        load_suite(args.suite),
        limit=args.limit,
        stratified=args.stratified,
        stratum=lambda case: case.role if args.suite == "pipeline" else case.expect_decision,
    )
    summary = run_suite(
        services,
        args.suite,
        cases,
        run_id=run_id,
        model=args.model,
        prompt_version=args.prompt_version,
        use_cache=not args.no_cache,
    )
    path = write_summary(summary)
    if not args.no_db:
        persist(services.app_engine, summary)
    print(
        json.dumps({"run_id": run_id, "summary": path.as_posix(), **summary["metrics"]}, indent=2)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
