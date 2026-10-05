"""Versioned prompt files. The name, version and SHA-256 of every prompt are recorded with each audit row."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parent / "prompts"


@dataclass(frozen=True)
class Prompt:
    name: str
    version: str
    text: str

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()

    @property
    def label(self) -> str:
        return f"{self.name}@{self.version}"


@lru_cache
def load_prompt(name: str, version: str) -> Prompt:
    path = PROMPT_DIR / f"{name}_{version}.txt"
    if not path.is_file():
        raise FileNotFoundError(f"prompt file missing: {path.name}")
    return Prompt(name=name, version=version, text=path.read_text(encoding="utf-8").strip())


def all_prompts() -> list[Prompt]:
    """Every shipped prompt, for the prompt_versions table."""
    prompts: list[Prompt] = []
    for path in sorted(PROMPT_DIR.glob("*_v*.txt")):
        name, version = path.stem.rsplit("_", 1)
        prompts.append(load_prompt(name, version))
    return prompts


PLAN_PROMPT_NAME = "plan"
SQL_PROMPT_NAME = "sql_fallback"
REPAIR_PROMPT_NAME = "repair"
CURRENT_VERSION = "v1"
