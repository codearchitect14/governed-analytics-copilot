"""Build the shared services used by the query pipeline. Created once at application startup."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from sqlalchemy import Engine, text

from app.core.config import Settings, get_settings
from app.db.engine import _cached_engine
from app.llm.config import build_gateway
from app.llm.gateway import DatabaseUsageStore, LLMGateway
from app.pipeline.executor import ColumnCatalog
from app.pipeline.orchestrator import QueryPipeline, Services
from app.semantic.compiler import MetricFlowCompiler
from app.semantic.embeddings import Embedder
from app.semantic.vocabulary import load_vocabulary

REPO_ROOT = Path(__file__).resolve().parents[3]


def _repo_path(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


def read_llm_mode(engine: Engine) -> str:
    with engine.connect() as connection:
        value = connection.execute(
            text("SELECT value FROM app.llm_settings WHERE key = 'llm_mode'")
        ).scalar()
    return str(value or "auto")


def build_services(settings: Settings) -> Services:
    app_engine = _cached_engine(
        str(settings.app_database_url), settings.db_pool_size, settings.db_connect_timeout_seconds
    )
    executor_engine = _cached_engine(
        str(settings.warehouse_ro_database_url),
        settings.db_pool_size,
        settings.db_connect_timeout_seconds,
    )
    project_dir = _repo_path(settings.dbt_project_dir)
    seed_dir = _repo_path(settings.semantic_seed_dir)
    metrics_yml = project_dir / "models" / "semantic" / "metrics.yml"
    vocabulary = load_vocabulary(seed_dir / "synonyms.yml", metrics_yml)
    gateway: LLMGateway | None = None
    groq = settings.groq_api_key.get_secret_value() if settings.groq_api_key else ""
    gemini = settings.gemini_api_key.get_secret_value() if settings.gemini_api_key else ""
    if groq or gemini:
        gateway = build_gateway(
            groq_key=groq,
            gemini_key=gemini,
            usage=DatabaseUsageStore(app_engine),
            mode_source=lambda: read_llm_mode(app_engine),
        )
    return Services(
        settings=settings,
        app_engine=app_engine,
        executor_engine=executor_engine,
        compiler=MetricFlowCompiler(
            project_dir,
            executable=settings.mf_executable,
            timeout_seconds=settings.mf_timeout_seconds,
            build_dir=Path.home() / ".cache" / "governed-analytics-dbt",
        ),
        vocabulary=vocabulary,
        columns=ColumnCatalog(executor_engine),
        embedder=Embedder(cache_dir=_repo_path(settings.embedding_cache_dir)),
        gateway=gateway,
    )


@lru_cache
def _pipeline_for(url: str) -> QueryPipeline:
    return QueryPipeline(build_services(get_settings()))


def get_pipeline() -> QueryPipeline:
    settings = get_settings()
    return _pipeline_for(str(settings.app_database_url))
