"""Tests for the §6 multibagger math. Aims for full coverage of firm.core.compute.multibagger."""

import math

import pytest

from firm.core.compute.multibagger import (
    GateVerdict,
    eps_growth,
    feasibility_gate,
    reinvestment_rate_from_financials,
    required_earnings_cagr,
    required_reinvestment_rate,
    serial_diluter_flag,
    sustainable_growth,
)

GATE = dict(self_fund_ceiling=1.0, high_quality_ceiling=0.6)


# ---- required_earnings_cagr: reproduce the §6.2 table -------------------------------------------
@pytest.mark.parametrize(
    "rerating,expected",
    [(1.0, 0.389), (1.5, 0.311), (2.0, 0.258), (3.0, 0.188)],
)
def test_required_cagr_matches_spec_table(rerating, expected):
    g = required_earnings_cagr(total_return_multiple=10, years=7, rerating_multiple=rerating)
    assert g == pytest.approx(expected, abs=0.001)


def test_required_cagr_dilution_raises_the_bar():
    with_dilution = required_earnings_cagr(10, 7, 1.0, dilution_factor=1.2)
    without = required_earnings_cagr(10, 7, 1.0, dilution_factor=1.0)
    assert with_dilution > without


def test_required_cagr_bad_inputs():
    with pytest.raises(ValueError):
        required_earnings_cagr(10, 0)
    with pytest.raises(ValueError):
        required_earnings_cagr(-1, 7)
    with pytest.raises(ValueError):
        required_earnings_cagr(10, 7, rerating_multiple=0)
    with pytest.raises(ValueError):
        required_earnings_cagr(10, 7, dilution_factor=0)


# ---- reinvestment / sustainable growth ---------------------------------------------------------
def test_reinvestment_rate_from_financials():
    assert reinvestment_rate_from_financials(100, 40, 20, 80) == pytest.approx(1.0)


def test_reinvestment_rate_zero_nopat_raises():
    with pytest.raises(ValueError):
        reinvestment_rate_from_financials(100, 40, 20, 0)


def test_sustainable_growth():
    assert sustainable_growth(0.40, 0.65) == pytest.approx(0.26)


def test_required_reinvestment_rate_paths():
    assert required_reinvestment_rate(0.0, 0.20) == 0.0          # no growth needed
    assert required_reinvestment_rate(-0.05, 0.20) == 0.0        # negative growth needed
    assert math.isinf(required_reinvestment_rate(0.10, -0.05))   # value-destroyer can't self-fund
    assert required_reinvestment_rate(0.26, 0.40) == pytest.approx(0.65)


# ---- feasibility gate (§6.3) -------------------------------------------------------------------
def test_gate_hard_fail_rejects_under_returning_company():
    r = feasibility_gate(
        g_required=0.30, roic=0.15, debt_capacity_available=False,
        thesis_allows_dilution=False, **GATE,
    )
    assert r.verdict is GateVerdict.HARD_FAIL
    assert r.self_funds is False
    assert r.required_reinvestment == pytest.approx(2.0)
    assert "Rejected" in r.rationale


def test_gate_needs_external_funding_when_debt_or_dilution_available():
    r = feasibility_gate(
        g_required=0.30, roic=0.15, debt_capacity_available=True,
        thesis_allows_dilution=False, **GATE,
    )
    assert r.verdict is GateVerdict.NEEDS_EXTERNAL_FUNDING


def test_gate_self_funded_band():
    r = feasibility_gate(
        g_required=0.26, roic=0.40, debt_capacity_available=True,
        thesis_allows_dilution=True, **GATE,
    )
    assert r.verdict is GateVerdict.SELF_FUNDED
    assert r.self_funds is True


def test_gate_self_funded_surplus():
    r = feasibility_gate(
        g_required=0.10, roic=0.40, debt_capacity_available=True,
        thesis_allows_dilution=True, **GATE,
    )
    assert r.verdict is GateVerdict.SELF_FUNDED_SURPLUS
    assert r.surplus_or_gap == pytest.approx(0.75)


def test_gate_infinite_reinvestment_when_roic_nonpositive():
    r = feasibility_gate(
        g_required=0.10, roic=-0.05, debt_capacity_available=False,
        thesis_allows_dilution=False, **GATE,
    )
    assert r.verdict is GateVerdict.HARD_FAIL
    assert math.isinf(r.required_reinvestment)
    assert math.isinf(r.surplus_or_gap)


# ---- dilution drag (§6.5) ----------------------------------------------------------------------
def test_eps_growth():
    assert eps_growth(0.20, 0.05) == pytest.approx((1.20 / 1.05) - 1.0)


def test_eps_growth_impossible_share_shrink_raises():
    with pytest.raises(ValueError):
        eps_growth(0.20, -1.0)


def test_serial_diluter_flag():
    assert serial_diluter_flag(0.08, roic_stepped_up=False, share_cagr_threshold=0.06) is True
    assert serial_diluter_flag(0.08, roic_stepped_up=True, share_cagr_threshold=0.06) is False
    assert serial_diluter_flag(0.04, roic_stepped_up=False, share_cagr_threshold=0.06) is False
