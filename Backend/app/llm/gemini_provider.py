"""
Google Gemini LLM provider.

Uses the google-genai SDK (pip install google-genai).
The Gemini API differs from OpenAI's format — this adapter handles those
differences transparently so the rest of the codebase stays provider-agnostic.

Configuration (env vars)
────────────────────────
LLM_PROVIDER=gemini
GEMINI_API_KEY          — required (Google AI Studio API key)
GEMINI_MODEL            — defaults to gemini-2.0-flash
GEMINI_TEMPERATURE      — defaults to 0.3
GEMINI_MAX_TOKENS       — defaults to 2048
GEMINI_TIMEOUT          — HTTP timeout in seconds, defaults to 60
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import TypeVar

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

_MAX_RATE_LIMIT_RETRIES = 4       # how many times to retry on 429
_DEFAULT_RATE_LIMIT_WAIT = 15.0   # seconds to wait if no retryDelay in error

# ── Module-level throttle (shared across all GeminiProvider instances) ────────
# Enforces minimum spacing between API calls so we never burst past the
# free-tier limit (5 req/min = one call every 12s).
_GEMINI_MIN_INTERVAL: float = 12.5   # seconds between calls
_gemini_throttle_lock: asyncio.Lock | None = None
_gemini_last_call_at: float = 0.0


def _get_throttle_lock() -> asyncio.Lock:
    """Lazily create the lock inside the running event loop."""
    global _gemini_throttle_lock
    if _gemini_throttle_lock is None:
        _gemini_throttle_lock = asyncio.Lock()
    return _gemini_throttle_lock


async def _throttle_gemini() -> None:
    """Sleep until it is safe to make the next Gemini call."""
    global _gemini_last_call_at
    lock = _get_throttle_lock()
    async with lock:
        now = asyncio.get_event_loop().time()
        elapsed = now - _gemini_last_call_at
        wait = _GEMINI_MIN_INTERVAL - elapsed
        if wait > 0:
            logger.debug("[gemini] throttle: sleeping %.1fs to respect rate limit", wait)
            await asyncio.sleep(wait)
        _gemini_last_call_at = asyncio.get_event_loop().time()


def _extract_retry_delay(exc: Exception) -> float:
    """Parse retryDelay from a google-genai 429 error. Returns seconds."""
    text = str(exc)
    # Format: 'retryDelay': '13s'  or  "retryDelay": "13.47s"
    match = re.search(r"retryDelay['\"]?\s*:\s*['\"]?(\d+(?:\.\d+)?)s", text)
    if match:
        return float(match.group(1)) + 1.0  # +1s safety margin
    return _DEFAULT_RATE_LIMIT_WAIT


def _is_rate_limit(exc: Exception) -> bool:
    return "429" in str(exc) or "RESOURCE_EXHAUSTED" in str(exc)


class GeminiProvider(BaseLLMProvider):
    """
    LLM provider adapter for Google Gemini (via google-genai SDK).

    Uses the async client with JSON response MIME type for structured output.
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
        self._default_temperature = (
            default_temperature
            if default_temperature is not None
            else settings.GEMINI_TEMPERATURE
        )
        self._default_max_tokens = default_max_tokens or settings.GEMINI_MAX_TOKENS
        self._default_timeout = default_timeout or settings.GEMINI_TIMEOUT

    # ── Public API ────────────────────────────────────────────────

    async def generate_json(
        self,
        prompt: str,
        schema: type[T],
        settings: GenerationSettings | None = None,
    ) -> T:
        try:
            import google.genai as genai  # type: ignore[import-untyped]
            import google.genai.types as gentypes  # type: ignore[import-untyped]
        except ImportError as exc:
            raise LLMProviderError(
                "google-genai is not installed. Run: pip install google-genai"
            ) from exc

        temperature = (
            settings.temperature
            if settings and settings.temperature is not None
            else self._default_temperature
        )
        max_tokens = (
            settings.max_tokens
            if settings and settings.max_tokens is not None
            else self._default_max_tokens
        )

        client = genai.Client(api_key=self._api_key)
        full_prompt = prompt + self._build_json_instruction(schema)

        config = gentypes.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
            response_mime_type="application/json",
        )

        # ── Call with throttle + 429-aware retry loop ───────────
        last_exc: Exception | None = None
        for attempt in range(1, _MAX_RATE_LIMIT_RETRIES + 1):
            await _throttle_gemini()
            try:
                response = await client.aio.models.generate_content(
                    model=self._model_name,
                    contents=full_prompt,
                    config=config,
                )
                last_exc = None
                break
            except Exception as exc:
                if _is_rate_limit(exc):
                    wait = _extract_retry_delay(exc)
                    logger.warning(
                        "[gemini] 429 rate-limited (attempt %d/%d) — sleeping %.1fs",
                        attempt, _MAX_RATE_LIMIT_RETRIES, wait,
                    )
                    if attempt < _MAX_RATE_LIMIT_RETRIES:
                        await asyncio.sleep(wait)
                        last_exc = exc
                        continue
                    else:
                        raise LLMProviderError(f"[gemini] API call failed: {exc}") from exc
                raise LLMProviderError(f"[gemini] API call failed: {exc}") from exc

        if last_exc is not None:
            raise LLMProviderError(f"[gemini] API call failed: {last_exc}") from last_exc

        raw_text: str = response.text or ""  # type: ignore[possibly-undefined]
        if not raw_text:
            raise LLMProviderError("[gemini] API returned an empty response")
        logger.debug("[gemini] raw response: %s", raw_text[:300])

        try:
            return self._parse_response(raw_text, schema)
        except LLMParseError:
            # Retry without response_mime_type
            logger.warning("[gemini] First parse failed — retrying without response_mime_type")
            plain_config = gentypes.GenerateContentConfig(
                temperature=temperature,
                max_output_tokens=max_tokens,
            )
            for attempt2 in range(1, _MAX_RATE_LIMIT_RETRIES + 1):
                await _throttle_gemini()
                try:
                    response2 = await client.aio.models.generate_content(
                        model=self._model_name,
                        contents=full_prompt,
                        config=plain_config,
                    )
                    break
                except Exception as exc2:
                    if _is_rate_limit(exc2):
                        wait2 = _extract_retry_delay(exc2)
                        logger.warning(
                            "[gemini] 429 on parse-retry (attempt %d/%d) — sleeping %.1fs",
                            attempt2, _MAX_RATE_LIMIT_RETRIES, wait2,
                        )
                        if attempt2 < _MAX_RATE_LIMIT_RETRIES:
                            await asyncio.sleep(wait2)
                            continue
                    raise LLMProviderError(f"[gemini] Retry API call failed: {exc2}") from exc2
            raw_text2: str = response2.text or ""  # type: ignore[possibly-undefined]
            if not raw_text2:
                raise LLMProviderError("[gemini] Retry returned an empty response")
            return self._parse_response(raw_text2, schema)

    async def health_check(self) -> bool:
        try:
            import google.genai as genai  # type: ignore[import-untyped]
            client = genai.Client(api_key=self._api_key)
            # paging through models is a lightweight API key validation
            models = [m async for m in await client.aio.models.list()]
            return len(models) > 0
        except Exception:
            logger.warning("[gemini] health_check failed", exc_info=True)
            return False
