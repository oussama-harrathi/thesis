"""
OpenAI-compatible LLM provider.

Works with any API that uses the OpenAI chat-completions format:
  - Groq        (https://api.groq.com/openai/v1)
  - OpenRouter  (https://openrouter.ai/api/v1)
  - OpenAI      (https://api.openai.com/v1)
  - Together AI, Fireworks, etc.

Configuration (env vars)
────────────────────────
LLM_PROVIDER=openai_compatible
OPENAI_COMPATIBLE_API_KEY     — required (Bearer token)
OPENAI_COMPATIBLE_BASE_URL    — defaults to https://api.openai.com/v1
OPENAI_COMPATIBLE_MODEL       — defaults to gpt-4o-mini
OPENAI_COMPATIBLE_TEMPERATURE — defaults to 0.3
OPENAI_COMPATIBLE_MAX_TOKENS  — defaults to 2048
OPENAI_COMPATIBLE_TIMEOUT     — HTTP timeout in seconds, defaults to 60
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

_DEFAULT_BASE_URL = "https://api.openai.com/v1"


class OpenAICompatibleProvider(BaseLLMProvider):
    """
    LLM provider for any OpenAI-compatible chat completions API.

    Sends a single user message with a JSON-output instruction appended.
    Uses `response_format={"type": "json_object"}` when supported
    (requires the model to also be instructed to emit JSON — already done
    via _build_json_instruction).
    """

    provider_name = "openai_compatible"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        default_temperature: float | None = None,
        default_max_tokens: int | None = None,
        default_timeout: float | None = None,
    ) -> None:
        self._api_key = api_key or settings.OPENAI_COMPATIBLE_API_KEY
        self._base_url = (base_url or settings.OPENAI_COMPATIBLE_BASE_URL).rstrip("/")
        self._model = model or settings.OPENAI_COMPATIBLE_MODEL
        self._default_temperature = default_temperature if default_temperature is not None else settings.OPENAI_COMPATIBLE_TEMPERATURE
        self._default_max_tokens = default_max_tokens or settings.OPENAI_COMPATIBLE_MAX_TOKENS
        self._default_timeout = default_timeout or settings.OPENAI_COMPATIBLE_TIMEOUT

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

        payload: dict = {
            "model": self._model,
            "messages": [{"role": "user", "content": full_prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }

        raw_text = await self._call_api(payload, timeout)
        logger.debug("[openai_compatible] raw response: %s", raw_text[:300])

        try:
            return self._parse_response(raw_text, schema)
        except LLMParseError:
            logger.warning("[openai_compatible] First parse failed — retrying without response_format")
            # Some endpoints don't support json_object mode — retry without it
            payload.pop("response_format", None)
            raw_text2 = await self._call_api(payload, timeout)
            return self._parse_response(raw_text2, schema)

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{self._base_url}/models",
                    headers=self._auth_headers(),
                )
            return resp.status_code == 200
        except Exception:
            logger.warning("[openai_compatible] health_check failed", exc_info=True)
            return False

    # ── Private helpers ───────────────────────────────────────────

    async def _call_api(self, payload: dict, timeout: float) -> str:
        url = f"{self._base_url}/chat/completions"
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(
                    url,
                    json=payload,
                    headers=self._auth_headers(),
                )
        except httpx.TimeoutException as exc:
            raise LLMProviderError(f"[openai_compatible] Request timed out: {exc}") from exc
        except httpx.RequestError as exc:
            raise LLMProviderError(f"[openai_compatible] Request error: {exc}") from exc

        if resp.status_code != 200:
            raise LLMProviderError(
                f"[openai_compatible] API returned {resp.status_code}: {resp.text[:400]}"
            )

        data = resp.json()
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise LLMProviderError(
                f"[openai_compatible] Unexpected response shape: {data}"
            ) from exc

    def _auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
