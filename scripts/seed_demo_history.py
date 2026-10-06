"""Backfill 90 days of synthetic operations history (flagged is_synthetic = true).

Usage (from the repository root, after migrations):
    uv run --package governed-analytics-backend python scripts/seed_demo_history.py --days 90
"""

import sys

from app.ops.seed_history import main

if __name__ == "__main__":
    sys.exit(main())
