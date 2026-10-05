"""Hash chain for the audit log.

Each row stores prev_hash (the row_hash of the previous row) and row_hash, which is the SHA-256
of prev_hash together with a canonical encoding of the row content. Changing any row, or
removing one, breaks the chain at that point. The encoding is independent of the server time
zone and of JSON key order, so a row verifies the same way when it is read back.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

GENESIS_HASH = "0" * 64

HASHED_FIELDS: tuple[str, ...] = (
    "ts",
    "event",
    "user_id",
    "role",
    "session_id",
    "question",
    "normalized_question",
    "route",
    "provider",
    "model",
    "prompt_version",
    "tokens_in",
    "tokens_out",
    "plan_json",
    "generated_sql",
    "final_sql",
    "validation_result",
    "policy_hash",
    "decision",
    "denial_reason",
    "row_count",
    "exec_ms",
    "total_ms",
    "is_synthetic",
    "client_ip",
    "request_id",
)


def _encode(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC).isoformat(timespec="microseconds")
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (dict, list)):
        return json.loads(json.dumps(value, sort_keys=True, default=str))
    return value


def canonical_payload(row: Mapping[str, Any]) -> str:
    encoded = {name: _encode(row.get(name)) for name in HASHED_FIELDS}
    return json.dumps(encoded, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_row_hash(prev_hash: str, row: Mapping[str, Any]) -> str:
    material = f"{prev_hash}\n{canonical_payload(row)}".encode()
    return hashlib.sha256(material).hexdigest()
