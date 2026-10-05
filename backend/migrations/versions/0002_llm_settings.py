"""Operational settings that an administrator can change at runtime (LLM provider mode).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-06
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE app.llm_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        INSERT INTO app.llm_settings (key, value) VALUES ('llm_mode', 'auto')
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS app.llm_settings")
