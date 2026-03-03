"""
Cerebras LLM provider.

Cerebras uses the OpenAI chat-completions API format, so this is a thin
subclass of OpenAICompatibleProvider that reads Cerebras-specific settings
(CEREBRAS_API_KEY, CEREBRAS_MODEL, CEREBRAS_BASE_URL) instead of the generic
OPENAI_COMPATIBLE_* vars.

Configuration (env vars)
────────────────────────
LLM_FALLBACK_PROVIDER=cerebras     (or LLM_SECOND_FALLBACK_PROVIDER)
CEREBRAS_API_KEY                   — required
CEREBRAS_BASE_URL                  — defaults to https://api.cerebras.ai/v1
CEREBRAS_MODEL                     — defaults to llama-3.3-70b
CEREBRAS_TEMPERATURE               — defaults to 0.3
CEREBRAS_MAX_TOKENS                — defaults to 2048
CEREBRAS_TIMEOUT                   — HTTP timeout in seconds, defaults to 60
"""

from __future__ import annotations

from app.core.config import settings
from app.llm.openai_provider import OpenAICompatibleProvider


class CerebrasProvider(OpenAICompatibleProvider):
    """
    Cerebras Cloud API — OpenAI-compatible chat completions.

    Inherits all retry, JSON-parsing, and error-handling logic from
    OpenAICompatibleProvider.  Only the connection parameters differ.
    """

    provider_name = "cerebras"

    def __init__(self) -> None:
        super().__init__(
            api_key=settings.CEREBRAS_API_KEY,
            base_url=settings.CEREBRAS_BASE_URL.rstrip("/"),
            model=settings.CEREBRAS_MODEL,
            default_temperature=settings.CEREBRAS_TEMPERATURE,
            default_max_tokens=settings.CEREBRAS_MAX_TOKENS,
            default_timeout=settings.CEREBRAS_TIMEOUT,
        )
