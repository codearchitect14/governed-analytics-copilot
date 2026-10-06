"""Contact form submissions from the public website.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-06
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE app.contact_requests (
            id BIGSERIAL PRIMARY KEY,
            received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            company TEXT,
            topic TEXT NOT NULL,
            message TEXT NOT NULL,
            consent_given BOOLEAN NOT NULL,
            client_ip TEXT
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS app.contact_requests")
