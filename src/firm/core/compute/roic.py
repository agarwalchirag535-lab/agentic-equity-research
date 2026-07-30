"""ROIC, incremental ROIC, and ROIC-vs-WACC (Phase 1).

SPEC §5 stresses INCREMENTAL ROIC = ΔNOPAT / ΔInvested Capital over rolling windows — the marginal
return on the next rupee of capital, which matters more than the average.
"""

from __future__ import annotations

from typing import Sequence


def _nonzero(value: float, name: str) -> float:
    if value == 0:
        raise ValueError(f"{name} must be non-zero")
    return value


def nopat(ebit: float, tax_rate: float) -> float:
    """Net operating profit after tax = EBIT × (1 − tax rate)."""
    return ebit * (1.0 - tax_rate)


def invested_capital(total_debt: float, equity: float, cash: float) -> float:
    """Invested capital = total debt + equity − surplus cash."""
    return total_debt + equity - cash


def roic(nopat_value: float, invested_capital_value: float) -> float:
    return nopat_value / _nonzero(invested_capital_value, "invested_capital")


def roic_wacc_spread(roic_value: float, wacc: float) -> float:
    """Positive spread = value creation; negative = value destruction."""
    return roic_value - wacc


def incremental_roic(delta_nopat: float, delta_invested_capital: float) -> float:
    return delta_nopat / _nonzero(delta_invested_capital, "delta_invested_capital")


def rolling_incremental_roic(
    nopat_series: Sequence[float], invested_series: Sequence[float], window: int = 3
) -> list[float]:
    """Incremental ROIC over rolling ``window``-year gaps."""
    if len(nopat_series) != len(invested_series):
        raise ValueError("series length mismatch")
    if len(nopat_series) <= window:
        raise ValueError("series must be longer than the window")
    out: list[float] = []
    for i in range(window, len(nopat_series)):
        d_nopat = nopat_series[i] - nopat_series[i - window]
        d_ic = invested_series[i] - invested_series[i - window]
        out.append(incremental_roic(d_nopat, d_ic))
    return out
