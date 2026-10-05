"""Database connectivity check used by the readiness probe."""

import psycopg

from app.core.config import Settings


def check_database(settings: Settings) -> bool:
    """Return True when the application database answers a trivial query."""
    try:
        with (
            psycopg.connect(
                str(settings.app_database_url),
                connect_timeout=settings.db_connect_timeout_seconds,
            ) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute("SELECT 1")
            row = cursor.fetchone()
            return row is not None and row[0] == 1
    except psycopg.Error:
        return False
