"""Append only audit writer. Every request outcome and security event goes through here."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.audit.chain import GENESIS_HASH, HASHED_FIELDS, compute_row_hash

Decision = Literal["allowed", "denied", "clarify", "error", "info"]
JSON_FIELDS = frozenset({"plan_json", "validation_result"})
CHAIN_LOCK_KEY = "app.audit_chain"


@dataclass(frozen=True)
class AuditEvent:
    event: str
    decision: Decision
    user_id: UUID | None = None
    role: str | None = None
    session_id: UUID | None = None
    question: str | None = None
    normalized_question: str | None = None
    route: str | None = None
    provider: str | None = None
    model: str | None = None
    prompt_version: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    plan_json: dict[str, Any] | None = None
    generated_sql: str | None = None
    final_sql: str | None = None
    validation_result: dict[str, Any] | None = None
    policy_hash: str | None = None
    denial_reason: str | None = None
    row_count: int | None = None
    exec_ms: int | None = None
    total_ms: int | None = None
    is_synthetic: bool = False
    client_ip: str | None = None
    request_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def append_event(connection: Connection, event: AuditEvent, now: datetime | None = None) -> int:
    """Insert one event into the chain and return its id.

    A transaction level advisory lock serialises writers, so every row links to the row that
    was committed before it.
    """
    connection.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": CHAIN_LOCK_KEY}
    )
    previous = connection.execute(
        text("SELECT row_hash FROM app.audit_log ORDER BY id DESC LIMIT 1")
    ).scalar()
    prev_hash = str(previous) if previous is not None else GENESIS_HASH

    row: dict[str, Any] = {
        "ts": now or datetime.now(UTC),
        "event": event.event,
        "user_id": event.user_id,
        "role": event.role,
        "session_id": event.session_id,
        "question": event.question,
        "normalized_question": event.normalized_question,
        "route": event.route,
        "provider": event.provider,
        "model": event.model,
        "prompt_version": event.prompt_version,
        "tokens_in": event.tokens_in,
        "tokens_out": event.tokens_out,
        "plan_json": event.plan_json,
        "generated_sql": event.generated_sql,
        "final_sql": event.final_sql,
        "validation_result": event.validation_result,
        "policy_hash": event.policy_hash,
        "decision": event.decision,
        "denial_reason": event.denial_reason,
        "row_count": event.row_count,
        "exec_ms": event.exec_ms,
        "total_ms": event.total_ms,
        "is_synthetic": event.is_synthetic,
        "client_ip": event.client_ip,
        "request_id": event.request_id,
    }
    row_hash = compute_row_hash(prev_hash, row)

    columns = [*HASHED_FIELDS, "prev_hash", "row_hash"]
    values: dict[str, Any] = {name: _bind(name, row[name]) for name in HASHED_FIELDS}
    values["prev_hash"] = prev_hash
    values["row_hash"] = row_hash
    placeholders = ", ".join(
        f"CAST(:{name} AS JSONB)" if name in JSON_FIELDS else f":{name}" for name in columns
    )
    statement = text(
        f"INSERT INTO app.audit_log ({', '.join(columns)}) VALUES ({placeholders}) RETURNING id"  # noqa: S608 - bound values
    )
    identifier: int = connection.execute(statement, values).scalar_one()
    return int(identifier)


def _bind(name: str, value: Any) -> Any:
    if name in JSON_FIELDS and value is not None:
        return json.dumps(value, sort_keys=True, default=str)
    if isinstance(value, UUID):
        return str(value)
    return value
