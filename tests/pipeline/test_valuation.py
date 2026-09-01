"""The valuation bridge (Phase 4, ADR-0062): facts + price + stated policy -> a priced scenario set."""

from __future__ import annotations

from datetime import date

from firm.core.config import valuation_policy
from firm.core.pipeline import derive as D
from firm.core.pipeline.valuation import valuation_derivations, value_company
from tests.conftest import AS_OF, clean_series, seed_store

POLICY = valuation_policy()


def _valuable_series(**overrides) -> dict:
    """`clean_series` plus the balance-sheet cash rows a net-debt figure needs."""
    return {
        **clean_series(),
        "balance_sheet:Cash Equivalents": [50, 60, 70, 80, 90, 100],
        "balance_sheet:Other Bank Balances": [10, 10, 10, 10, 10, 10],
        **overrides,
    }


def _priced(store, series=None, price=2044.40):
    seed_store(store, "ACME", series if series is not None else _valuable_series())
    facts = D.load_company_facts(store, "ACME", AS_OF)
    derived = D.derive_metrics(facts)
    return facts, derived, value_company(facts, derived, price=price, price_on=date(2026, 8, 28),
                                         policy=POLICY)


def test_a_company_with_price_and_cash_flow_is_valued_against_its_own_growth(store):
    facts, _derived, v = _priced(store)
    assert v.valued and v.missing == ()
    # Share count is the filing's OWN identity, PAT / EPS — not a face-value assumption.
    assert v.shares_cr == facts.value("pnl:Net Profit", "FY26") / facts.value("pnl:EPS in Rs", "FY26")
    assert v.market_cap_cr == 2044.40 * v.shares_cr
    # The grid is centred on the company's realised growth, so the base case IS its own record.
    assert v.scenarios and {s.name for s in v.scenarios} == {"disaster", "bear", "base", "bull"}
    base = next(s for s in v.scenarios if s.name == "base")
    assert base.growth == v.realised_growth
    # Every assumption that produced the number travels with it.
    assert v.assumptions["discount_rate"] == POLICY["discount_rate"]


def test_every_missing_input_is_named_rather_than_defaulted(store):
    """A valuation that quietly substitutes a zero for missing net debt is worse than none — it looks
    like a valuation."""
    _, _, v = _priced(store, price=None)
    assert not v.valued
    assert any("market:Close" in m for m in v.missing)


def test_a_cash_burning_company_is_refused_rather_than_valued(store):
    """Discounting negative cash produces a confident negative number about the wrong question: for a
    company burning cash the question is funding, not price."""
    series = _valuable_series(**{"cashflow:Free Cash Flow": [40, 50, 60, 70, 85, -95]})
    _, _, v = _priced(store, series)
    assert not v.valued
    assert any("cannot be valued by discounting" in m for m in v.missing)


def test_a_price_the_dcf_cannot_bracket_is_reported_as_a_finding_not_an_error(store):
    """A price implying growth beyond the band is a statement about the PRICE — the one thing a
    reverse DCF exists to surface — so it must reach the reader, not raise."""
    _, _, v = _priced(store, price=2_000_000.0)
    assert v.valued and v.implied_growth is None
    assert "cannot be justified by discounting" in v.implied_growth_note


def test_the_valuation_s_numbers_become_derivations_the_law_1_validator_can_see(store):
    _, _, v = _priced(store)
    derivations = valuation_derivations(v)
    assert {"market_cap", "enterprise_value", "base_case_value_per_share"} <= set(derivations)
    # "base case" is bound to the base scenario, never reassignable to the bull column.
    base = next(s for s in v.scenarios if s.name == "base")
    assert derivations["base_case_value_per_share"].value == base.value_per_share
    # Each derivation carries the facts it rests on, so it cites and grades like any other number.
    assert derivations["market_cap"].inputs and derivations["market_cap"].citation.grade


def test_scenario_lines_are_checked_against_the_priced_grid_item_by_item():
    """Allowlisting a scenario multiple would let an agent write 'bull: 4.2x' beside a computed 0.22x
    and pass every gate — the easiest way to launder an invented number through this system."""
    from firm.core.pipeline.deep_dive import _scenario_discipline
    from firm.schemas.agents import ScenarioLine, ValuationModelerOutput

    priced = {"base": 0.15, "bull": 0.22}
    ok = ValuationModelerOutput(
        agent="valuation_modeler", agent_version="1.0.0", ticker="ACME", as_of=date(2026, 8, 30),
        narrative="n", disconfirming_search="d", open_questions=["q"],
        scenarios=[ScenarioLine(name="base", probability=0.6, return_multiple=0.15)])
    assert _scenario_discipline(ok, priced) == []

    fabricated = ok.model_copy(update={"scenarios": [
        ScenarioLine(name="bull", probability=0.4, return_multiple=4.2)]})
    assert "the DCF prices it at 0.2200" in _scenario_discipline(fabricated, priced)[0]

    invented = ok.model_copy(update={"scenarios": [
        ScenarioLine(name="moon", probability=1.0, return_multiple=9.0)]})
    assert "never priced a scenario by that name" in _scenario_discipline(invented, priced)[0]


def test_a_store_with_no_readable_period_says_so_once(store):
    """Not four gaps whose text reads 'share count for ' — a message with a blank where its subject
    belongs tells a reader nothing, and this one would have shipped in a published report."""
    facts = D.load_company_facts(store, "NOBODY", AS_OF)
    v = value_company(facts, D.derive_metrics(facts), price=100.0,
                      price_on=date(2026, 8, 28), policy=POLICY)
    assert not v.valued and len(v.missing) == 1
    assert "no financial year" in v.missing[0]
