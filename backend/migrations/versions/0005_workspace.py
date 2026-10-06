"""Answer feedback from users (thumbs up and down), stored for evaluation.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-07
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE app.answer_feedback (
            id BIGSERIAL PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES app.users (id) ON DELETE CASCADE,
            audit_id BIGINT,
            value TEXT NOT NULL CHECK (value IN ('up', 'down')),
            comment TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS app.answer_feedback")
