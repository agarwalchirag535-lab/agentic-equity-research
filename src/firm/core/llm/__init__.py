"""LLM provider abstraction + caching (Laws 5 & 6)."""

from firm.core.llm.cache import DiskCache, make_key
from firm.core.llm.provider import (
    AnthropicAdapter,
    CachingProvider,
    ClaudeCodeAdapter,
    LLMRequest,
    LLMResponse,
    LocalAdapter,
    OpenAIAdapter,
    Provider,
    StaticProvider,
    build_provider,
)

__all__ = [
    "AnthropicAdapter",
    "CachingProvider",
    "ClaudeCodeAdapter",
    "DiskCache",
    "LLMRequest",
    "LLMResponse",
    "LocalAdapter",
    "OpenAIAdapter",
    "Provider",
    "StaticProvider",
    "build_provider",
    "make_key",
]
