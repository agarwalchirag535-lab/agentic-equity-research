"""Multibagger decomposition and the §6 feasibility gate — the intellectual centre of the system.

Law 1: pure Python. No LLM, no network, no I/O. Every policy threshold is passed in explicitly
(sourced from ``config/thresholds.yaml``); no magic policy number is baked into this module.

Decomposition (§6.1):
    Total Return = (1 + g_earnings)**n  ×  (M_exit / M_entry)  ×  (1 / dilution_factor)
where ``dilution_factor = shares_exit / shares_entry``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum


class GateVerdict(str, Enum):
    """Outcome of the §6.3 self-funding feasibility gate."""

    SELF_FUNDED_SURPLUS = "SELF_FUNDED_SURPLUS"       # g/ROIC < high_quality_ceiling
    SELF_FUNDED = "SELF_FUNDED"                       # high_quality_ceiling <= g/ROIC <= self_fund_ceiling
    NEEDS_EXTERNAL_FUNDING = "NEEDS_EXTERNAL_FUNDING"  # g/ROIC > self_fund_ceiling but still fundable
    HARD_FAIL = "HARD_FAIL"                           # cannot self-fund, no debt room, thesis bars dilution


def required_earnings_cagr(
    total_return_multiple: float,
    years: int,
    rerating_multiple: float = 1.0,
    dilution_factor: float = 1.0,
) -> float:
    """Earnings CAGR required for ``total_return_multiple`` over ``years`` (§6.2).

    Solving the decomposition for g:
        (1 + g)**n = total_return × dilution_factor / rerating
        g = (that)**(1/n) - 1

    Reproduces the §6.2 table, e.g. 10x / 7y / no re-rating -> 0.389.
    """
    if years <= 0:
        raise ValueError("years must be positive")
    if total_return_multiple <= 0 or rerating_multiple <= 0 or dilution_factor <= 0:
        raise ValueError("multiples must be positive")
    growth_component = total_return_multiple * dilution_factor / rerating_multiple
    return growth_component ** (1.0 / years) - 1.0


def reinvestment_rate_from_financials(
    capex: float, depreciation: float, delta_working_capital: float, nopat: float
) -> float:
    """Reinvestment Rate = (Capex - D&A + ΔWC) / NOPAT (§6.3)."""
    if nopat == 0:
        raise ValueError("nopat must be non-zero")
    return (capex - depreciation + delta_working_capital) / nopat


def sustainable_growth(roic: float, reinvestment_rate: float) -> float:
    """g_sustainable = ROIC × Reinvestment Rate (§6.3)."""
    return roic * reinvestment_rate


def required_reinvestment_rate(g_required: float, roic: float) -> float:
    """Required Reinvestment Rate = g / ROIC (§6.3).

    Returns ``inf`` when growth is required but ROIC <= 0 (a value-destroyer cannot self-fund any
    positive growth). No required growth -> 0 regardless of ROIC.
    """
    if g_required <= 0:
        return 0.0
    if roic <= 0:
        return math.inf
    return g_required / roic


@dataclass(frozen=True)
class FeasibilityResult:
    g_required: float
    roic: float
    required_reinvestment: float
    verdict: GateVerdict
    self_funds: bool
    surplus_or_gap: float  # 1 - required_reinvestment; positive = surplus NOPAT, negative = funding gap
    rationale: str


def feasibility_gate(
    *,
    g_required: float,
    roic: float,
    self_fund_ceiling: float,
    high_quality_ceiling: float,
    debt_capacity_available: bool,
    thesis_allows_dilution: bool,
) -> FeasibilityResult:
    """The §6.3 HARD-FAIL gate.

    - required_reinvestment > self_fund_ceiling -> cannot self-fund; must raise debt or equity.
      If no debt room AND the thesis bars dilution -> HARD_FAIL (thesis rejected).
      Otherwise -> NEEDS_EXTERNAL_FUNDING (dilution/leverage must be modelled and the run re-done).
    - required_reinvestment < high_quality_ceiling -> SELF_FUNDED_SURPLUS (then ask what happens to the
      surplus cash — capital-allocation risk).
    - otherwise -> SELF_FUNDED.
    """
    rr = required_reinvestment_rate(g_required, roic)
    surplus = 1.0 - rr if math.isfinite(rr) else math.inf * -1  # -inf gap when reinvestment is infinite

    if rr > self_fund_ceiling:
        if not debt_capacity_available and not thesis_allows_dilution:
            verdict = GateVerdict.HARD_FAIL
            rationale = (
                f"required reinvestment {rr:.2f} > {self_fund_ceiling:.2f} of NOPAT; debt capacity "
                f"exhausted and thesis assumes no dilution — cannot fund {g_required:.1%} growth at "
                f"ROIC {roic:.1%}. Rejected."
            )
        else:
            verdict = GateVerdict.NEEDS_EXTERNAL_FUNDING
            rationale = (
                f"required reinvestment {rr:.2f} > {self_fund_ceiling:.2f} of NOPAT; must raise "
                f"debt/equity to fund {g_required:.1%} growth at ROIC {roic:.1%}. Model the funding "
                f"and dilution explicitly, then re-run the decomposition."
            )
        return FeasibilityResult(g_required, roic, rr, verdict, False, surplus, rationale)

    if rr < high_quality_ceiling:
        verdict = GateVerdict.SELF_FUNDED_SURPLUS
        rationale = (
            f"required reinvestment {rr:.2f} < {high_quality_ceiling:.2f} of NOPAT — self-funds with "
            f"{surplus:.0%} surplus. High-quality compounding; scrutinise what happens to surplus cash."
        )
        return FeasibilityResult(g_required, roic, rr, verdict, True, surplus, rationale)

    verdict = GateVerdict.SELF_FUNDED
    rationale = (
        f"required reinvestment {rr:.2f} within [{high_quality_ceiling:.2f}, {self_fund_ceiling:.2f}] "
        f"of NOPAT — self-funds {g_required:.1%} growth at ROIC {roic:.1%}."
    )
    return FeasibilityResult(g_required, roic, rr, verdict, True, surplus, rationale)


def eps_growth(earnings_growth: float, share_growth: float) -> float:
    """EPS growth = (1 + g_earnings) / (1 + g_shares) - 1 (§6.5 dilution drag)."""
    if share_growth <= -1.0:
        raise ValueError("share_growth <= -100% is impossible")
    return (1.0 + earnings_growth) / (1.0 + share_growth) - 1.0


def serial_diluter_flag(
    share_count_cagr: float, roic_stepped_up: bool, share_cagr_threshold: float
) -> bool:
    """Flag serial dilution (§6.5): share count CAGR above threshold WITHOUT a matching ROIC step-up."""
    return share_count_cagr > share_cagr_threshold and not roic_stepped_up
