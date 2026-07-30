"""Tests for the agent loader and the end-to-end agent runner (offline, stub provider)."""

from pathlib import Path

import pytest

from firm.core.agents.loader import load_agent
from firm.core.agents.runner import AgentValidationError, run_agent
from firm.core.llm.provider import LLMResponse
from firm.schemas.agents import ForensicAccountantOutput

REPO = Path(__file__).resolve().parents[2]

VALID_JSON = (
    '{"agent":"forensic_accountant","agent_version":"1.0.0","ticker":"ACME",'
    '"as_of":"2026-07-23","disconfirming_search":"searched related-party notes; none",'
    '"verdict":"PASS","flags":[],"veto":false}'
)


class FakeProvider:
    name = "fake"

    def __init__(self, texts: list[str]) -> None:
        self._texts = texts
        self.calls = 0

    def complete(self, req) -> LLMResponse:
        text = self._texts[min(self.calls, len(self._texts) - 1)]
        self.calls += 1
        return LLMResponse(text=text, model=req.model, input_tokens=1, output_tokens=1)


def _run(provider):
    return run_agent(
        provider, system="house style", user="analyse ACME", model="test",
        schema=ForensicAccountantOutput, max_retries=2,
    )


def test_load_real_agent_file():
    spec = load_agent(REPO / "agents" / "forensic_accountant.md")
    assert spec.name == "forensic_accountant"
    assert spec.output_schema.endswith("ForensicAccountantOutput")
    assert "absolute veto" in spec.body.lower()


def test_load_agent_without_frontmatter_raises(tmp_path):
    p = tmp_path / "bad.md"
    p.write_text("no frontmatter here")
    with pytest.raises(ValueError):
        load_agent(p)


def test_runner_happy_path():
    provider = FakeProvider([VALID_JSON])
    out = _run(provider)
    assert out.verdict == "PASS" and provider.calls == 1


def test_runner_retries_then_succeeds():
    provider = FakeProvider(["this is not json", VALID_JSON])
    out = _run(provider)
    assert out.verdict == "PASS" and provider.calls == 2


def test_runner_hard_fails_after_retries():
    provider = FakeProvider(["nope", "still nope", "nope again"])
    with pytest.raises(AgentValidationError):
        _run(provider)
    assert provider.calls == 3
