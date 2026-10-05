"""Alembic environment. The connection comes from the application settings (role app_rw)."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool, text

from app.core.config import get_settings

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

APP_SCHEMA = "app"


def database_url() -> str:
    url = str(get_settings().app_database_url)
    return url.replace("postgresql://", "postgresql+psycopg://", 1)


def run_migrations_online() -> None:
    engine = create_engine(database_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        # The bootstrap creates the schema. Creating it here only when it is missing avoids
        # needing CREATE privilege on the database for every run.
        exists = connection.execute(
            text("SELECT 1 FROM pg_namespace WHERE nspname = :name"), {"name": APP_SCHEMA}
        ).first()
        if exists is None:
            connection.execute(text(f"CREATE SCHEMA {APP_SCHEMA}"))
            connection.commit()
        context.configure(
            connection=connection,
            target_metadata=None,
            version_table_schema=APP_SCHEMA,
            transactional_ddl=True,
        )
        with context.begin_transaction():
            context.run_migrations()
        connection.commit()
    engine.dispose()


run_migrations_online()
