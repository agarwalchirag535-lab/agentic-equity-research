"""The Phase-4 judgment tier reaches the page (ADR-0070).

Four agents have existed as prompts and schemas since Phase 0 and rendered nothing: `valuation_modeler`,
`thesis_synthesizer`, `red_team`, `portfolio_manager`. An agent that runs, enters `agent_versions` and
has its narrative dropped is the ADR-0034 failure — the reader cannot tell it from one that never ran.

The invariant with teeth here is Law 1 in its most tempting place. The judgment tier is where an LLM
would most plausibly author a number: a value per share, a return multiple, an expectancy. The agent
supplies PROBABILITIES and prose; the compute layer supplies every figure, and a restated figure that
disagrees with the priced grid fails the run.
"""

from __future__ import annotations

from datetime import date

import pytest

from firm.core.pipeline.deep_dive import (
    AgentDisciplineError,
    agent_facts_payload,
    plan_agents,
    run_deep_dive,
)
from firm.core.report.render import render_markdown
from tests.conftest import AS_OF, agent_answer, clean_answers, filing_for, seed_store
from tests.pipeline.test_valuation_wiring import seed_price, valuable_series

JUDGMENT = ("valuation_modeler", "thesis_synthesizer", "red_team", "portfolio_manager")


def judgment_answers(ticker: str, *, scenarios: list[dict] | None = None) -> dict[str, str]:
    """Law-abiding answers for the four judgment agents: probabilities and prose, no authored numbers."""
    extra = {
        "valuation_modeler": {
            # Both scalars null: the compute layer authors them (Law 1). A value here would be the
            # agent doing the arithmetic itself.
            "reverse_dcf_implied_growth": None, "base_case_value_per_share": None,
            "scenarios": scenarios if scenarios is not None else [],
        },
        "thesis_synthesizer": {
            "return_multiple_if": "volumes hold, the amine spread does not compress, and no equity "
                                  "is issued to fund the next plant",
            "three_load_bearing_assumptions": [
                "The per-tonne realisation holds near the current cycle average.",
                "Capex converts to commissioned capacity rather than perpetual CWIP.",
                "No related-party lending emerges in the Schedule III rows.",
            ],
            "feasibility_verdict": "SELF_FUNDED",
        },
        "red_team": {
            "bear_case": "The realised growth rate is the cycle, not the trend: a single trough year "
                         "sets the base and the grid inherits it.",
            "base_rate_of_failure": None,
            "kill_criteria": ["Cumulative cash conversion falls below the policy floor."],
        },
        "portfolio_manager": {
            "position_size_pct": None, "expectancy": None,
            "staged_entry": "Stage against disclosure, not against price.",
        },
    }
    return {a: agent_answer(a, ticker, e) for a, e in extra.items()}


PHASE2 = ("business_analyst", "financial_statement_analyst", "forensic_accountant")


def _run(store, tmp_path, *, ticker="CLEANCO", judgment=None, staffed=True, price=1500.0):
    """Run with or without the judgment tier. `staffed=False` is the Phase-3 roster, unchanged."""
    seed_store(store, ticker, valuable_series())
    if price is not None:
        seed_price(store, ticker, price, date(2026, 7, 28))
    answers = dict(clean_answers(ticker))
    agents = PHASE2
    if staffed:
        answers.update(judgment if judgment is not None else judgment_answers(ticker))
        agents = (*PHASE2, *JUDGMENT)
    return run_deep_dive(
        store, ticker, AS_OF, answers=answers, filing=filing_for(ticker),
        company_name=f"{ticker} Limited", agents=agents,
        reports_root=tmp_path, write=True, memory_root=tmp_path)


def test_the_roster_can_finally_staff_the_portfolio_manager():
    """`prices` was listed as its prerequisite, and as NOT INGESTED, since Phase 3."""
    with_prices, _ = plan_agents(phase=4, available_inputs=["financials", "prices"])
    without, gaps = plan_agents(phase=4, available_inputs=["financials"])

    assert "portfolio_manager" in with_prices
    assert "portfolio_manager" not in without
    assert any("portfolio_manager" in g and "prices" in g for g in gaps)


