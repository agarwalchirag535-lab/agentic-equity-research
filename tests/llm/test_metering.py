"""Token metering and the run ceiling (ADR-0080, SPEC §9).

`BudgetGuard` was written in Phase 0 to abort a run on cost and was NEVER INSTANTIATED. Every
`LLMResponse` has carried `input_tokens`/`output_tokens` from the start and nothing summed them, so a
`deep-dive` against a paid API had no spend limit and no accounting — it could not abort on breach
because nothing was counting.

Two design choices are pinned here because both are easy to get wrong in a way that looks fine:

* **The ceiling counts tokens, not dollars.** Charging USD needs a price per model, and
  `config/models.yaml` still holds placeholder ids. Inventing prices would produce a number that looks
  like money and is not — the ADR-0078 error in a different costume.
* **A cache hit is free.** Charging it would make the ceiling punish the mechanism that saves money,
  and would make a resumed run (Law 5) fail where the first one passed.
"""

from __future__ import annotations

import pytest

from firm.core.llm.provider import LLMRequest, LLMResponse, MeteredProvider
from firm.core.orchestrator.budget import BudgetExceeded


class _Fake:
    """A provider whose replies the test dictates, including whether they were cached."""

    name = "fake"

    def __init__(self, *responses: LLMResponse) -> None:
        self._responses = list(responses)
        self.seen = 0

    def complete(self, req: LLMRequest) -> LLMResponse:
        self.seen += 1
        return self._responses[min(self.seen - 1, len(self._responses) - 1)]


def _resp(i: int = 100, o: int = 50, cached: bool = False) -> LLMResponse:
    return LLMResponse(text="{}", model="m", input_tokens=i, output_tokens=o, cached=cached)


def _req() -> LLMRequest:
    return LLMRequest(system="s", prompt="p", model="m", temperature=0.2)


def test_tokens_accumulate_across_calls():
    metered = MeteredProvider(_Fake(_resp()))
    for _ in range(3):
        metered.complete(_req())
    assert metered.calls == 3
    assert metered.input_tokens == 300 and metered.output_tokens == 150
    assert metered.total_tokens == 450


def test_the_ceiling_aborts_the_run():
    metered = MeteredProvider(_Fake(_resp()), ceiling_tokens=200)
    metered.complete(_req())                                  # 150, under
    with pytest.raises(BudgetExceeded) as caught:
        metered.complete(_req())                              # 300, over
    assert "300" in str(caught.value) and "200" in str(caught.value)
    assert "nothing was published" in str(caught.value)


def test_no_ceiling_means_no_limit_only_accounting():
    """Metering is unconditional so a run always reports what it consumed; the ceiling is opt-in."""
    metered = MeteredProvider(_Fake(_resp()))
    for _ in range(50):
        metered.complete(_req())
    assert metered.total_tokens == 7500          # counted, never blocked


def test_a_cache_hit_is_free():
    """Charging it would punish the thing that saves money and break a resumed run (Law 5)."""
    metered = MeteredProvider(_Fake(_resp(cached=True)), ceiling_tokens=10)
    for _ in range(5):
        metered.complete(_req())
    assert metered.total_tokens == 0
    assert metered.calls == 5                    # still recorded, so a reader sees the cache working


def test_the_ledger_shows_where_a_run_spent():
    metered = MeteredProvider(_Fake(_resp(10, 5), _resp(20, 7, cached=True)))
    metered.complete(_req())
    metered.complete(_req())
    assert metered.ledger == [("m", 10, 5, False), ("m", 20, 7, True)]


def test_retries_are_counted_because_that_is_where_cost_escapes():
    """The seam is the provider, not the agent loop: three attempts per agent is exactly the cost a
    per-agent counter would miss."""
    from firm.core.agents.runner import AgentValidationError, run_agent
    from firm.schemas.agents import ForensicAccountantOutput

    metered = MeteredProvider(_Fake(LLMResponse(text="not json", model="m",
                                                input_tokens=100, output_tokens=50)))
    with pytest.raises(AgentValidationError):
        run_agent(metered, system="s", user="u", model="m", schema=ForensicAccountantOutput)
    assert metered.calls == 3                    # the retries, counted
    assert metered.total_tokens == 450
