"""Publish the latest evaluation summary as a Markdown table, a Benchmarks JSON and README results.

Reads evals/results/<run_id>.json (the newest one, checkpoints ignored), writes
evals/RESULTS.md and frontend/src/site/data/benchmarks.json, and replaces the block between
the markers in README.md.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = REPO_ROOT / "evals" / "results"
RESULTS_MD = REPO_ROOT / "evals" / "RESULTS.md"
BENCHMARKS_JSON = REPO_ROOT / "frontend" / "src" / "site" / "data" / "benchmarks.json"
README = REPO_ROOT / "README.md"
START = "<!-- eval-results:start -->"
END = "<!-- eval-results:end -->"


def latest_summary(results_dir: Path = RESULTS_DIR) -> dict[str, Any]:
    candidates = [
        path for path in results_dir.glob("*.json") if not path.name.endswith(".checkpoint.jsonl")
    ]
    if not candidates:
        raise SystemExit(f"No evaluation summary found in {results_dir}")
    newest = max(candidates, key=lambda path: path.stat().st_mtime)
    return json.loads(newest.read_text(encoding="utf-8"))


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def markdown_table(summary: dict[str, Any]) -> str:
    m = summary["metrics"]
    rows = [
        "| Suite | Model | Prompt | Sample | Accuracy | Leakage | Correct denial "
        "| Tokens per question | p95 latency | Run date |",
        "|---|---|---|---|---|---|---|---|---|---|",
        (
            "| {suite} | {model} | {prompt} | {n} | {acc} | {leak} | {deny} | {tok} "
            "| {p95} ms | {date} |"
        ).format(
            suite=summary["suite"],
            model=summary["model"],
            prompt=summary["prompt_version"],
            n=m["sample_size"],
            acc=_pct(m["accuracy"]),
            leak=_pct(m["leakage_rate"]),
            deny=_pct(m["correct_denial_rate"]),
            tok=m["avg_tokens_per_question"] if m["avg_tokens_per_question"] is not None else "n/a",
            p95=m["p95_latency_ms"] if m["p95_latency_ms"] is not None else "n/a",
            date=summary["finished_at"][:10],
        ),
    ]
    taxonomy = m.get("error_taxonomy") or {}
    if taxonomy:
        rows.append("")
        rows.append("| Failure category | Count |")
        rows.append("|---|---|")
        rows.extend(f"| {name} | {count} |" for name, count in sorted(taxonomy.items()))
    return "\n".join(rows) + "\n"


def benchmarks_payload(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": summary["run_id"],
        "suite": summary["suite"],
        "model": summary["model"],
        "prompt_version": summary["prompt_version"],
        "run_date": summary["finished_at"][:10],
        "metrics": summary["metrics"],
    }


def update_readme(table: str, readme: Path = README) -> bool:
    text = readme.read_text(encoding="utf-8")
    if START not in text or END not in text:
        return False
    head, rest = text.split(START, 1)
    _, tail = rest.split(END, 1)
    readme.write_text(f"{head}{START}\n{table}{END}{tail}", encoding="utf-8")
    return True


def main() -> int:
    summary = latest_summary()
    table = markdown_table(summary)
    RESULTS_MD.write_text(table, encoding="utf-8")
    BENCHMARKS_JSON.parent.mkdir(parents=True, exist_ok=True)
    BENCHMARKS_JSON.write_text(json.dumps(benchmarks_payload(summary), indent=2), encoding="utf-8")
    updated = update_readme(table)
    print(f"Wrote {RESULTS_MD.name} and {BENCHMARKS_JSON.name}; README updated: {updated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
