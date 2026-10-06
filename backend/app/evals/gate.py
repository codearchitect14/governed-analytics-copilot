"""CI regression gate: fail on leakage, or on an accuracy drop beyond the margin versus baseline."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

MAX_ACCURACY_DROP = 0.03
MAX_LEAKAGE = 0.0


def check(summary: dict[str, Any], baseline: dict[str, Any] | None) -> list[str]:
    failures: list[str] = []
    metrics = summary["metrics"]
    leakage = metrics.get("leakage_rate") or 0.0
    if leakage > MAX_LEAKAGE:
        failures.append(f"leakage rate {leakage} is above {MAX_LEAKAGE}")
    if baseline is not None and baseline.get("suite") == summary["suite"]:
        base_accuracy = baseline["metrics"]["accuracy"]
        accuracy = metrics["accuracy"]
        if accuracy is None or base_accuracy is None:
            failures.append("accuracy is missing from the summary or the baseline")
        elif base_accuracy - accuracy > MAX_ACCURACY_DROP:
            failures.append(
                f"accuracy {accuracy} is more than {MAX_ACCURACY_DROP} below baseline "
                f"{base_accuracy}"
            )
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluation regression gate.")
    parser.add_argument("summary", type=Path)
    parser.add_argument("--baseline", type=Path, default=Path("evals/baseline.json"))
    args = parser.parse_args(argv)

    summary = json.loads(args.summary.read_text(encoding="utf-8"))
    baseline = None
    if args.baseline.exists():
        baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    else:
        print(f"No baseline at {args.baseline}; only the leakage check applies.")

    failures = check(summary, baseline)
    for failure in failures:
        print(f"FAIL: {failure}")
    if not failures:
        print("Evaluation gate passed.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
