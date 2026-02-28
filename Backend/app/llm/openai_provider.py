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

import asyncio
import logging
import random
import re as _re
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
        # Maximum number of retries on 429 / transient errors before giving up.
        self._max_retries: int = 5

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

        # ── Proactive rate-limit pacing ──────────────────────────────────
        # Acquire token budget before hitting the API so we don't exhaust
        # the TPM window for Groq / other limited providers.
        try:
            from app.llm.rate_limit import rate_limit_manager
            estimated_tokens = rate_limit_manager.estimate_tokens(full_prompt)
            await rate_limit_manager.acquire(estimated_tokens)
        except Exception as _rl_exc:  # never let pacing interfere with generation
            logger.debug("[openai_compatible] rate-limit manager skipped: %s", _rl_exc)

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
        """
        POST to the chat-completions endpoint with 429-aware exponential backoff.

        Retry strategy
        --------------
        1. On HTTP 429, parse the wait time from:
           a. ``Retry-After`` response header (seconds).
           b. ``"Please try again in Xs"`` string in the response body.
           c. Exponential backoff fallback: ``2^attempt + random jitter``.
        2. Retries up to ``self._max_retries`` times, then raises.
        3. Any non-429, non-200 status raises ``LLMProviderError`` immediately.
        """
        url = f"{self._base_url}/chat/completions"

        for attempt in range(1, self._max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    resp = await client.post(
                        url,
                        json=payload,
                        headers=self._auth_headers(),
                    )
            except httpx.TimeoutException as exc:
                raise LLMProviderError(
                    f"[openai_compatible] Request timed out: {exc}"
                ) from exc
            except httpx.RequestError as exc:
                raise LLMProviderError(
                    f"[openai_compatible] Request error: {exc}"
                ) from exc

            if resp.status_code == 200:
                data = resp.json()
                try:
                    return data["choices"][0]["message"]["content"]
                except (KeyError, IndexError) as exc:
                    raise LLMProviderError(
                        f"[openai_compatible] Unexpected response shape: {data}"
                    ) from exc

            if resp.status_code == 429:
                if attempt >= self._max_retries:
                    raise LLMProviderError(
                        f"[openai_compatible] API returned 429 after {attempt} "
                        f"attempt(s): {resp.text[:300]}"
                    )

                # 1. Retry-After header
                wait_sec: float | None = None
                retry_after_hdr = resp.headers.get(
                    "Retry-After"
                ) or resp.headers.get("retry-after")
                if retry_after_hdr:
                    try:
                        wait_sec = float(retry_after_hdr) + 1.0
                    except (ValueError, TypeError):
                        pass

                # 2. Parse body message "try again in X.Xs"
                if wait_sec is None:
                    m = _re.search(
                        r"try again in ([0-9]+(?:\.[0-9]+)?)s", resp.text
                    )
                    if m:
                        wait_sec = float(m.group(1)) + 1.0

                # 3. Exponential backoff + jitter fallback
                if wait_sec is None:
                    wait_sec = (2.0 ** attempt) + random.uniform(0.0, 1.5)

                # Never wait more than 90 seconds per attempt
                wait_sec = min(wait_sec, 90.0)

                logger.warning(
                    "[openai_compatible] 429 rate-limited — attempt %d/%d, "
                    "sleeping %.1fs before retry.",
                    attempt, self._max_retries, wait_sec,
                )
                await asyncio.sleep(wait_sec)
                continue

            # Any other non-200 status: fail immediately, do not retry.
            raise LLMProviderError(
                f"[openai_compatible] API returned {resp.status_code}: "
                f"{resp.text[:400]}"
            )

        # Should be unreachable, but keeps type-checkers happy.
        raise LLMProviderError(
            f"[openai_compatible] All {self._max_retries} retry attempts exhausted."
        )

    def _auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
