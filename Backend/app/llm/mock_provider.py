"""
Mock LLM provider — for testing and development without a real API.

The mock provider returns pre-configured responses (fixtures) or
auto-generates minimal valid instances from the Pydantic schema.

Configuration (env vars)
────────────────────────
LLM_PROVIDER=mock

No API keys required.

Usage in tests
──────────────
    from app.llm.mock_provider import MockProvider
    from pydantic import BaseModel

    class MyOutput(BaseModel):
        label: str
        score: float

    provider = MockProvider(responses=[{"label": "easy", "score": 0.8}])
    result = await provider.generate_json("classify...", MyOutput)
    assert result.label == "easy"

    # Or: use auto-generated defaults (empty strings, 0s, etc.)
    provider = MockProvider()
    result = await provider.generate_json("anything", MyOutput)
"""

from __future__ import annotations

import inspect
import logging
from typing import Any, TypeVar

from pydantic import BaseModel

from app.llm.base import BaseLLMProvider, GenerationSettings, LLMProviderError

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


class MockProvider(BaseLLMProvider):
    """
    Deterministic mock provider for unit and integration testing.

    Parameters
    ----------
    responses : list[dict] | None
        Optional queue of raw dict responses to return in order.
        When the queue is exhausted (or None), auto-generates a minimal
        valid instance using Pydantic's default/zero values.
    always_fail : bool
        If True, generate_json always raises LLMProviderError.
        Useful for testing error-handling paths.
    health : bool
        Value returned by health_check().
    """

    provider_name = "mock"

    def __init__(
        self,
        responses: list[dict] | None = None,
        *,
        always_fail: bool = False,
        health: bool = True,
    ) -> None:
        self._responses: list[dict] = list(responses or [])
        self._always_fail = always_fail
        self._health = health
        self.call_count: int = 0          # inspectable in tests
        self.last_prompt: str | None = None

    # ── Public API ────────────────────────────────────────────────

    async def generate_json(
        self,
        prompt: str,
        schema: type[T],
        settings: GenerationSettings | None = None,
    ) -> T:
        self.call_count += 1
        self.last_prompt = prompt

        if self._always_fail:
            raise LLMProviderError("[mock] Configured to always fail.")

        if self._responses:
            raw = self._responses.pop(0)
            logger.debug("[mock] returning pre-configured response: %s", raw)
            return schema.model_validate(raw)

        # Auto-generate a minimal valid instance
        instance = _auto_instance(schema)
        logger.debug("[mock] auto-generated instance: %s", instance)
        return instance

    async def health_check(self) -> bool:
        return self._health

    def queue_response(self, response: dict) -> None:
        """Append a response to the queue (utility for test setup)."""
        self._responses.append(response)


# ── Auto-instance generator ───────────────────────────────────────────────────


def _auto_instance(schema: type[T]) -> T:
    """
    Create a minimal valid instance of *schema* by filling each field
    with a sensible zero/default value based on its annotation.

    Supports: str, int, float, bool, list, dict, optional, nested BaseModel.
    """
    import typing

    data: dict[str, Any] = {}

    for name, field_info in schema.model_fields.items():
        annotation = field_info.annotation
        # Use the field's default if it has one
        if field_info.default is not None and not _is_pydantic_undefined(field_info.default):
            data[name] = field_info.default
            continue
        if field_info.default_factory is not None:  # type: ignore[misc]
            data[name] = field_info.default_factory()  # type: ignore[misc]
            continue

        data[name] = _zero_for(annotation)

    return schema.model_validate(data)


def _is_pydantic_undefined(value: Any) -> bool:
    try:
        from pydantic_core import PydanticUndefinedType  # type: ignore[import-untyped]
        return isinstance(value, PydanticUndefinedType)
    except ImportError:
        return repr(value) == "PydanticUndefined"


def _zero_for(annotation: Any) -> Any:
    """Return a zero/empty value appropriate for *annotation*."""
    import typing

    if annotation is None:
        return None

    origin = getattr(annotation, "__origin__", None)

    # Optional[X] → unwrap X
    if origin is typing.Union:
        args = annotation.__args__
        non_none = [a for a in args if a is not type(None)]
        if non_none:
            return _zero_for(non_none[0])
        return None

    # list[X]
    if origin is list:
        return []

    # dict[K, V]
    if origin is dict:
        return {}

    # Literal['a', 'b'] → pick first
    if origin is typing.Literal:
        return annotation.__args__[0]

    # Primitives
    if annotation is str:
        return ""
    if annotation is int:
        return 0
    if annotation is float:
        return 0.0
    if annotation is bool:
        return False

    # Nested Pydantic model
    if inspect.isclass(annotation) and issubclass(annotation, BaseModel):
        return _auto_instance(annotation)

    return None
