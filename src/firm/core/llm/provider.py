"""Single LLM interface (Law 6). Swap providers via config, never in code.

The compute and validator layers never call this — only agents do. `LocalAdapter` is deterministic and
offline so the whole harness is runnable and testable without any API key. Real providers are imported
lazily so the package imports cleanly with neither SDK installed.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from typing import Callable, Protocol

from firm.core.llm.cache import DiskCache, make_key


@dataclass(frozen=True)
class LLMRequest:
    system: str
    prompt: str
    model: str
    temperature: float = 0.2
    max_tokens: int = 4000


@dataclass(frozen=True)
class LLMResponse:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    cached: bool = False


class Provider(Protocol):
    name: str

    def complete(self, req: LLMRequest) -> LLMResponse: ...


def _approx_tokens(s: str) -> int:
    return max(1, len(s) // 4)


class LocalAdapter:
    """Deterministic, offline. Echoes a reproducible response for tests and dry-runs."""

    name = "local"

    def complete(self, req: LLMRequest) -> LLMResponse:
        text = f"[local:{req.model}] {req.prompt[:200]}"
        return LLMResponse(
            text=text,
            model=req.model,
            input_tokens=_approx_tokens(req.system) + _approx_tokens(req.prompt),
            output_tokens=_approx_tokens(text),
        )


class AnthropicAdapter:
    name = "anthropic"

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key

    def complete(self, req: LLMRequest) -> LLMResponse:
        if not self._api_key:
            raise RuntimeError("AnthropicAdapter needs an API key (set ANTHROPIC_API_KEY).")
        import anthropic  # lazy — only needed when actually calling the API

        client = anthropic.Anthropic(api_key=self._api_key)
        msg = client.messages.create(
            model=req.model, max_tokens=req.max_tokens, temperature=req.temperature,
            system=req.system, messages=[{"role": "user", "content": req.prompt}],
        )
        return LLMResponse(
            text=msg.content[0].text, model=req.model,
            input_tokens=msg.usage.input_tokens, output_tokens=msg.usage.output_tokens,
        )


class OpenAIAdapter:
    name = "openai"

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key

    def complete(self, req: LLMRequest) -> LLMResponse:
        if not self._api_key:
            raise RuntimeError("OpenAIAdapter needs an API key (set OPENAI_API_KEY).")
        import openai  # lazy

        client = openai.OpenAI(api_key=self._api_key)
        resp = client.chat.completions.create(
            model=req.model, temperature=req.temperature, max_tokens=req.max_tokens,
            messages=[{"role": "system", "content": req.system},
                      {"role": "user", "content": req.prompt}],
        )
        usage = resp.usage
        return LLMResponse(
            text=resp.choices[0].message.content, model=req.model,
            input_tokens=usage.prompt_tokens, output_tokens=usage.completion_tokens,
        )


def _default_cli_runner(cmd: list[str], stdin_text: str, timeout: float) -> str:
    if shutil.which(cmd[0]) is None:
        raise RuntimeError(
            f"`{cmd[0]}` CLI not found on PATH — run inside Claude Code, or install the CLI."
        )
    proc = subprocess.run(  # noqa: S603 (fixed argv, no shell)
        cmd, input=stdin_text, capture_output=True, text=True, timeout=timeout
    )
    if proc.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed (exit {proc.returncode}): {proc.stderr[:400]}")
    return proc.stdout


class ClaudeCodeAdapter:
    """Run agents on a Claude Code subscription (Pro/Max) — no API key, no per-token billing (Law 6).

    Shells out to the headless `claude -p` CLI. Use this when running inside a Claude Code terminal.
    The subprocess runner is injectable so this is unit-testable without the CLI installed.
    """

    name = "claude_code"

    def __init__(
        self,
        binary: str = "claude",
        runner: Callable[[list[str], str, float], str] | None = None,
        timeout: float = 300.0,
    ) -> None:
        self._binary = binary
        self._runner = runner or _default_cli_runner
        self._timeout = timeout

    def complete(self, req: LLMRequest) -> LLMResponse:
        prompt = f"{req.system}\n\n{req.prompt}" if req.system else req.prompt
        text = self._runner([self._binary, "-p", "--output-format", "text"], prompt, self._timeout)
        return LLMResponse(
            text=text.strip(), model="claude-code",
            input_tokens=_approx_tokens(prompt), output_tokens=_approx_tokens(text),
        )


class CachingProvider:
    """Wraps any provider with the Law-5 disk cache."""

    def __init__(self, inner: Provider, cache: DiskCache) -> None:
        self._inner = inner
        self._cache = cache
        self.name = f"cached:{inner.name}"

    def complete(self, req: LLMRequest) -> LLMResponse:
        key = make_key(self._inner.name, req.model, f"{req.temperature}", req.system, req.prompt)
        hit = self._cache.get(key)
        if hit is not None:
            return LLMResponse(
                text=hit["text"], model=hit["model"],
                input_tokens=hit["input_tokens"], output_tokens=hit["output_tokens"], cached=True,
            )
        resp = self._inner.complete(req)
        self._cache.set(key, {
            "text": resp.text, "model": resp.model,
            "input_tokens": resp.input_tokens, "output_tokens": resp.output_tokens,
        })
        return resp


def build_provider(name: str, api_key: str | None = None) -> Provider:
    if name == "local":
        return LocalAdapter()
    if name == "claude_code":
        return ClaudeCodeAdapter()
    if name == "anthropic":
        return AnthropicAdapter(api_key)
    if name == "openai":
        return OpenAIAdapter(api_key)
    raise ValueError(f"unknown provider: {name}")
