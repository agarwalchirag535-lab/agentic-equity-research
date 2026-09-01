"""Two Law-1/house-style checks that existed and were never called (ADR-0080).

Both are the shape already found three times today: written in Phase 0, unit-tested, wired to nothing.

* **`validators/hedge.py`** — and this one is the sharpest yet, because the system *told its agents the
  check existed*. `agents/_shared/house_style.md` §1 says verbatim that "a `hedge_detector` flags vague
  quantifiers ... and forces a number", and `agents/_shared/forbidden.md` lists them under "anti-patterns
  that fail a run". Neither was true. A prompt asserting an enforcement that does not exist is worse
  than one that asks politely: the agent is taught the rule is checked and has no way to learn otherwise.
* **`scenarios.validate_probabilities`** — reachable only from two functions that were themselves never
  called, so `valuation_modeler` could return bull 0.8 / base 0.8 / bear 0.8 and pass every gate. That
  is not an optimistic view; it is not a view at all. One field to the left of `_scenario_discipline`,
  which had the same defect and was fixed this morning.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from firm.core.pipeline.deep_dive import (
    AgentDisciplineError,
    _hedge_problems,
    _probability_problems,
)
from firm.schemas.agents import BusinessAnalystOutput, ScenarioLine, ValuationModelerOutput
from tests.conftest import AS_OF


def _business(**kw) -> BusinessAnalystOutput:
    base = {
        "agent": "business_analyst", "agent_version": "1.0.0", "ticker": "ACME", "as_of": AS_OF,
        "observations": [], "inferences": [], "speculations": [],
        "open_questions": ["What is the top-customer share?"],
        "disconfirming_search": "Looked for a receivables run-up and found none.",
        "narrative": "The computed table carries the figures.",
        "what_it_does": "Manufactures amines.", "moat": "Process know-how.",
        "customer_concentration": None, "national_relevance": True,
    }
    return BusinessAnalystOutput(**{**base, **kw})


def _valuation(scenarios) -> ValuationModelerOutput:
    return ValuationModelerOutput(
        agent="valuation_modeler", agent_version="1.0.0", ticker="ACME", as_of=AS_OF,
        observations=[], inferences=[], speculations=[], open_questions=["What is the exit multiple?"],
        disconfirming_search="Checked whether the price implies growth no peer has sustained.",
        narrative="The grid is priced against the quoted close.",
        reverse_dcf_implied_growth=None, base_case_value_per_share=None, scenarios=scenarios)


# ---- the hedge detector ----------------------------------------------------------------------------
def test_an_adjective_standing_in_for_a_number_is_caught():
    problems = _hedge_problems(_business(narrative="Margins are healthy and growth has been strong."))
    assert problems and "healthy" in problems[0] and "strong" in problems[0]
    assert "house style §1" in problems[0]


def test_the_same_adjective_beside_a_cited_figure_is_fine():
    """`forbidden.md` bans a vague quantifier "without a number". Applying the rule as WRITTEN matters
    in both directions — a bare word match would fail a sentence doing exactly what house style asks."""
    assert _hedge_problems(_business(
        narrative="Margins improved to a strong 24.1% [fact:derived:ebitda_margin].")) == []


def test_every_authored_field_is_scanned_not_just_the_narrative():
    """The citation check learned this lesson already: an invented figure rode in through a field
    nobody was looking at. The hedge scan uses the same schema-derived walk."""
    assert _hedge_problems(_business(moat="A robust position in a niche.")) != []
    assert _hedge_problems(_business(what_it_does="Sells into a significant end market.")) != []


def test_clean_prose_passes_untouched():
    assert _hedge_problems(_business()) == []


# ---- scenario probabilities ------------------------------------------------------------------------
def _line(name: str, probability: float, multiple: float = 1.0) -> ScenarioLine:
    return ScenarioLine(name=name, probability=probability, return_multiple=multiple)


def test_probabilities_that_do_not_sum_to_one_are_rejected():
    """bull 0.8 / base 0.8 / bear 0.8 is not an optimistic view — it is not a view at all."""
    problems = _probability_problems(_valuation(
        [_line("bull", 0.8), _line("base", 0.8), _line("bear", 0.8)]))
    assert problems and "sum to 1" in problems[0]


def test_a_coherent_distribution_passes():
    assert _probability_problems(_valuation(
        [_line("bull", 0.25), _line("base", 0.5), _line("bear", 0.25)])) == []


def test_the_schema_already_bounds_each_value_so_only_the_SUM_needs_a_check():
    """Worth stating, because it explains why this check is small. `ScenarioLine.probability` is
    `Field(ge=0, le=1)`, so pydantic rejects a negative or >1 weight before this function runs. What a
    per-field schema cannot express is that the set is a DISTRIBUTION — that is the whole job here."""
    with pytest.raises(ValidationError):
        _line("bull", 1.4)
    # Individually legal, collectively meaningless — exactly the gap the schema leaves open.
    assert _probability_problems(_valuation([_line("bull", 0.9), _line("bear", 0.9)]))


def test_an_agent_with_no_scenarios_is_not_penalised():
    assert _probability_problems(_valuation([])) == []
    assert _probability_problems(_business()) == []


# ---- both are wired into the run -------------------------------------------------------------------
def test_the_run_fails_on_incoherent_probabilities(store, tmp_path):
    from tests.pipeline.test_judgment_tier import _run, judgment_answers

    invented = [{"name": "bull", "probability": 0.8, "return_multiple": 1.0},
                {"name": "base", "probability": 0.8, "return_multiple": 1.0}]
    with pytest.raises(AgentDisciplineError) as caught:
        _run(store, tmp_path, judgment=judgment_answers("CLEANCO", scenarios=invented))
    # The multiples are wrong too, so the run would fail regardless — assert the PROBABILITY check is
    # what spoke, otherwise this test would pass while the thing it exists to prove stayed unwired.
    assert "valuation_modeler" in str(caught.value)
    assert "sum to 1" in str(caught.value)


def test_the_run_fails_on_an_unquantified_adjective(store, tmp_path):
    from firm.core.pipeline.deep_dive import run_deep_dive
    from tests.conftest import agent_answer, clean_answers, clean_series, filing_for, seed_store

    seed_store(store, "CLEANCO", clean_series())
    answers = dict(clean_answers("CLEANCO"))
    answers["business_analyst"] = agent_answer(
        "business_analyst", "CLEANCO",
        {"what_it_does": "Manufactures amines.", "moat": "Process know-how.",
         "customer_concentration": None, "national_relevance": True},
        narrative="The company has delivered strong growth and healthy margins throughout.")

    with pytest.raises(AgentDisciplineError) as caught:
        run_deep_dive(store, "CLEANCO", AS_OF, answers=answers, filing=filing_for("CLEANCO"),
                      company_name="Cleanco Limited", reports_root=tmp_path, write=True,
                      memory_root=tmp_path)
    assert "business_analyst" in str(caught.value)
