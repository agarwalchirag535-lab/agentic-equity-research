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
    build_provider,
)

__all__ = [
    "DiskCache", "make_key",
    "AnthropicAdapter", "CachingProvider", "ClaudeCodeAdapter", "LLMRequest", "LLMResponse",
    "LocalAdapter", "OpenAIAdapter", "Provider", "build_provider",
]
