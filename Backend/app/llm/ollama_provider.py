"""
Ollama local LLM provider.

Ollama exposes an OpenAI-compatible chat/completions endpoint at
/api/chat  (native) or  /v1/chat/completions  (OpenAI compat, Ollama ≥0.1.24).

This adapter uses the native /api/chat endpoint for maximum compatibility
with older Ollama versions.

Configuration (env vars)
────────────────────────
LLM_PROVIDER=ollama
OLLAMA_BASE_URL    — defaults to http://localhost:11434
OLLAMA_MODEL       — defaults to llama3
OLLAMA_TEMPERATURE — defaults to 0.3
OLLAMA_MAX_TOKENS  — defaults to 2048
OLLAMA_TIMEOUT     — HTTP timeout in seconds, defaults to 120
                     (local models are slow — use a generous timeout)
"""

from __future__ import annotations

import logging
from typing import TypeVar

import httpx
from pydantic import BaseModel

from app.core.config import settings
from app.llm.base import (
    BaseLLMProvider,
    GenerationSettings,
    LLMParseError,
    LLMProviderError,
)

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


class OllamaProvider(BaseLLMProvider):
    """
    LLM provider adapter for a locally running Ollama instance.

    Uses Ollama's native /api/chat endpoint with format="json" to
    encourage structured output, combined with prompt-level JSON instructions.
    """

    provider_name = "ollama"

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        default_temperature: float | None = None,
        default_max_tokens: int | None = None,
        default_timeout: float | None = None,
    ) -> None:
        self._base_url = (base_url or settings.OLLAMA_BASE_URL).rstrip("/")
        self._model = model or settings.OLLAMA_MODEL
        self._default_temperature = default_temperature if default_temperature is not None else settings.OLLAMA_TEMPERATURE
        self._default_max_tokens = default_max_tokens or settings.OLLAMA_MAX_TOKENS
        self._default_timeout = default_timeout or settings.OLLAMA_TIMEOUT

    # ── Public API ────────────────────────────────────────────────

    async def generate_json(
        self,
        prompt: str,
        schema: type[T],
        settings: GenerationSettings | None = None,
    ) -> T:
        temperature = settings.temperature if settings and settings.temperature is not None else self._default_temperature
        max_tokens = settings.max_tokens if settings and settings.max_tokens is not None else self._default_max_tokens
        timeout = settings.timeout if settings and settings.timeout is not None else self._default_timeout

        full_prompt = prompt + self._build_json_instruction(schema)

        payload = {
            "model": self._model,
            "messages": [{"role": "user", "content": full_prompt}],
            "format": "json",          # Ollama-native JSON mode
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        raw_text = await self._call_api(payload, timeout)
        logger.debug("[ollama] raw response: %s", raw_text[:300])

        return self._parse_response(raw_text, schema)

    async def health_check(self) -> bool:
        """Check if Ollama is running and the configured model is available."""
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{self._base_url}/api/tags")
            if resp.status_code != 200:
                return False
            data = resp.json()
            available = [m.get("name", "") for m in data.get("models", [])]
            # Accept if model name is a prefix match (e.g. "llama3" matches "llama3:latest")
            return any(m.startswith(self._model.split(":")[0]) for m in available)
        except Exception:
            logger.warning("[ollama] health_check failed", exc_info=True)
            return False

    # ── Private helpers ───────────────────────────────────────────

    async def _call_api(self, payload: dict, timeout: float) -> str:
        url = f"{self._base_url}/api/chat"
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, json=payload)
        except httpx.TimeoutException as exc:
            raise LLMProviderError(f"[ollama] Request timed out: {exc}") from exc
        except httpx.RequestError as exc:
            raise LLMProviderError(
                f"[ollama] Could not connect to Ollama at {self._base_url}: {exc}"
            ) from exc

        if resp.status_code != 200:
            raise LLMProviderError(
                f"[ollama] API returned {resp.status_code}: {resp.text[:400]}"
            )

        data = resp.json()
        try:
            return data["message"]["content"]
        except (KeyError, TypeError) as exc:
            raise LLMProviderError(
                f"[ollama] Unexpected response shape: {data}"
            ) from exc
