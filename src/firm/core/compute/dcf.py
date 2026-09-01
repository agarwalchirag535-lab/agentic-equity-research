"""Discounted cash flow: present value, Gordon terminal, and a 2-stage enterprise DCF (Phase 1)."""

from __future__ import annotations

from collections.abc import Sequence


def present_value(cashflows: Sequence[float], discount_rate: float) -> float:
    """PV of a stream, first cash flow one period out."""
    if discount_rate <= -1.0:
        raise ValueError("discount_rate must exceed -100%")
    return sum(cf / (1.0 + discount_rate) ** (t + 1) for t, cf in enumerate(cashflows))


def terminal_value_gordon(fcf_next: float, discount_rate: float, terminal_growth: float) -> float:
    """Gordon growth terminal value = FCF_next / (r − g)."""
    if discount_rate <= terminal_growth:
        raise ValueError("discount_rate must exceed terminal_growth")
    return fcf_next / (discount_rate - terminal_growth)


def dcf_enterprise_value(
    fcf_forecast: Sequence[float], discount_rate: float, terminal_growth: float
) -> float:
    """Enterprise value = PV(explicit FCFs) + PV(terminal value)."""
    if len(fcf_forecast) == 0:
        raise ValueError("empty forecast")
    pv_explicit = present_value(fcf_forecast, discount_rate)
    terminal = terminal_value_gordon(fcf_forecast[-1] * (1.0 + terminal_growth), discount_rate, terminal_growth)
    pv_terminal = terminal / (1.0 + discount_rate) ** len(fcf_forecast)
    return pv_explicit + pv_terminal


def equity_value(enterprise_value: float, net_debt: float) -> float:
    return enterprise_value - net_debt


def value_per_share(equity_value_amount: float, shares_outstanding: float) -> float:
    if shares_outstanding <= 0:
        raise ValueError("shares_outstanding must be positive")
    return equity_value_amount / shares_outstanding
