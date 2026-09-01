"""Probability-weighted scenario analysis (SPEC §5: bear/base/bull/disaster, probabilities sum to 1)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from firm.core.compute.dcf import dcf_enterprise_value, equity_value, value_per_share


@dataclass(frozen=True)
class Scenario:
    name: str
    probability: float
    return_multiple: float


def validate_probabilities(scenarios: Sequence[Scenario], tol: float = 1e-6) -> None:
    """Probabilities must be non-negative and sum to 1 (SPEC §5)."""
    if len(scenarios) == 0:
        raise ValueError("no scenarios")
    total = sum(s.probability for s in scenarios)
    if abs(total - 1.0) > tol:
        raise ValueError(f"probabilities must sum to 1, got {total}")
    for s in scenarios:
        if s.probability < 0:
            raise ValueError("probability cannot be negative")


def expectancy(scenarios: Sequence[Scenario]) -> float:
    """Expected return multiple = Σ p_i × return_i (SPEC §5 / PM expectancy)."""
    validate_probabilities(scenarios)
    return sum(s.probability * s.return_multiple for s in scenarios)


# --------------------------------------------------------------------------------------------------
# The valuation grid (Phase 4, ADR-0062). Law 1 lives exactly here: an agent may argue the PROBABILITY
# of a scenario, and may never author its return multiple.
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ScenarioValuation:
    """One scenario priced by the compute layer: its growth, what that is worth, and versus what."""

    name: str
    growth: float
    value_per_share: float
    #: intrinsic value under this scenario / the price actually quoted today. NOT a target price and
    #: NOT a re-rating: no multiple expansion is assumed anywhere in this number.
    return_multiple: float


def scenario_growth_grid(
    realised_growth: float, *, bull_spread: float, bear_spread: float, disaster_growth: float
) -> dict[str, float]:
    """Four growth paths ANCHORED TO THE COMPANY'S OWN REALISED GROWTH, not to a house guess.

    A fixed grid ("base = 10% for everybody") is the analytical failure the house standard's "state the
    base rate first" exists to prevent: a business that has compounded 25% and one that has managed 3%
    do not share a base case, and pretending they do makes every valuation a statement about the grid
    rather than about the company. The spreads are policy (config); the anchor is the company's record.

    `disaster` is ABSOLUTE, not a spread: the disaster case is not "a bit worse than usual", it is the
    business shrinking, and that floor is the same question for every company.
    """
    return {
        "disaster": disaster_growth,
        "bear": realised_growth - bear_spread,
        "base": realised_growth,
        "bull": realised_growth + bull_spread,
    }


def value_scenario_grid(
    *,
    base_fcf: float,
    growth_by_scenario: Mapping[str, float],
    discount_rate: float,
    terminal_growth: float,
    years: int,
    net_debt: float,
    shares_outstanding: float,
    price_today: float,
) -> list[ScenarioValuation]:
    """Price every scenario by DCF. The return multiple is intrinsic value over the quoted price.

    WHY VALUE/PRICE AND NOT A PRICE TARGET. `agents/valuation_modeler.md` names the failure mode it
    must not commit: "silently assuming a 3x re-rating and calling it conservative". A price target
    needs an exit multiple, and an assumed exit multiple is where that assumption hides. Discounting
    the cash the business itself produces needs no exit multiple at all — the terminal value is Gordon
    on the company's own final-year FCF — so a return of 3x here means the cash is worth three times
    the price, not that someone will pay three times the multiple.

    A growth rate at or above the discount rate is refused rather than valued: the Gordon terminal
    diverges, and a DCF that returns infinity is not a bullish valuation, it is an arithmetic error
    wearing one.
    """
    if price_today <= 0:
        raise ValueError("price_today must be positive")
    if terminal_growth >= discount_rate:
        raise ValueError("terminal growth must be below the discount rate (Gordon diverges otherwise)")
    out: list[ScenarioValuation] = []
    for name, growth in growth_by_scenario.items():
        forecast = [base_fcf * (1.0 + growth) ** (t + 1) for t in range(years)]
        ev = dcf_enterprise_value(forecast, discount_rate, terminal_growth)
        per_share = value_per_share(equity_value(ev, net_debt), shares_outstanding)
        out.append(ScenarioValuation(name, growth, per_share, per_share / price_today))
    return out


def expectancy_from(
    valuations: Sequence[ScenarioValuation], probabilities: Mapping[str, float]
) -> float:
    """Probability-weighted return, from the agent's PROBABILITIES and the compute layer's MULTIPLES.

    This function is the Law-1 seam of the whole judgment tier, and the reason the agent schema's
    `expectancy` field must arrive null: expectancy is a number, so an LLM may not author it — but it
    is a function of a judgment (how likely is the bull case?) that only an analyst can supply. The
    analyst supplies the weights; this computes the number. A probability naming no scenario, or a set
    that does not sum to 1, is refused — a weighting that does not cover the outcome space is not a
    judgment, it is an omission.
    """
    priced = {v.name: v for v in valuations}
    unknown = sorted(set(probabilities) - set(priced))
    if unknown:
        raise ValueError(f"probabilities name scenarios the compute layer never priced: {unknown}")
    missing = sorted(set(priced) - set(probabilities))
    if missing:
        raise ValueError(f"no probability supplied for priced scenario(s): {missing}")
    validate_probabilities([Scenario(n, p, priced[n].return_multiple) for n, p in probabilities.items()])
    return sum(p * priced[n].return_multiple for n, p in probabilities.items())
