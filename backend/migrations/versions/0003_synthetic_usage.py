"""Flag synthetic (demo) usage counters so that they can be shown separately from real usage.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-07
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE app.llm_usage ADD COLUMN is_synthetic BOOLEAN NOT NULL DEFAULT FALSE")
    op.execute("ALTER TABLE app.llm_usage DROP CONSTRAINT llm_usage_usage_date_provider_model_key")
    op.execute(
        "ALTER TABLE app.llm_usage ADD CONSTRAINT llm_usage_daily_key "
        "UNIQUE (usage_date, provider, model, is_synthetic)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE app.llm_usage DROP CONSTRAINT IF EXISTS llm_usage_daily_key")
    op.execute("DELETE FROM app.llm_usage WHERE is_synthetic")
    op.execute("ALTER TABLE app.llm_usage DROP COLUMN is_synthetic")
    op.execute(
        "ALTER TABLE app.llm_usage ADD CONSTRAINT llm_usage_usage_date_provider_model_key "
        "UNIQUE (usage_date, provider, model)"
    )
