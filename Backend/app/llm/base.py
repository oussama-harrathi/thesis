"""
LLM provider base interface.

All concrete providers must implement BaseLLMProvider.  The contract:

  generate_json(prompt, schema, settings=None) -> T (instance of schema)
      Call the underlying model with *prompt* and instruct it to return
      strict JSON matching *schema*.  Parse and return a validated
      Pydantic model instance.  On JSON parse failure the base class
      helper ``_parse_with_retry`` should be used.

  health_check() -> bool
      Return True if the provider endpoint is reachable and functional.

GenerationSettings
──────────────────
Optional per-call overrides for temperature, max_tokens, and timeout.
If not supplied, provider-level defaults (from config) are used.

Usage
─────
    from app.llm.base import BaseLLMProvider, GenerationSettings
    from pydantic import BaseModel

    class MyOutput(BaseModel):
        answer: str
        confidence: float

    provider: BaseLLMProvider = ...
    result: MyOutput = await provider.generate_json(
        "Classify the topic ...",
        MyOutput,
    )
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, TypeVar, overload

from pydantic import BaseModel, ValidationError

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


# ── Generation settings ───────────────────────────────────────────────────────


@dataclass
class GenerationSettings:
    """
    Per-request overrides for generation parameters.

    All fields are optional.  Providers fall back to their env-var defaults
    when a field is None.
    """

    temperature: float | None = None
    max_tokens: int | None = None
    timeout: float | None = None
    # Extra provider-specific kwargs (e.g. top_p, seed) passed through as-is.
    extra: dict = field(default_factory=dict)


# ── Base class ────────────────────────────────────────────────────────────────


class BaseLLMProvider(ABC):
    """
    Abstract base for all LLM provider adapters.

    Subclasses must implement:
        generate_json(prompt, schema, settings=None) -> T
        health_check() -> bool

    Optional override:
        provider_name (str class attribute)
    """

    provider_name: str = "base"

    # ── Abstract interface ────────────────────────────────────────

    @abstractmethod
    async def generate_json(
        self,
        prompt: str,
        schema: type[T],
        settings: GenerationSettings | None = None,
    ) -> T:
        """
        Send *prompt* to the model, parse the response as *schema*.

        Parameters
        ----------
        prompt   : Full prompt string (system + user context already merged).
        schema   : Pydantic model class — defines the expected JSON shape.
        settings : Optional per-call overrides for temperature, tokens, etc.

        Returns
        -------
        Validated instance of *schema*.

        Raises
        ------
        LLMParseError      : JSON response could not be parsed after retries.
        LLMProviderError   : Network / API error from the provider.
        """

    @abstractmethod
    async def health_check(self) -> bool:
        """Return True if the provider is reachable and functional."""

    # ── Shared helpers ────────────────────────────────────────────

    def _parse_response(self, raw_text: str, schema: type[T]) -> T:
        """
        Parse and validate a raw JSON string against *schema*.

        Strategy
        ────────
        1. Direct json.loads + schema.model_validate.
        2. If the model wrapped JSON in a markdown code block, strip it first.

        Raises LLMParseError if both attempts fail.
        """
        # Attempt 1: direct parse
        try:
            return schema.model_validate(json.loads(raw_text))
        except (json.JSONDecodeError, ValidationError, ValueError):
            pass

        # Attempt 2: strip markdown code fences  ```json ... ``` or ``` ... ```
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            # drop first line (```json or ```) and last line (```)
            inner = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])
            try:
                return schema.model_validate(json.loads(inner))
            except (json.JSONDecodeError, ValidationError, ValueError):
                pass

        # Attempt 3: find first { ... } or [ ... ] block in the text
        for start_char, end_char in [("{", "}"), ("[", "]")]:
            start = cleaned.find(start_char)
            end = cleaned.rfind(end_char)
            if start != -1 and end > start:
                try:
                    return schema.model_validate(json.loads(cleaned[start : end + 1]))
                except (json.JSONDecodeError, ValidationError, ValueError):
                    pass

        raise LLMParseError(
            f"[{self.provider_name}] Could not parse model response as "
            f"{schema.__name__}.\nRaw response (first 500 chars):\n"
            f"{raw_text[:500]}"
        )

    def _build_json_instruction(self, schema: type[BaseModel]) -> str:
        """
        Return a short instruction appended to every prompt that tells the
        model to respond with valid JSON matching *schema*.
        """
        schema_json = json.dumps(schema.model_json_schema(), indent=2)
        return (
            "\n\n---\n"
            "Respond with ONLY a valid JSON object that strictly conforms to "
            "the following JSON Schema.  Do NOT include any explanation, "
            "markdown, or text outside the JSON.\n\n"
            f"Schema:\n{schema_json}"
        )


# ── Custom exceptions ─────────────────────────────────────────────────────────


class LLMError(Exception):
    """Base class for all LLM provider errors."""


class LLMParseError(LLMError):
    """Raised when the model response cannot be parsed as the expected schema."""


class LLMProviderError(LLMError):
    """Raised when the provider API returns an error or is unreachable."""
