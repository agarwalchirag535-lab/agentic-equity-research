"""Tests for the LLM provider abstraction + disk cache (offline; no API key)."""

import pytest

from firm.core.llm.cache import DiskCache, make_key
from firm.core.llm.provider import (
    AnthropicAdapter,
    CachingProvider,
    ClaudeCodeAdapter,
    LLMRequest,
    LocalAdapter,
    OpenAIAdapter,
    build_provider,
)


def _req() -> LLMRequest:
    return LLMRequest(system="you are an analyst", prompt="summarise ACME", model="test-model")


def test_local_adapter_is_deterministic():
    a = LocalAdapter()
    r1, r2 = a.complete(_req()), a.complete(_req())
    assert r1.text == r2.text
    assert r1.input_tokens > 0 and r1.output_tokens > 0
    assert r1.cached is False


def test_make_key_stable_and_distinct():
    assert make_key("a", "b") == make_key("a", "b")
    assert make_key("a", "b") != make_key("a", "c")


def test_disk_cache_roundtrip(tmp_path):
    c = DiskCache(tmp_path / "cache")
    assert c.get("missing") is None
    c.set("k", {"text": "hi"})
    assert c.get("k") == {"text": "hi"}


def test_caching_provider_miss_then_hit(tmp_path):
    provider = CachingProvider(LocalAdapter(), DiskCache(tmp_path / "c"))
    first = provider.complete(_req())
    second = provider.complete(_req())
    assert first.cached is False
    assert second.cached is True
    assert first.text == second.text


def test_build_provider():
    assert isinstance(build_provider("local"), LocalAdapter)
    assert isinstance(build_provider("claude_code"), ClaudeCodeAdapter)
    assert isinstance(build_provider("anthropic"), AnthropicAdapter)
    assert isinstance(build_provider("openai"), OpenAIAdapter)
    with pytest.raises(ValueError):
        build_provider("nope")


def test_claude_code_adapter_with_injected_runner():
    captured = {}

    def fake_runner(cmd, stdin_text, timeout):
        captured["cmd"] = cmd
        captured["stdin"] = stdin_text
        return '{"ok": true}\n'

    adapter = ClaudeCodeAdapter(runner=fake_runner)
    resp = adapter.complete(_req())
    assert resp.text == '{"ok": true}'
    assert resp.model == "claude-code"
    assert captured["cmd"][0] == "claude" and "-p" in captured["cmd"]
    assert "you are an analyst" in captured["stdin"]


def test_claude_code_adapter_missing_cli_raises():
    adapter = ClaudeCodeAdapter(binary="definitely-not-a-real-binary-xyz")
    with pytest.raises(RuntimeError):
        adapter.complete(_req())


def test_real_adapters_require_a_key():
    with pytest.raises(RuntimeError):
        AnthropicAdapter().complete(_req())
    with pytest.raises(RuntimeError):
        OpenAIAdapter().complete(_req())