def test_the_priced_grid_reaches_the_agent_that_must_argue_with_it(store):
    """Scenario ROWS are not derivations, so they do not reach the agent through `computed_metrics`.
    Without them `valuation_modeler` would be asked to assign probabilities to scenarios it cannot see."""
    from firm.core.compute.quality import ForensicMetrics, ForensicScreenResult, ForensicVerdict
    from firm.core.config import load_thresholds
    from firm.core.pipeline import derive as D
    from firm.core.pipeline.checks import CheckEvaluation
    from firm.core.pipeline.valuation import load_valuation
    from firm.core.report.assemble import NotesReview

    seed_store(store, "ACME", valuable_series())
    seed_price(store, "ACME", 1000.0, date(2026, 7, 28))
    facts = D.load_company_facts(store, "ACME", AS_OF)
    derived = D.derive_metrics(facts)
    valuation = load_valuation(store, "ACME", AS_OF, facts, derived,
                               policy=load_thresholds()["valuation"])

    payload = agent_facts_payload(
        derived, CheckEvaluation((), ForensicMetrics(), ()),
        ForensicScreenResult(ForensicVerdict.PASS, False, []), None, [], NotesReview(),
        valuation=valuation)

    assert payload["valuation"]["status"] == "valued"
    assert {s["name"] for s in payload["valuation"]["scenarios"]} == {
        "disaster", "bear", "base", "bull"}
    assert "Law-1 violation" in payload["valuation"]["rule"]
    # The policy that produced them travels with them — the agent must see the discount rate it is
    # arguing about rather than inferring one.
    assert payload["valuation"]["assumptions"]["discount_rate"] > 0


def test_all_four_judgment_agents_render(store, tmp_path):
    result = _run(store, tmp_path)
    report = result.report
    markdown = render_markdown(report)

    for agent in JUDGMENT:
        assert agent in report.agent_versions, f"{agent} did not run"

    # thesis_synthesizer owns the thesis, and its load-bearing assumptions are listed rather than
    # buried — they are the part a reader checks first.
    assert "if and only if" in report.thesis
    assert "amine spread does not compress" in report.thesis
    assert "load-bearing assumptions" in report.thesis
    # red_team's bear case is structural in the anti-thesis, not an appendix.
    assert "red_team (bear case)" in report.anti_thesis
    assert "the cycle, not the trend" in report.anti_thesis
    assert "red_team (kill criterion)" in report.anti_thesis
    # the valuation section carries the analysts who argued with the computed grid
    assert "valuation_modeler" in report.valuation_narrative
    assert "portfolio_manager" in report.valuation_narrative
    assert "Stage against disclosure" in markdown


def test_an_agent_that_restates_a_computed_multiple_differently_fails_the_run(store, tmp_path):
    """Law 1 at the single easiest place to launder an invented number through this system.

    `ScenarioLine.return_multiple` is checked item by item against the priced grid (ADR-0062), so an
    agent writing "bull: 4.2x" beside a computed 0.03x does not merely get corrected — the run fails.
    """
    invented = [{"name": "bull", "probability": 0.25, "return_multiple": 4.2}]
    with pytest.raises(AgentDisciplineError) as caught:
        _run(store, tmp_path, judgment=judgment_answers("CLEANCO", scenarios=invented))
    assert "valuation_modeler" in str(caught.value)


def test_the_valuation_note_never_claims_a_tier_that_rendered_is_missing(store, tmp_path):
    """The stale-prose failure in its general form: a report must not describe a run other than its own."""
    unstaffed = _run(store, tmp_path, staffed=False)
    assert "not staffed in this run" in unstaffed.report.valuation_narrative

    staffed = _run(store, tmp_path)
    assert "not staffed in this run" not in staffed.report.valuation_narrative
