"""The Phase-4 valuation grid (ADR-0062).

The probability/multiple split is the Law-1 seam of the judgment tier: an agent argues how likely a
scenario is, and never what it is worth.
"""

from __future__ import annotations

import pytest

from firm.core.compute.scenarios import (
    expectancy_from,
    scenario_growth_grid,
    value_scenario_grid,
)


# ---- the Phase-4 valuation grid (ADR-0062) -------------------------------------------------------

def test_the_grid_is_anchored_to_the_company_s_own_realised_growth():
    """A business compounding 25% and one managing 3% must not share a 'base case' — that would make
    every valuation a statement about the grid rather than about the company."""
    fast = scenario_growth_grid(0.25, bull_spread=0.06, bear_spread=0.08, disaster_growth=-0.10)
    slow = scenario_growth_grid(0.03, bull_spread=0.06, bear_spread=0.08, disaster_growth=-0.10)
    assert fast["base"] == pytest.approx(0.25) and slow["base"] == pytest.approx(0.03)
    assert fast["bull"] == pytest.approx(0.31) and fast["bear"] == pytest.approx(0.17)
    # Disaster is ABSOLUTE for both — the disaster case is the business shrinking, not "a bit worse".
    assert fast["disaster"] == slow["disaster"] == -0.10


def test_scenarios_are_priced_against_the_quoted_price_with_no_re_rating():
    """ALKYLAMINE at as_of 2026-08-30, from its own filings and the exchange's settled close."""
    priced = value_scenario_grid(
        base_fcf=110.15, growth_by_scenario={"base": 0.052, "bull": 0.112},
        discount_rate=0.13, terminal_growth=0.04, years=10,
        net_debt=-202.0, shares_outstanding=5.11, price_today=2044.40)
    by_name = {p.name: p for p in priced}
    assert by_name["base"].value_per_share == pytest.approx(310, abs=2)
    assert by_name["bull"].value_per_share == pytest.approx(450, abs=2)
    # The multiple is intrinsic value over the price actually quoted — no exit multiple anywhere.
    assert by_name["base"].return_multiple == pytest.approx(310 / 2044.40, abs=0.01)
    assert by_name["bull"].return_multiple > by_name["base"].return_multiple


def test_a_diverging_terminal_is_refused_rather_than_valued():
    """A DCF that returns infinity is not a bullish valuation, it is an arithmetic error wearing one."""
    with pytest.raises(ValueError):
        value_scenario_grid(base_fcf=100.0, growth_by_scenario={"base": 0.1}, discount_rate=0.04,
                            terminal_growth=0.04, years=10, net_debt=0.0,
                            shares_outstanding=1.0, price_today=100.0)
    with pytest.raises(ValueError):
        value_scenario_grid(base_fcf=100.0, growth_by_scenario={"base": 0.1}, discount_rate=0.13,
                            terminal_growth=0.04, years=10, net_debt=0.0,
                            shares_outstanding=1.0, price_today=0.0)


def test_expectancy_takes_probabilities_from_judgment_and_multiples_from_compute():
    """The Law-1 seam of the judgment tier: the analyst weights, the compute layer values."""
    priced = value_scenario_grid(
        base_fcf=100.0, growth_by_scenario={"bear": 0.0, "base": 0.10},
        discount_rate=0.13, terminal_growth=0.04, years=10, net_debt=0.0,
        shares_outstanding=10.0, price_today=100.0)
    got = expectancy_from(priced, {"bear": 0.4, "base": 0.6})
    by_name = {p.name: p for p in priced}
    assert got == pytest.approx(0.4 * by_name["bear"].return_multiple
                                + 0.6 * by_name["base"].return_multiple)


def test_expectancy_refuses_a_weighting_that_does_not_cover_the_outcome_space():
    priced = value_scenario_grid(
        base_fcf=100.0, growth_by_scenario={"bear": 0.0, "base": 0.10},
        discount_rate=0.13, terminal_growth=0.04, years=10, net_debt=0.0,
        shares_outstanding=10.0, price_today=100.0)
    with pytest.raises(ValueError, match="no probability supplied"):
        expectancy_from(priced, {"base": 1.0})                     # a scenario left unweighted
    with pytest.raises(ValueError, match="never priced"):
        expectancy_from(priced, {"bear": 0.4, "base": 0.5, "moon": 0.1})   # an invented scenario
    with pytest.raises(ValueError, match="sum to 1"):
        expectancy_from(priced, {"bear": 0.4, "base": 0.4})
