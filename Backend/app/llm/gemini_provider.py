"""
Google Gemini LLM provider.

Uses the google-generativeai SDK (pip install google-generativeai).
The Gemini API differs from OpenAI's format — this adapter handles those
differences transparently so the rest of the codebase stays provider-agnostic.

Configuration (env vars)
────────────────────────
LLM_PROVIDER=gemini
GEMINI_API_KEY          — required (Google AI Studio API key)
GEMINI_MODEL            — defaults to gemini-1.5-flash
GEMINI_TEMPERATURE      — defaults to 0.3
GEMINI_MAX_TOKENS       — defaults to 2048
GEMINI_TIMEOUT          — HTTP timeout in seconds, defaults to 60
"""

from __future__ import annotations

import json
import logging
from typing import Any, TypeVar

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


class GeminiProvider(BaseLLMProvider):
    """
    LLM provider adapter for Google Gemini (via google-generativeai SDK).

    Requests JSON output using Gemini's native response_mime_type and
    response_schema support where available.  Falls back to prompt-level
    JSON instructions for older model versions.
    """

    provider_name = "gemini"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        default_temperature: float | None = None,
        default_max_tokens: int | None = None,
        default_timeout: float | None = None,
    ) -> None:
        self._api_key = api_key or settings.GEMINI_API_KEY
        self._model_name = model or settings.GEMINI_MODEL
        self._default_temperature = default_temperature if default_temperature is not None else settings.GEMINI_TEMPERATURE
        self._default_max_tokens = default_max_tokens or settings.GEMINI_MAX_TOKENS
        self._default_timeout = default_timeout or settings.GEMINI_TIMEOUT
        self._client: object | None = None  # lazy-loaded

    # ── Public API ────────────────────────────────────────────────

    async def generate_json(
        self,
        prompt: str,
        schema: type[T],
        settings: GenerationSettings | None = None,
    ) -> T:
        try:
            import google.generativeai as _genai_mod  # type: ignore[import-untyped]
            genai: Any = _genai_mod
        except ImportError as exc:
            raise LLMProviderError(
                "google-generativeai is not installed. "
                "Run: pip install google-generativeai"
            ) from exc

        temperature = settings.temperature if settings and settings.temperature is not None else self._default_temperature
        max_tokens = settings.max_tokens if settings and settings.max_tokens is not None else self._default_max_tokens

        genai.configure(api_key=self._api_key)
        model = genai.GenerativeModel(self._model_name)

        generation_config = genai.GenerationConfig(  # type: ignore[attr-defined]
            temperature=temperature,
            max_output_tokens=max_tokens,
            response_mime_type="application/json",
        )

        full_prompt = prompt + self._build_json_instruction(schema)

        try:
            response = await model.generate_content_async(
                full_prompt,
                generation_config=generation_config,
            )
        except Exception as exc:
            raise LLMProviderError(f"[gemini] API call failed: {exc}") from exc

        raw_text: str = response.text
        logger.debug("[gemini] raw response: %s", raw_text[:300])

        try:
            return self._parse_response(raw_text, schema)
        except LLMParseError:
            # Retry without response_mime_type in case the model doesn't support it
            logger.warning("[gemini] First parse failed — retrying without response_mime_type")
            plain_config = genai.GenerationConfig(
                temperature=temperature,
                max_output_tokens=max_tokens,
            )
            try:
                response2 = await model.generate_content_async(
                    full_prompt,
                    generation_config=plain_config,
                )
            except Exception as exc2:
                raise LLMProviderError(f"[gemini] Retry API call failed: {exc2}") from exc2
            return self._parse_response(response2.text, schema)

    async def health_check(self) -> bool:
        try:
            import google.generativeai as _genai_mod  # type: ignore[import-untyped]
            genai: Any = _genai_mod
            genai.configure(api_key=self._api_key)
            # list_models is a lightweight check that validates the API key
            models = list(genai.list_models())
            return len(models) > 0
        except Exception:
            logger.warning("[gemini] health_check failed", exc_info=True)
            return False
