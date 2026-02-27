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


def get_llm_provider() -> BaseLLMProvider:
    """
    Instantiate and return the LLM provider selected by ``LLM_PROVIDER``.

    The provider is freshly instantiated on each call (no singleton).
    For long-lived use-cases (e.g. a request lifespan) the caller should
    cache the returned instance.

    Raises
    ------
    ValueError  : if LLM_PROVIDER is set to an unsupported value.
    ImportError : if the provider's required SDK is not installed
                  (e.g. google-generativeai for gemini).
    """
    provider_key = settings.LLM_PROVIDER.lower().strip()

    if provider_key not in _PROVIDER_MAP:
        supported = ", ".join(sorted(_PROVIDER_MAP.keys()))
        raise ValueError(
            f"Unsupported LLM_PROVIDER={provider_key!r}. "
            f"Supported values: {supported}"
        )

    dotted_path = _PROVIDER_MAP[provider_key]
    module_path, class_name = dotted_path.rsplit(".", 1)

    import importlib
    module = importlib.import_module(module_path)
    provider_class: type[BaseLLMProvider] = getattr(module, class_name)

    logger.info("LLM provider: %s (%s)", provider_key, dotted_path)
    return provider_class()
