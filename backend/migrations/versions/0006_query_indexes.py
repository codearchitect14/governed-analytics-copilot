"""Indexes for the workspace lists and the evaluation tables, found with EXPLAIN in Phase 11.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-08
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEXES: tuple[str, ...] = (
    "chat_sessions_user_created_idx",
    "saved_queries_user_created_idx",
    "chat_messages_session_created_idx",
    "eval_results_run_idx",
    "eval_runs_started_idx",
)


def upgrade() -> None:
    op.execute(
        "CREATE INDEX chat_sessions_user_created_idx ON app.chat_sessions (user_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX saved_queries_user_created_idx ON app.saved_queries (user_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX chat_messages_session_created_idx ON app.chat_messages (session_id, created_at)"
    )
    op.execute("CREATE INDEX eval_results_run_idx ON app.eval_results (run_id)")
    op.execute("CREATE INDEX eval_runs_started_idx ON app.eval_runs (started_at DESC)")


def downgrade() -> None:
    for name in INDEXES:
        op.execute(f"DROP INDEX IF EXISTS app.{name}")
