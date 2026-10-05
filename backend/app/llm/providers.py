"""LLM provider adapters: Groq (primary) and Google Gemini (fallback).

Both adapters speak plain HTTP through httpx, so tests can replace the transport with a mock.
Every HTTP outcome is mapped to a ProviderError kind. The gateway uses the kind to decide
whether to fail over, and never shows the provider's raw error text to users.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import httpx

ErrorKind = Literal["rate_limited", "server", "timeout", "auth", "bad_request", "malformed"]
RETRYABLE_KINDS: frozenset[str] = frozenset({"rate_limited", "server", "timeout"})


class ProviderError(Exception):
    def __init__(self, kind: ErrorKind, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.retry_after = retry_after

    @property
    def retryable(self) -> bool:
        return self.kind in RETRYABLE_KINDS


@dataclass(frozen=True)
class LLMRequest:
    system: str
    user: str
    max_output_tokens: int
    json_output: bool = True


@dataclass(frozen=True)
class LLMResponse:
    text: str
    provider: str
    model: str
    tokens_in: int
    tokens_out: int
    latency_ms: int


class LLMProvider(Protocol):
    name: str
    model: str

    def complete(self, request: LLMRequest) -> LLMResponse: ...


def _map_status(response: httpx.Response) -> ProviderError:
    retry_after_header = response.headers.get("retry-after")
    retry_after = (
        float(retry_after_header)
        if retry_after_header and retry_after_header.replace(".", "").isdigit()
        else None
    )
    if response.status_code == 429:
        return ProviderError("rate_limited", "provider rate limit reached", retry_after)
    if response.status_code in (401, 403):
        return ProviderError("auth", "provider rejected the credentials")
    if response.status_code >= 500:
        return ProviderError("server", f"provider returned HTTP {response.status_code}")
    return ProviderError("bad_request", f"provider returned HTTP {response.status_code}")


def _call(client: httpx.Client, method: str, url: str, **kwargs: Any) -> httpx.Response:
    try:
        return client.request(method, url, **kwargs)
    except httpx.TimeoutException as error:
        raise ProviderError("timeout", "provider request timed out") from error
    except httpx.HTTPError as error:
        raise ProviderError("server", "provider connection failed") from error


class GroqProvider:
    """Groq OpenAI compatible chat completions. Default model: openai/gpt-oss-20b."""

    name = "groq"

    def __init__(
        self,
        api_key: str,
        model: str = "openai/gpt-oss-20b",
        *,
        base_url: str = "https://api.groq.com/openai/v1",
        transport: httpx.BaseTransport | None = None,
        timeout_seconds: float = 20.0,
    ) -> None:
        self.model = model
        self._client = httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout_seconds,
            transport=transport,
        )

    def complete(self, request: LLMRequest) -> LLMResponse:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": request.system},
                {"role": "user", "content": request.user},
            ],
            "max_completion_tokens": request.max_output_tokens,
            "temperature": 0,
            "reasoning_effort": "low",
        }
        if request.json_output:
            body["response_format"] = {"type": "json_object"}
        started = time.perf_counter()
        response = _call(self._client, "POST", "/chat/completions", json=body)
        if response.status_code != 200:
            raise _map_status(response)
        payload = response.json()
        try:
            text_output = str(payload["choices"][0]["message"]["content"] or "")
            usage = payload.get("usage") or {}
        except (KeyError, IndexError, TypeError) as error:
            raise ProviderError("malformed", "provider response had an unexpected shape") from error
        return LLMResponse(
            text=text_output,
            provider=self.name,
            model=self.model,
            tokens_in=int(usage.get("prompt_tokens", 0)),
            tokens_out=int(usage.get("completion_tokens", 0)),
            latency_ms=int((time.perf_counter() - started) * 1000),
        )


class GeminiProvider:
    """Google Gemini generateContent API. Default model: gemini-2.5-flash."""

    name = "gemini"

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.5-flash",
        *,
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
        transport: httpx.BaseTransport | None = None,
        timeout_seconds: float = 20.0,
    ) -> None:
        self.model = model
        self._client = httpx.Client(
            base_url=base_url,
            headers={"x-goog-api-key": api_key},
            timeout=timeout_seconds,
            transport=transport,
        )

    def complete(self, request: LLMRequest) -> LLMResponse:
        generation: dict[str, Any] = {
            "maxOutputTokens": request.max_output_tokens,
            "temperature": 0,
        }
        if request.json_output:
            generation["responseMimeType"] = "application/json"
        body: dict[str, Any] = {
            "systemInstruction": {"parts": [{"text": request.system}]},
            "contents": [{"role": "user", "parts": [{"text": request.user}]}],
            "generationConfig": generation,
        }
        started = time.perf_counter()
        response = _call(self._client, "POST", f"/models/{self.model}:generateContent", json=body)
        if response.status_code != 200:
            raise _map_status(response)
        payload = response.json()
        try:
            text_output = str(payload["candidates"][0]["content"]["parts"][0]["text"])
            usage = payload.get("usageMetadata") or {}
        except (KeyError, IndexError, TypeError) as error:
            raise ProviderError("malformed", "provider response had an unexpected shape") from error
        return LLMResponse(
            text=text_output,
            provider=self.name,
            model=self.model,
            tokens_in=int(usage.get("promptTokenCount", 0)),
            tokens_out=int(usage.get("candidatesTokenCount", 0)),
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
