"""Point-in-time reference rates (ADR-0078).

`thresholds.forensic.risk_free_rate` was ONE constant, 6.5%, applied to every vintage. The cash-reality
check asks whether the yield a company earned on its cash is plausible, and that question has a
different answer in every rate environment: Indian short rates ranged roughly 3.5%-7.5% across the
golden set's 2015-2021 window. A flat floor makes a FY21 company earning an ordinary 3.5% look like it
is hiding something, and waves through a FY15 company earning 4%.

GOLDEN_SET.md §1 lists this as a prerequisite for a reason it states precisely: "a bug uniform across
the calibration set is indistinguishable from a property of the world". Calibrating thresholds against
a mis-dated rate would teach the firm a compensating error and bake it in permanently.

The rule these tests defend hardest: **the fallback is never silent.** A check resting on the wrong
vintage while reading like a normal verdict is the defect, and a config file that hides it is the same
defect wearing a nicer hat.
"""

from __future__ import annotations

from firm.core.compute.rates import risk_free_for
from firm.core.config import reference_rates

DATED = {
    "risk_free_rate": {
        "fallback": 0.065,
        "fallback_basis": "undated reference",
        "by_fiscal_year": {
            "FY21": {"rate": 0.035, "source": "RBI Handbook Table 71", "as_of": "2021-03-31"},
            "FY15": {"rate": 0.075, "source": "RBI Handbook Table 71", "as_of": "2015-03-31"},
        },
    }
}


def test_a_dated_rate_is_used_for_the_year_it_covers():
    rate = risk_free_for("FY21", DATED)
    assert rate.value == 0.035 and rate.dated is True
    assert "FY21" in rate.basis and "3.50%" in rate.basis


def test_the_source_travels_with_the_rate():
    """A rate without a source is a number someone typed, which is the failure mode this file exists
    to prevent — it would miscalibrate every verdict downstream and nothing could detect it."""
    assert "RBI Handbook Table 71" in risk_free_for("FY15", DATED).basis


def test_rates_actually_differ_by_vintage_which_is_the_whole_point():
    assert risk_free_for("FY15", DATED).value > risk_free_for("FY21", DATED).value


def test_an_uncovered_year_falls_back_and_says_so():
    rate = risk_free_for("FY19", DATED)
    assert rate.value == 0.065 and rate.dated is False
    assert "undated fallback" in rate.basis and "FY19" in rate.basis


def test_an_unknown_period_is_never_guessed_into_a_year():
    """Guessing which year an unlabelled figure belongs to is the mis-dating this module prevents."""
    for period in (None, ""):
        rate = risk_free_for(period, DATED)
        assert rate.dated is False


def test_a_source_less_entry_is_used_but_flagged_as_unsourced():
    rates = {"risk_free_rate": {"fallback": 0.065, "by_fiscal_year": {"FY20": {"rate": 0.04}}}}
    assert "source not stated" in risk_free_for("FY20", rates).basis


def test_the_shipped_config_is_readable_and_declares_its_own_gap():
    """The repo ships the mechanism with no dated rows — deliberately, because typing rates from
    memory would fabricate a primary input. The config must say that rather than look populated."""
    shipped = reference_rates()
    rate = risk_free_for("FY21", shipped)
    assert rate.dated is False
    assert rate.value == 0.065
    assert "NOT vintage-correct" in shipped["risk_free_rate"]["fallback_basis"]


def test_the_cash_yield_check_reports_which_rate_its_floor_came_from():
    """A reader cannot judge a cash-yield flag without knowing which year's rate it was measured
    against, so the basis is part of the check's detail rather than a footnote in config."""

    rate = risk_free_for("FY21", reference_rates())
    assert rate.basis                       # non-empty, and it is what checks.py appends to `detail`
    assert "fallback" in rate.basis


def test_the_flat_rate_produces_errors_in_BOTH_directions():
    """The concrete case for this change, and the reason it blocks the golden set.

    A single 6.5% reference does not make the cash-yield check merely approximate. It makes it wrong in
    a direction that depends on the year — flagging honest companies in a low-rate year and waving
    through suspicious ones in a high-rate year. Calibrating thresholds on top of that would fit a
    parameter to the firm's own dating error and carry it forever (GOLDEN_SET.md §1).
    """
    from firm.core.compute.quality import cash_interest_consistency

    flat = {"risk_free_rate": {"fallback": 0.065}}
    ratio = 0.40

    # FY21, market paid 3.5%: a company earning 2.0% is unremarkable and the flat floor flags it.
    _, flat_flag = cash_interest_consistency(2.0, 100.0, risk_free_for("FY21", flat).value, ratio)
    _, dated_flag = cash_interest_consistency(2.0, 100.0, risk_free_for("FY21", DATED).value, ratio)
    assert flat_flag is True and dated_flag is False, "flat rate false-positives in a low-rate year"

    # FY15, market paid 7.5%: a company earning 2.8% is well under market and the flat floor clears it.
    _, flat_flag = cash_interest_consistency(2.8, 100.0, risk_free_for("FY15", flat).value, ratio)
    _, dated_flag = cash_interest_consistency(2.8, 100.0, risk_free_for("FY15", DATED).value, ratio)
    assert flat_flag is False and dated_flag is True, "flat rate false-negatives in a high-rate year"
