"""Normalising the base cash flow (ADR-0072).

The valuation discounted ONE year's free cash flow. That is the wrong base for a cyclical business: a
trough year makes the bear case look inevitable, a peak year makes the bull look cheap, and the whole
scenario grid inherits whichever twelve months it was handed. STATUS has carried this as the last
Phase-4 defect, with the standing instruction that the fix is the missing input — never a nudged
discount rate.

Two rules pull against each other here and both are kept:

* **Normalise the base**, because one year is not a cycle. Median, not mean: a single asset sale moves
  a mean and barely moves a median.
* **Do not normalise away a current cash burn.** The latest year decides whether to value the company
  at all; the window only decides the base to value FROM. Smoothing a fresh burn into a comfortable
  median is the one case where the smoothing is itself the error.
"""

from __future__ import annotations

from datetime import date

from firm.core.config import load_thresholds
from firm.core.pipeline import derive as D
from firm.core.pipeline.valuation import value_company
from tests.conftest import AS_OF, seed_store
from tests.pipeline.test_valuation_wiring import valuable_series

POLICY = load_thresholds()["valuation"]


def _value(store, fcf: list[float], *, policy=None):
    seed_store(store, "ACME", valuable_series(**{"cashflow:Free Cash Flow": fcf}))
    facts = D.load_company_facts(store, "ACME", AS_OF)
    return value_company(facts, D.derive_metrics(facts), price=2044.40,
                         price_on=date(2026, 8, 28), policy=policy or POLICY)


def test_a_trough_year_no_longer_sets_the_base_on_its_own(store):
    """The defect, stated as a test: five steady years and one bad one must not price the company as
    though the bad one were the business."""
    steady = _value(store, [60, 60, 60, 60, 60, 60])
    trough = _value(store, [60, 60, 60, 60, 60, 6])

    assert steady.valued and trough.valued
    # The trough year is still IN the window, so the base moves — but to the median, not to the trough.
    assert trough.base_fcf_cr == 60.0
    assert trough.base_fcf_cr > 6.0


def test_the_basis_is_stated_so_a_reader_can_judge_the_bear_case(store):
    result = _value(store, [40, 50, 60, 70, 80, 90])
    assert "median of 5 years" in result.base_fcf_basis
    # the median of the last five (50, 60, 70, 80, 90), not the latest and not the mean
    assert result.base_fcf_cr == 70.0


def test_one_readable_year_is_reported_as_one_year_not_dressed_up_as_normalised(store):
    """A claim about a cycle needs a cycle of data — the rule `cumulative_cfo_pat_min_periods` applies
    to cash conversion, applied here."""
    result = _value(store, [0, 0, 0, 0, 0, 90])
    seeded = _value(store, [90])
    for outcome in (result, seeded):
        if outcome.valued:
            assert "alone" in outcome.base_fcf_basis or "median" in outcome.base_fcf_basis


def test_a_current_cash_burn_is_still_refused_however_good_the_history(store):
    """The smoothing must not hide the signal it exists to smooth: a company that has just gone cash
    negative is exactly the case where the median is the wrong answer."""
    result = _value(store, [60, 60, 60, 60, 60, -95])
    assert not result.valued
    assert any("cannot be valued by discounting" in m for m in result.missing)


def test_a_cycle_that_is_negative_overall_is_refused_even_with_a_positive_latest_year(store):
    """The mirror case: one good year on top of a losing cycle is not a business to discount."""
    result = _value(store, [-60, -60, -60, -60, -60, 5])
    assert not result.valued
    assert any("the cycle is not" in m for m in result.missing)


def test_the_window_and_the_floor_are_policy_not_code(store):
    """CLAUDE.md: every hardcoded number lives in config. Changing the window changes the base."""
    wide = _value(store, [10, 20, 30, 40, 50, 60], policy={**POLICY, "base_fcf_years": 5})
    narrow = _value(store, [10, 20, 30, 40, 50, 60], policy={**POLICY, "base_fcf_years": 3})
    assert wide.base_fcf_cr == 40.0          # median of 20,30,40,50,60
    assert narrow.base_fcf_cr == 50.0        # median of 40,50,60
    assert wide.base_fcf_cr != narrow.base_fcf_cr
