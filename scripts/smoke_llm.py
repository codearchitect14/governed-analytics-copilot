"""Live smoke test for the LLM providers. Makes one small real request per configured provider.

Requires GROQ_API_KEY and/or GEMINI_API_KEY in .env. Not run in CI (no network in CI tests).

Usage (from the repository root):
    uv run --package governed-analytics-backend python scripts/smoke_llm.py
"""

from __future__ import annotations

import sys

from app.core.config import get_settings
from app.llm.config import build_provider, load_provider_settings
from app.llm.providers import LLMRequest, ProviderError

PROMPT = LLMRequest(
    system='Reply with a JSON object only: {"ok": true}.',
    user="ping",
    max_output_tokens=20,
)


def main() -> int:
    settings = get_settings()
    groq = settings.groq_api_key.get_secret_value() if settings.groq_api_key else ""
    gemini = settings.gemini_api_key.get_secret_value() if settings.gemini_api_key else ""
    configured = [item for item in load_provider_settings()]
    exit_code = 0
    tried = 0
    for item in sorted(configured, key=lambda entry: entry.priority):
        provider = build_provider(item.name, item.model, groq, gemini)
        if provider is None:
            print(f"{item.name}: no API key configured, skipped")
            continue
        tried += 1
        try:
            response = provider.complete(PROMPT)
        except ProviderError as error:
            print(f"{item.name}: FAILED ({error.kind})")
            exit_code = 1
            continue
        print(
            f"{item.name}: ok model={response.model} tokens_in={response.tokens_in} "
            f"tokens_out={response.tokens_out} latency_ms={response.latency_ms}"
        )
    if tried == 0:
        print("No provider key is configured. Set GROQ_API_KEY or GEMINI_API_KEY in .env.")
        return 2
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
