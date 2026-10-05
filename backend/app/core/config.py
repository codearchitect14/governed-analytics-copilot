"""Application settings loaded from environment variables."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Values come from the environment or a local .env file."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["local", "test", "staging", "production"] = "local"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    app_database_url: PostgresDsn = Field(
        default=PostgresDsn("postgresql://app_rw:change-me-app-rw@localhost:5433/copilot"),
        description="Connection for application tables (role app_rw).",
    )
    db_connect_timeout_seconds: int = Field(default=3, ge=1, le=30)


@lru_cache
def get_settings() -> Settings:
    return Settings()
