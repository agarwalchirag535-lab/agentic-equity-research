"""Reverse DCF — solve for the growth the current price already demands (SPEC §5: 'reverse DCF first').

The most honest valuation question is not 'what is it worth?' but 'what does today's price require to be
true?'. This inverts the DCF to find the constant explicit-stage FCF growth rate implied by a given
enterprise value, via bisection (enterprise value is monotincreasing in growth).
"""

from __future__ import annotations

from firm.core.compute.dcf import dcf_enterprise_value


def implied_growth_rate(
    market_enterprise_value: float,
    base_fcf: float,
    discount_rate: float,
    terminal_growth: float,
    years: int,
    low: float = -0.5,
    high: float = 1.0,
    iterations: int = 100,
) -> float:
    """Constant FCF growth rate over the explicit window implied by ``market_enterprise_value``."""
    if base_fcf <= 0:
        raise ValueError("base_fcf must be positive")
    if years <= 0:
        raise ValueError("years must be positive")

    def ev_for_growth(g: float) -> float:
        forecast = [base_fcf * (1.0 + g) ** (t + 1) for t in range(years)]
        return dcf_enterprise_value(forecast, discount_rate, terminal_growth)

    if not (ev_for_growth(low) <= market_enterprise_value <= ev_for_growth(high)):
        raise ValueError("target enterprise value is not bracketed by [low, high] growth bounds")

    for _ in range(iterations):
        mid = (low + high) / 2.0
        if ev_for_growth(mid) < market_enterprise_value:
            low = mid
        else:
            high = mid
    return (low + high) / 2.0
