"""Common financial ratios (Phase 1). Pure Python; a zero denominator raises ValueError."""

from __future__ import annotations


def _nonzero(value: float, name: str) -> float:
    if value == 0:
        raise ValueError(f"{name} must be non-zero")
    return value


# --- margins ---
def gross_margin(sales: float, cogs: float) -> float:
    return (sales - cogs) / _nonzero(sales, "sales")


def ebitda_margin(ebitda: float, sales: float) -> float:
    return ebitda / _nonzero(sales, "sales")


def net_margin(pat: float, sales: float) -> float:
    return pat / _nonzero(sales, "sales")


# --- growth ---
def cagr(first: float, last: float, years: float) -> float:
    """Compound annual growth from ``first`` to ``last`` over ``years``.

    Undefined rather than merely awkward when a bound is non-positive: a company that went from a loss to
    a profit has no meaningful compound *rate*, and the fractional power of a negative ratio is not real.
    Callers that would rather have "no answer" than an exception guard before calling.

    ``years`` may be fractional (ADR-0049): across a fiscal-year-end change the true compounding time
    between two annual closes is not a whole number of years, and the stated dates beat the labels.
    """
    if years <= 0:
        raise ValueError("years must be positive")
    if first <= 0 or last <= 0:
        raise ValueError("cagr needs positive endpoints")
    return (last / first) ** (1.0 / years) - 1.0


# --- returns ---
def roa(pat: float, avg_total_assets: float) -> float:
    return pat / _nonzero(avg_total_assets, "avg_total_assets")


def roe(pat: float, avg_equity: float) -> float:
    return pat / _nonzero(avg_equity, "avg_equity")


# --- liquidity & leverage ---
def current_ratio(current_assets: float, current_liabilities: float) -> float:
    return current_assets / _nonzero(current_liabilities, "current_liabilities")


def quick_ratio(current_assets: float, inventory: float, current_liabilities: float) -> float:
    return (current_assets - inventory) / _nonzero(current_liabilities, "current_liabilities")


def debt_to_equity(total_debt: float, equity: float) -> float:
    return total_debt / _nonzero(equity, "equity")


def net_debt_to_ebitda(net_debt: float, ebitda: float) -> float:
    return net_debt / _nonzero(ebitda, "ebitda")


def interest_coverage(ebit: float, interest_expense: float) -> float:
    return ebit / _nonzero(interest_expense, "interest_expense")


# --- efficiency / working capital ---
def asset_turnover(sales: float, avg_total_assets: float) -> float:
    return sales / _nonzero(avg_total_assets, "avg_total_assets")


def receivable_days(receivables: float, sales: float, days: int = 365) -> float:
    return receivables / _nonzero(sales, "sales") * days


def inventory_days(inventory: float, cogs: float, days: int = 365) -> float:
    return inventory / _nonzero(cogs, "cogs") * days


def payable_days(payables: float, cogs: float, days: int = 365) -> float:
    return payables / _nonzero(cogs, "cogs") * days


def cash_conversion_cycle(rec_days: float, inv_days: float, pay_days: float) -> float:
    return rec_days + inv_days - pay_days


# --- cash quality ---
def free_cash_flow(cfo: float, capex: float) -> float:
    return cfo - capex


def fcf_to_pat(fcf: float, pat: float) -> float:
    return fcf / _nonzero(pat, "pat")


def cfo_to_ebitda(cfo: float, ebitda: float) -> float:
    return cfo / _nonzero(ebitda, "ebitda")
