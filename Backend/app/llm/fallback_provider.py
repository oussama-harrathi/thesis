"""
Fallback LLM provider.

Wraps a *primary* provider and a *fallback* provider.  When the primary
raises ``LLMProviderError`` (e.g. after exhausting all Groq retries on
rate-limit or service errors), the call is transparently retried using the
fallback provider.

Circuit breaker
───────────────
Once the primary fails, a module-level circuit breaker trips for
``CIRCUIT_BREAKER_TTL`` seconds (default 600 = 10 minutes).  During that
window every call goes directly to the fallback — skipping the primary
entirely so we don't waste time retrying a provider that is out of quota.

Typical usage (configured through env vars):
    LLM_PROVIDER=openai_compatible          # Groq / OpenRouter / OpenAI
    LLM_FALLBACK_PROVIDER=gemini            # Google Gemini as fallback

The factory (app.llm.factory) wires this automatically when
``LLM_FALLBACK_PROVIDER`` is set to a non-empty value.
"""

from __future__ import annotations

import logging
import time
from typing import TypeVar

from pydantic import BaseModel

from app.llm.base import BaseLLMProvider, GenerationSettings, LLMProviderError

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)

# How long (seconds) to bypass the primary after a failure.
# 600 s = 10 minutes — covers Groq's typical per-minute / per-day reset window.
CIRCUIT_BREAKER_TTL: float = 600.0

# Module-level dict: provider_name → timestamp when circuit opens (epoch seconds).
# Shared across all FallbackProvider instances in the same process.
_circuit_open_until: dict[str, float] = {}


class FallbackProvider(BaseLLMProvider):
    """
    Transparent two-provider fallback wrapper with circuit breaker.

    Tries *primary* first.  On ``LLMProviderError`` it:
      1. Trips the circuit breaker for the primary (bypasses it for TTL seconds).
      2. Delegates the same call to *fallback*.

    While the circuit is open, calls go directly to *fallback* without
    attempting the primary — avoiding long retry waits for a known-bad provider.
    """

    provider_name = "fallback"

    def __init__(
        self,
        primary: BaseLLMProvider,
        fallback: BaseLLMProvider,
    ) -> None:
        self._primary = primary
        self._fallback = fallback

    # ── Internal helpers ──────────────────────────────────────────

    def _is_circuit_open(self) -> bool:
        """Return True if the primary's circuit breaker is currently tripped."""
        open_until = _circuit_open_until.get(self._primary.provider_name, 0.0)
        return time.monotonic() < open_until

    def _trip_circuit(self) -> None:
        """Trip the circuit breaker — primary will be skipped for TTL seconds."""
        open_until = time.monotonic() + CIRCUIT_BREAKER_TTL
        _circuit_open_until[self._primary.provider_name] = open_until
        logger.warning(
            "[fallback] Circuit breaker TRIPPED for primary=%s — "
            "bypassing for %.0f s (until %.0f).",
            self._primary.provider_name,
            CIRCUIT_BREAKER_TTL,
            open_until,
        )

    # ── Public API ────────────────────────────────────────────────

    async def generate_json(
        self,
        prompt: str,
        schema: type[T],
        settings: GenerationSettings | None = None,
    ) -> T:
        if self._is_circuit_open():
            logger.info(
                "[fallback] Circuit open for %s — routing directly to fallback (%s).",
                self._primary.provider_name,
                self._fallback.provider_name,
            )
            return await self._fallback.generate_json(prompt, schema, settings)

        try:
            result = await self._primary.generate_json(prompt, schema, settings)
            return result
        except LLMProviderError as primary_exc:
            logger.warning(
                "[fallback] Primary provider (%s) failed: %s — "
                "tripping circuit breaker and switching to fallback (%s).",
                self._primary.provider_name,
                primary_exc,
                self._fallback.provider_name,
            )
            self._trip_circuit()
            return await self._fallback.generate_json(prompt, schema, settings)

    async def health_check(self) -> bool:
        primary_ok = await self._primary.health_check()
        if primary_ok:
            return True
        logger.warning(
            "[fallback] Primary provider (%s) health check failed — "
            "checking fallback (%s).",
            self._primary.provider_name,
            self._fallback.provider_name,
        )
        return await self._fallback.health_check()
