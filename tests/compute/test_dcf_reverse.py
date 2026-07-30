"""Tests for the DCF and reverse-DCF modules — full coverage."""

import pytest

from firm.core.compute import dcf
from firm.core.compute.reverse_dcf import implied_growth_rate


# ---- DCF ---------------------------------------------------------------------------------------
def test_present_value():
    # two cash flows of 100 at 10%
    assert dcf.present_value([100, 100], 0.10) == pytest.approx(100 / 1.1 + 100 / 1.1**2)


def test_present_value_bad_rate_raises():
    with pytest.raises(ValueError):
        dcf.present_value([100], -1.0)


def test_terminal_value_gordon():
    assert dcf.terminal_value_gordon(104, 0.12, 0.04) == pytest.approx(104 / 0.08)


def test_terminal_value_requires_r_above_g():
    with pytest.raises(ValueError):
        dcf.terminal_value_gordon(100, 0.04, 0.04)


def test_dcf_enterprise_value():
    ev = dcf.dcf_enterprise_value([100, 110, 121], discount_rate=0.12, terminal_growth=0.04)
    assert ev > 0


def test_dcf_enterprise_value_empty_raises():
    with pytest.raises(ValueError):
        dcf.dcf_enterprise_value([], 0.12, 0.04)


def test_equity_value_and_per_share():
    assert dcf.equity_value(1000, 300) == pytest.approx(700)
    assert dcf.value_per_share(700, 100) == pytest.approx(7.0)


def test_value_per_share_requires_positive_shares():
    with pytest.raises(ValueError):
        dcf.value_per_share(700, 0)


# ---- reverse DCF -------------------------------------------------------------------------------
def test_implied_growth_recovers_known_growth():
    base_fcf, r, tg, years, g_true = 100.0, 0.12, 0.04, 5, 0.15
    forecast = [base_fcf * (1 + g_true) ** (t + 1) for t in range(years)]
    ev = dcf.dcf_enterprise_value(forecast, r, tg)
    g_implied = implied_growth_rate(ev, base_fcf, r, tg, years)
    assert g_implied == pytest.approx(g_true, abs=1e-3)


def test_implied_growth_guards():
    with pytest.raises(ValueError):
        implied_growth_rate(1000, base_fcf=0, discount_rate=0.12, terminal_growth=0.04, years=5)
    with pytest.raises(ValueError):
        implied_growth_rate(1000, base_fcf=100, discount_rate=0.12, terminal_growth=0.04, years=0)


def test_implied_growth_unbracketed_raises():
    with pytest.raises(ValueError):
        implied_growth_rate(1e12, base_fcf=100, discount_rate=0.12, terminal_growth=0.04, years=5)
