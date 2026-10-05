"""Verify the audit hash chain from the first row to the last."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.audit.chain import GENESIS_HASH, HASHED_FIELDS, compute_row_hash

_SELECT_COLUMNS = ", ".join(("id", *HASHED_FIELDS, "prev_hash", "row_hash"))


@dataclass(frozen=True)
class ChainReport:
    ok: bool
    rows_checked: int
    first_invalid_id: int | None = None
    reason: str | None = None


def verify_chain(connection: Connection) -> ChainReport:
    """Walk the chain in id order. Stops at the first row that does not link or does not hash."""
    expected_prev = GENESIS_HASH
    checked = 0
    result = connection.execution_options(stream_results=True).execute(
        text(f"SELECT {_SELECT_COLUMNS} FROM app.audit_log ORDER BY id")  # noqa: S608 - constant columns
    )
    for row in result.mappings():
        row_id = int(row["id"])
        if str(row["prev_hash"]) != expected_prev:
            return ChainReport(
                ok=False,
                rows_checked=checked,
                first_invalid_id=row_id,
                reason="link broken: a row before this one was removed, reordered or changed",
            )
        recomputed = compute_row_hash(expected_prev, dict(row))
        if recomputed != str(row["row_hash"]):
            return ChainReport(
                ok=False,
                rows_checked=checked,
                first_invalid_id=row_id,
                reason="row content does not match its hash: the row was modified",
            )
        expected_prev = str(row["row_hash"])
        checked += 1
    return ChainReport(ok=True, rows_checked=checked)
