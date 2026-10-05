"""Application settings loaded from environment variables."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, PostgresDsn, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_APP_DATABASE_URL = "postgresql://app_rw:change-me-app-rw@localhost:5433/copilot"
MIN_JWT_SECRET_LENGTH = 32


class Settings(BaseSettings):
    """Runtime configuration. Values come from the environment or a local .env file."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["local", "test", "staging", "production"] = "local"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    app_database_url: PostgresDsn = Field(
        default=PostgresDsn(DEFAULT_APP_DATABASE_URL),
        description="Connection for application tables (role app_rw).",
    )
    db_connect_timeout_seconds: int = Field(default=3, ge=1, le=30)
    db_pool_size: int = Field(default=5, ge=1, le=50)

    # Authentication
    jwt_secret: SecretStr = Field(
        default=SecretStr("change-me-to-a-random-string-of-at-least-32-characters")
    )
    jwt_issuer: str = "meridian-data-copilot"
    access_token_minutes: int = Field(default=15, ge=1, le=60)
    refresh_token_days: int = Field(default=7, ge=1, le=30)
    refresh_cookie_name: str = "refresh_token"
    cookie_secure: bool = True
    password_min_length: int = Field(default=12, ge=8)
    lockout_threshold: int = Field(default=5, ge=1)
    lockout_minutes: int = Field(default=15, ge=1)

    # Demo accounts (local demonstration only)
    demo_user_password: SecretStr | None = None

    # LLM providers (free tiers). Both are optional: the rule resolver needs neither.
    groq_api_key: SecretStr | None = None
    gemini_api_key: SecretStr | None = None

    # Query pipeline
    warehouse_ro_database_url: PostgresDsn = Field(
        default=PostgresDsn(
            "postgresql://warehouse_ro:change-me-warehouse-ro@localhost:5433/copilot"
        ),
        description="Read only executor role (warehouse_ro).",
    )
    dbt_project_dir: Path = Field(default=Path("warehouse/dbt_project"))
    mf_executable: str = "mf"
    mf_timeout_seconds: float = Field(default=60.0, gt=0, le=300)
    semantic_cache_threshold: float = Field(default=0.93, ge=0.5, le=1.0)
    explain_cost_ceiling: float = Field(default=1_000_000.0, gt=0)
    query_max_rows: int = Field(default=1000, ge=1, le=10000)
    embedding_cache_dir: Path = Field(default=Path(".cache/embeddings"))
    semantic_seed_dir: Path = Field(default=Path("dataset/semantic_seed"))

    # HTTP
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5180", "http://localhost:5173"]
    )
    rate_limit_login: str = "10/minute"
    rate_limit_default: str = "120/minute"

    @field_validator("jwt_secret")
    @classmethod
    def _secret_is_long_enough(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < MIN_JWT_SECRET_LENGTH:
            raise ValueError(f"JWT_SECRET must be at least {MIN_JWT_SECRET_LENGTH} characters")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
