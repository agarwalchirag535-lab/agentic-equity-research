"""Tests for the exogenous-series divergence scanner (FORENSIC_METHODOLOGY §3 P1). Full coverage."""

import pytest

from firm.core.compute.divergence import (
    cochange_divergence,
    divergence_flag,
    pct_change,
    realized_correlation,
)


def test_pct_change():
    assert pct_change([100, 309]) == pytest.approx(2.09)   # Carvana GPU-like +209%
    assert pct_change([100, 80]) == pytest.approx(-0.20)   # Manheim-like -20%
    with pytest.raises(ValueError):
        pct_change([100])          # need two points
    with pytest.raises(ValueError):
        pct_change([0, 5])         # first observation zero


def test_realized_correlation():
    assert realized_correlation([1, 2, 3], [1, 2, 3]) == pytest.approx(1.0)
    assert realized_correlation([1, 2, 3], [3, 2, 1]) == pytest.approx(-1.0)
    with pytest.raises(ValueError):
        realized_correlation([1, 2, 3], [1, 2])   # length mismatch
    with pytest.raises(ValueError):
        realized_correlation([1], [1])            # < 2 observations
    with pytest.raises(ValueError):
        realized_correlation([2, 2, 2], [1, 2, 3])  # zero-variance metric


def test_divergence_flag():
    # expected to move together, but strongly move apart => flag
    corr, flag = divergence_flag([1, 2, 3], [3, 2, 1], expected_sign=1, min_abs_correlation=0.5)
    assert corr == pytest.approx(-1.0) and flag is True
    # expected to move inversely, but strongly move together => flag
    corr, flag = divergence_flag([1, 2, 3], [1, 2, 3], expected_sign=-1, min_abs_correlation=0.5)
    assert corr == pytest.approx(1.0) and flag is True
    # aligned with expectation => no flag
    _, flag = divergence_flag([1, 2, 3], [1, 2, 3], expected_sign=1, min_abs_correlation=0.5)
    assert flag is False
    with pytest.raises(ValueError):
        divergence_flag([1, 2, 3], [1, 2, 3], expected_sign=0, min_abs_correlation=0.5)


def test_cochange_divergence():
    # Carvana: GPU +209% while used-car index -20.3%, expected to move together => divergence
    assert cochange_divergence(2.09, -0.203, expected_sign=1) is True
    # both up, expected together => aligned, no divergence
    assert cochange_divergence(0.5, 0.5, expected_sign=1) is False
    # metric up while driver down, but they SHOULD move inversely => aligned, no divergence
    assert cochange_divergence(0.5, -0.5, expected_sign=-1) is False
    # a zero move on either side is inconclusive
    assert cochange_divergence(0.0, 0.5, expected_sign=1) is False
    assert cochange_divergence(0.5, 0.0, expected_sign=1) is False
    with pytest.raises(ValueError):
        cochange_divergence(1.0, 1.0, expected_sign=2)
