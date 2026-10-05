"""Load provider order and budgets from llm_config.yml and build the gateway."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from app.llm.gateway import DatabaseUsageStore, LLMGateway, ProviderLimits, ProviderSlot, UsageStore
from app.llm.providers import GeminiProvider, GroqProvider, LLMProvider

BACKEND_DIR = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = Path(os.environ.get("LLM_CONFIG_PATH", str(BACKEND_DIR / "llm_config.yml")))


@dataclass(frozen=True)
class ProviderSettings:
    name: str
    priority: int
    model: str
    limits: ProviderLimits


def load_provider_settings(path: Path = DEFAULT_CONFIG) -> list[ProviderSettings]:
    document: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    settings: list[ProviderSettings] = []
    for name, values in (document.get("providers") or {}).items():
        settings.append(
            ProviderSettings(
                name=str(name),
                priority=int(values["priority"]),
                model=str(values["model"]),
                limits=ProviderLimits(
                    requests_per_minute=int(values["requests_per_minute"]),
                    tokens_per_minute=int(values["tokens_per_minute"]),
                    requests_per_day=int(values["requests_per_day"]),
                    tokens_per_day=int(values["tokens_per_day"]),
                ),
            )
        )
    return settings


def build_provider(name: str, model: str, groq_key: str, gemini_key: str) -> LLMProvider | None:
    if name == "groq" and groq_key:
        return GroqProvider(groq_key, model)
    if name == "gemini" and gemini_key:
        return GeminiProvider(gemini_key, model)
    return None


def build_gateway(
    *,
    groq_key: str,
    gemini_key: str,
    usage: UsageStore,
    mode_source: Callable[[], str],
    config_path: Path = DEFAULT_CONFIG,
) -> LLMGateway:
    slots: list[ProviderSlot] = []
    for item in load_provider_settings(config_path):
        provider = build_provider(item.name, item.model, groq_key, gemini_key)
        if provider is not None:
            slots.append(
                ProviderSlot(provider=provider, limits=item.limits, priority=item.priority)
            )
    return LLMGateway(slots, usage, mode_source)


def database_usage(engine: Any) -> UsageStore:
    return DatabaseUsageStore(engine)
