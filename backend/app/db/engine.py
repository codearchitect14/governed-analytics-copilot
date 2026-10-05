"""SQLAlchemy engine for the application database (role app_rw, psycopg 3 driver)."""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import Connection

from app.core.config import Settings, get_settings


def _driver_url(url: str) -> str:
    return url.replace("postgresql://", "postgresql+psycopg://", 1)


def build_engine(settings: Settings) -> Engine:
    return create_engine(
        _driver_url(str(settings.app_database_url)),
        pool_size=settings.db_pool_size,
        max_overflow=0,
        pool_pre_ping=True,
        connect_args={"connect_timeout": settings.db_connect_timeout_seconds},
    )


@lru_cache
def _cached_engine(url: str, pool_size: int, connect_timeout: int) -> Engine:
    return create_engine(
        _driver_url(url),
        pool_size=pool_size,
        max_overflow=0,
        pool_pre_ping=True,
        connect_args={"connect_timeout": connect_timeout},
    )


def get_engine(settings: Settings | None = None) -> Engine:
    """One engine per database URL. Settings are read once at startup."""
    current = settings or get_settings()
    return _cached_engine(
        str(current.app_database_url),
        current.db_pool_size,
        current.db_connect_timeout_seconds,
    )


def connection_scope(engine: Engine) -> Iterator[Connection]:
    """Yield a connection inside a transaction that commits on success."""
    with engine.begin() as connection:
        yield connection
