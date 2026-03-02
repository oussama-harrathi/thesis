"""
LLM provider factory.

Call get_llm_provider() to obtain the active provider as configured by
the LLM_PROVIDER environment variable.

Supported values
────────────────
openai_compatible   OpenAICompatibleProvider  (Groq, OpenRouter, OpenAI, …)
gemini              GeminiProvider            (Google Gemini via AI Studio)
ollama              OllamaProvider            (local Ollama instance)
mock                MockProvider              (deterministic, no API calls)

Fallback
────────
Set LLM_FALLBACK_PROVIDER to any supported value to enable automatic
fallback: when the primary provider exhausts all retries (LLMProviderError),
the same call is transparently re-attempted using the fallback provider.

Example:
    LLM_PROVIDER=openai_compatible   # Groq
    LLM_FALLBACK_PROVIDER=gemini     # Google Gemini as fallback
"""

from __future__ import annotations

import logging

from app.core.config import settings
from app.llm.base import BaseLLMProvider

logger = logging.getLogger(__name__)

# Registry: provider name → import path (lazy to avoid importing heavy SDKs at startup)
_PROVIDER_MAP = {
    "openai_compatible": "app.llm.openai_provider.OpenAICompatibleProvider",
    "gemini": "app.llm.gemini_provider.GeminiProvider",
    "ollama": "app.llm.ollama_provider.OllamaProvider",
    "mock": "app.llm.mock_provider.MockProvider",
}


def _instantiate_provider(provider_key: str) -> BaseLLMProvider:
    """Resolve and instantiate a provider by its registry key."""
    key = provider_key.lower().strip()
    if key not in _PROVIDER_MAP:
        supported = ", ".join(sorted(_PROVIDER_MAP.keys()))
        raise ValueError(
            f"Unsupported provider key {key!r}. Supported values: {supported}"
        )
    dotted_path = _PROVIDER_MAP[key]
    module_path, class_name = dotted_path.rsplit(".", 1)
    import importlib
    module = importlib.import_module(module_path)
    provider_class: type[BaseLLMProvider] = getattr(module, class_name)
    return provider_class()


def get_llm_provider() -> BaseLLMProvider:
    """
    Instantiate and return the LLM provider selected by ``LLM_PROVIDER``.

    When ``LLM_FALLBACK_PROVIDER`` is also set, returns a ``FallbackProvider``
    that wraps the primary provider and transparently retries using the
    fallback when the primary raises ``LLMProviderError``.

    The provider is freshly instantiated on each call (no singleton).
    For long-lived use-cases (e.g. a request lifespan) the caller should
    cache the returned instance.

    Raises
    ------
    ValueError  : if LLM_PROVIDER or LLM_FALLBACK_PROVIDER is unsupported.
    ImportError : if a provider's required SDK is not installed.
    """
    provider_key = settings.LLM_PROVIDER.lower().strip()
    primary = _instantiate_provider(provider_key)
    logger.info("LLM primary provider: %s", provider_key)

    fallback_key = (settings.LLM_FALLBACK_PROVIDER or "").lower().strip()
    if fallback_key:
        fallback = _instantiate_provider(fallback_key)
        logger.info(
            "LLM fallback provider: %s (active after primary exhausts retries)",
            fallback_key,
        )
        from app.llm.fallback_provider import FallbackProvider
        return FallbackProvider(primary=primary, fallback=fallback)

    return primary
