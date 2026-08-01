"""Tests for ratios, DuPont, and ROIC modules — full coverage of all three."""

import pytest

from firm.core.compute import dupont, ratios, roic


# ---- ratios ------------------------------------------------------------------------------------
def test_margins_and_returns():
    assert ratios.gross_margin(1000, 600) == pytest.approx(0.40)
    assert ratios.ebitda_margin(180, 1000) == pytest.approx(0.18)
    assert ratios.net_margin(120, 1000) == pytest.approx(0.12)
    assert ratios.roa(120, 1200) == pytest.approx(0.10)
    assert ratios.roe(120, 600) == pytest.approx(0.20)


def test_cagr_compounds_and_refuses_an_undefined_rate():
    assert ratios.cagr(600, 1000, 4) == pytest.approx(0.1362, abs=1e-4)
    assert ratios.cagr(100, 100, 3) == pytest.approx(0.0)
    # A company that went from a loss to a profit has no compound RATE, and the fractional power of a
    # negative ratio is not a real number. Refusing beats returning something plottable and meaningless.
    for bad in ((600, 1000, 0), (-10, 1000, 4), (600, 0, 4)):
        with pytest.raises(ValueError):
            ratios.cagr(*bad)


def test_liquidity_and_leverage():
    assert ratios.current_ratio(400, 200) == pytest.approx(2.0)
    assert ratios.quick_ratio(400, 100, 200) == pytest.approx(1.5)
    assert ratios.debt_to_equity(300, 600) == pytest.approx(0.5)
    assert ratios.net_debt_to_ebitda(360, 180) == pytest.approx(2.0)
    assert ratios.interest_coverage(150, 30) == pytest.approx(5.0)


def test_efficiency_and_cash():
    assert ratios.asset_turnover(1000, 1250) == pytest.approx(0.8)
    assert ratios.receivable_days(150, 1000, days=365) == pytest.approx(54.75)
    assert ratios.inventory_days(100, 600, days=365) == pytest.approx(60.8333, abs=1e-3)
    assert ratios.payable_days(120, 600, days=365) == pytest.approx(73.0)
    assert ratios.cash_conversion_cycle(54.75, 60.83, 73.0) == pytest.approx(42.58, abs=1e-2)
    assert ratios.free_cash_flow(200, 50) == pytest.approx(150)
    assert ratios.fcf_to_pat(150, 120) == pytest.approx(1.25)
    assert ratios.cfo_to_ebitda(160, 180) == pytest.approx(0.8889, abs=1e-3)


@pytest.mark.parametrize("call", [
    lambda: ratios.gross_margin(0, 60),
    lambda: ratios.roe(120, 0),
    lambda: ratios.debt_to_equity(300, 0),
    lambda: ratios.fcf_to_pat(150, 0),
])
def test_ratios_zero_denominator_raises(call):
    with pytest.raises(ValueError):
        call()


# ---- DuPont ------------------------------------------------------------------------------------
def test_three_step_dupont():
    r = dupont.three_step_dupont(0.10, 0.8, 2.0)
    assert r.roe == pytest.approx(0.16)


def test_five_step_dupont():
    r = dupont.five_step_dupont(0.75, 0.9, 0.18, 0.8, 2.0)
    assert r.roe == pytest.approx(0.75 * 0.9 * 0.18 * 0.8 * 2.0)


def test_five_step_from_financials_reconstructs_roe():
    r = dupont.five_step_from_financials(
        pat=120, pretax_income=160, ebit=180, sales=1000, avg_total_assets=1250, avg_equity=600
    )
    assert r.roe == pytest.approx(120 / 600)  # ROE == PAT/avg_equity


def test_five_step_from_financials_zero_raises():
    with pytest.raises(ValueError):
        dupont.five_step_from_financials(120, 0, 180, 1000, 1250, 600)


# ---- ROIC --------------------------------------------------------------------------------------
def test_roic_basics():
    assert roic.nopat(200, 0.25) == pytest.approx(150)
    assert roic.invested_capital(300, 600, 100) == pytest.approx(800)
    assert roic.roic(150, 800) == pytest.approx(0.1875)
    assert roic.roic_wacc_spread(0.1875, 0.12) == pytest.approx(0.0675)
    assert roic.incremental_roic(60, 200) == pytest.approx(0.30)


def test_roic_zero_denominators_raise():
    with pytest.raises(ValueError):
        roic.roic(150, 0)
    with pytest.raises(ValueError):
        roic.incremental_roic(60, 0)


def test_rolling_incremental_roic():
    nopat_series = [100, 110, 125, 145, 170]
    invested_series = [500, 540, 590, 660, 750]
    out = roic.rolling_incremental_roic(nopat_series, invested_series, window=3)
    # gaps: idx3 vs idx0, idx4 vs idx1
    assert out == [pytest.approx((145 - 100) / (660 - 500)), pytest.approx((170 - 110) / (750 - 540))]


def test_rolling_incremental_roic_guards():
    with pytest.raises(ValueError):
        roic.rolling_incremental_roic([1, 2], [1], window=1)          # length mismatch
    with pytest.raises(ValueError):
        roic.rolling_incremental_roic([1, 2, 3], [1, 2, 3], window=3)  # not longer than window
