"""
LLM provider package.

Import the factory function to get the active provider:

    from app.llm import get_llm_provider
    provider = get_llm_provider()
    result = await provider.generate_json(prompt, MySchema)
"""

from app.llm.factory import get_llm_provider

__all__ = ["get_llm_provider"]
