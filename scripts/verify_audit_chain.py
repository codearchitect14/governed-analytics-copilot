"""Verify the audit log hash chain. Exit code 0 when intact, 1 when a row was changed or removed.

Usage (from the repository root, with .env loaded):
    uv run --package governed-analytics-backend python scripts/verify_audit_chain.py
"""

from __future__ import annotations

import sys

from app.audit.verify import verify_chain
from app.core.config import get_settings
from app.db.engine import get_engine


def main() -> int:
    engine = get_engine(get_settings())
    with engine.connect() as connection:
        report = verify_chain(connection)
    if report.ok:
        print(f"Audit chain intact: {report.rows_checked} rows verified.")
        return 0
    print(
        f"Audit chain BROKEN at row id {report.first_invalid_id} "
        f"after {report.rows_checked} valid rows: {report.reason}",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
