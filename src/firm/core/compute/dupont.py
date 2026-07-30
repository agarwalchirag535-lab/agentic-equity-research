"""DuPont ROE decomposition — 3-step and extended 5-step (Phase 1)."""

from __future__ import annotations

from dataclasses import dataclass


def _nonzero(value: float, name: str) -> float:
    if value == 0:
        raise ValueError(f"{name} must be non-zero")
    return value


@dataclass(frozen=True)
class ThreeStep:
    net_margin: float
    asset_turnover: float
    equity_multiplier: float
    roe: float


def three_step_dupont(net_margin: float, asset_turnover: float, equity_multiplier: float) -> ThreeStep:
    """ROE = net margin × asset turnover × equity multiplier."""
    roe = net_margin * asset_turnover * equity_multiplier
    return ThreeStep(net_margin, asset_turnover, equity_multiplier, roe)


@dataclass(frozen=True)
class FiveStep:
    tax_burden: float
    interest_burden: float
    operating_margin: float
    asset_turnover: float
    equity_multiplier: float
    roe: float


def five_step_dupont(
    tax_burden: float,
    interest_burden: float,
    operating_margin: float,
    asset_turnover: float,
    equity_multiplier: float,
) -> FiveStep:
    """ROE = tax burden × interest burden × operating margin × asset turnover × equity multiplier."""
    roe = tax_burden * interest_burden * operating_margin * asset_turnover * equity_multiplier
    return FiveStep(tax_burden, interest_burden, operating_margin, asset_turnover, equity_multiplier, roe)


def five_step_from_financials(
    pat: float,
    pretax_income: float,
    ebit: float,
    sales: float,
    avg_total_assets: float,
    avg_equity: float,
) -> FiveStep:
    """Build the 5-step decomposition from raw statement lines."""
    tax_burden = pat / _nonzero(pretax_income, "pretax_income")
    interest_burden = pretax_income / _nonzero(ebit, "ebit")
    operating_margin = ebit / _nonzero(sales, "sales")
    turnover = sales / _nonzero(avg_total_assets, "avg_total_assets")
    equity_multiplier = avg_total_assets / _nonzero(avg_equity, "avg_equity")
    return five_step_dupont(tax_burden, interest_burden, operating_margin, turnover, equity_multiplier)
