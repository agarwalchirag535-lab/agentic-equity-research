"""Exogenous-series divergence scanner — the P1 engine (FORENSIC_METHODOLOGY §3 P1).

The generative move behind both example reports: find a reported metric moving CONFIDENTLY AGAINST the
exogenous force that should drive it, and make that gap the hypothesis. Carvana's gross-profit-per-unit
rose ~209% while the Manheim used-vehicle index fell 20.3%; Sezzle's revenue rose 71% while its own
merchant and customer counts fell. Exogenous forces (used-car prices, sector delinquency, commodity
spreads) are not manipulable by the issuer, so a metric decoupling from them is either a genuine edge or
an artifact — and the base rate favours artifact.

Law 1: pure Python (stdlib only), no LLM, no network. Every policy threshold is passed in explicitly.
The compute layer keeps zero third-party runtime deps so it stays trivially testable offline.
"""

from __future__ import annotations

import math
from typing import Sequence


def pct_change(series: Sequence[float]) -> float:
    """Total proportional change from the first to the last observation."""
    if len(series) < 2:
        raise ValueError("need at least two observations")
    first, last = series[0], series[-1]
    if first == 0:
        raise ValueError("first observation must be non-zero")
    return last / first - 1.0


def realized_correlation(metric_series: Sequence[float], driver_series: Sequence[float]) -> float:
    """Pearson correlation between a reported metric and its exogenous driver over aligned periods."""
    m = list(metric_series)
    d = list(driver_series)
    if len(m) != len(d):
        raise ValueError("series length mismatch")
    n = len(m)
    if n < 2:
        raise ValueError("need at least two observations")
    mean_m = sum(m) / n
    mean_d = sum(d) / n
    cov = sum((mi - mean_m) * (di - mean_d) for mi, di in zip(m, d))
    var_m = sum((mi - mean_m) ** 2 for mi in m)
    var_d = sum((di - mean_d) ** 2 for di in d)
    if var_m == 0 or var_d == 0:
        raise ValueError("zero-variance series — correlation undefined")
    return cov / math.sqrt(var_m * var_d)


def divergence_flag(
    metric_series: Sequence[float],
    driver_series: Sequence[float],
    expected_sign: int,
    min_abs_correlation: float,
) -> tuple[float, bool]:
    """Flag a metric that is CONFIDENTLY correlated in the WRONG direction with its driver.

    ``expected_sign`` = +1 when the metric should move WITH the driver (positive correlation expected),
    −1 when it should move INVERSELY. A flag requires the realized correlation to (a) have the opposite
    sign to expectation and (b) be at least ``min_abs_correlation`` in magnitude — i.e. a *confident*
    wrong-way relationship, not noise. Returns (realized_correlation, is_flagged).
    """
    if expected_sign not in (1, -1):
        raise ValueError("expected_sign must be +1 or -1")
    corr = realized_correlation(metric_series, driver_series)
    diverges = (expected_sign == 1 and corr <= -min_abs_correlation) or (
        expected_sign == -1 and corr >= min_abs_correlation
    )
    return corr, diverges


def cochange_divergence(metric_delta: float, driver_delta: float, expected_sign: int) -> bool:
    """Two-point sign check: did the metric move opposite to what the driver's move implies?

    Use when only a start and end reading exist (e.g. Carvana GPU +209% vs Manheim −20.3%, expected_sign
    = +1 ⇒ GPU should have fallen ⇒ divergence). A zero move on either side is inconclusive → False.
    """
    if expected_sign not in (1, -1):
        raise ValueError("expected_sign must be +1 or -1")
    if metric_delta == 0 or driver_delta == 0:
        return False
    expected_metric_sign = 1 if (expected_sign * driver_delta) > 0 else -1
    actual_metric_sign = 1 if metric_delta > 0 else -1
    return actual_metric_sign != expected_metric_sign
