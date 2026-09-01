"""The valuation bridge: facts + price + stated policy -> a priced scenario set (Phase 4, ADR-0062).

WHERE THIS SITS. `checks.py` turns facts into forensic verdicts; this turns facts into a price
judgment, and it is the same shape on purpose — every input it lacks is NAMED rather than defaulted,
and the result carries its own reasons. A valuation that quietly substitutes a zero for a missing net
debt is worse than no valuation, because it looks like one.

REVERSE DCF FIRST (SPEC §5). The forward DCF's answer is hostage to the discount rate and to which
year's cash flow you call "base" — two choices the analyst makes, so the answer partly restates the
assumption. The reverse DCF inverts it: hold the price fixed, solve for the growth it already demands,
and hand the reader a falsifiable sentence — "this price requires 27% FCF growth for a decade; the
company has managed 12%, and no Indian speciality chemical business has sustained 27% for ten years."
That is a claim a reader can check against the base rate, which is what the house standard asks for.

LAW 1. Everything here is arithmetic over grade-A facts and a stated policy block. The agent layer
receives this result and argues about it; it authors none of it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Mapping, Sequence

from firm.core.compute import reverse_dcf
from firm.core.compute.scenarios import (
    ScenarioValuation,
    scenario_growth_grid,
    value_scenario_grid,
)
from firm.core.pipeline import derive as D
from firm.core.pipeline.derive import CompanyFacts, DerivedSet


@dataclass(frozen=True)
class ValuationResult:
    """A priced view of one company at one `as_of`, or an explicit account of why there is none."""

    status: str                                   # 'valued' | 'unavailable'
    #: Inputs the valuation needed and did not have. Empty iff `status == 'valued'`.
    missing: tuple[str, ...] = ()
    price: float | None = None
    price_on: date | None = None
    shares_cr: float | None = None
    market_cap_cr: float | None = None
    net_debt_cr: float | None = None
    enterprise_value_cr: float | None = None
    base_fcf_cr: float | None = None
    realised_growth: float | None = None
    #: The growth the quoted price already demands. None when the price implies growth outside the
    #: configured bracket — which is itself reported, in `implied_growth_note`.
    implied_growth: float | None = None
    implied_growth_note: str = ""
    scenarios: tuple[ScenarioValuation, ...] = ()
    assumptions: Mapping[str, float] = field(default_factory=dict)
    #: The facts this valuation rests on, so its derivations carry a citation and the
    #: worst-input grade like every other number in the report.
    inputs: tuple[Any, ...] = ()

    @property
    def valued(self) -> bool:
        return self.status == "valued"


def _shares_outstanding(facts: CompanyFacts, period: str) -> tuple[float | None, tuple[Any, ...]]:
    """Share count in crore, from the filing's OWN identity: PAT / EPS.

    Not from a face-value assumption and not from an exchange field: both PAT (₹ crore) and basic EPS
    (₹ per share) are grade-A figures printed on the same audited page, and their quotient is the
    weighted share count the company itself used. An identity the filing prints beats a number we
    would have to source separately — the same reasoning that established Five-Star's page scale.
    """
    pat = facts.fact(D.PAT, period)
    eps = facts.fact(D.EPS, period)
    if pat is None or eps is None or eps.value == 0:
        return None, ()
    shares = pat.value / eps.value
    return (shares, (pat, eps)) if shares > 0 else (None, ())


def value_company(
    facts: CompanyFacts,
    derived: DerivedSet,
    *,
    price: float | None,
    price_on: date | None,
    policy: Mapping[str, Any],
    price_facts: Sequence[Any] = (),
) -> ValuationResult:
    """Price the company, or say precisely what stopped it."""
    period = derived.last_period or ""
    missing: list[str] = []
    ids: list[Any] = list(price_facts)

    if not period:
        # No readable period at all: say THAT, rather than emitting four gaps whose text reads
        # "share count for " — a message with a blank where its subject should be tells the reader
        # nothing, and this one would have shipped in a published report.
        return ValuationResult(
            "unavailable",
            ("any annual period readable at this as_of — the store holds no financial year for this "
             "company on or before the run date, so there is nothing to value",),
            price=price, price_on=price_on, assumptions=dict(policy))

    if price is None:
        missing.append("a settled exchange close at or before as_of (market:Close)")
    shares, share_ids = _shares_outstanding(facts, period)
    if shares is None:
        missing.append(f"share count for {period} — needs {D.PAT} and a non-zero {D.EPS}")
    else:
        ids.extend(share_ids)

    fcf = facts.fact(D.FCF, period)
    if fcf is None:
        missing.append(f"{D.FCF} {period} (the cash the business itself produced)")
    elif fcf.value <= 0:
        missing.append(
            f"{D.FCF} {period} is {fcf.value:,.2f}cr — a company burning cash cannot be valued by "
            "discounting it; the question is funding, not price")
    else:
        ids.append(fcf)

    net_cash = derived.get("net_cash_position")
    if net_cash is None:
        missing.append("net cash/debt (Cash + Other Bank Balances - Borrowings)")

    growth = derived.get("fcf_cagr") or derived.get("pat_cagr")
    if growth is None:
        missing.append("a realised growth anchor (FCF or PAT CAGR) to centre the scenario grid on")

    if missing:
        return ValuationResult("unavailable", tuple(missing), price=price, price_on=price_on,
                               assumptions=dict(policy))

    assert price is not None and shares is not None and fcf is not None
    assert net_cash is not None and growth is not None
    ids.extend(net_cash.inputs)
    ids.extend(growth.inputs)

    market_cap = price * shares                     # ₹/share x crore shares = ₹ crore
    net_debt = -net_cash.value                      # net_cash_position is cash MINUS borrowings
    enterprise_value = market_cap + net_debt

    implied: float | None = None
    note = ""
    try:
        implied = reverse_dcf.implied_growth_rate(
            enterprise_value, fcf.value, policy["discount_rate"], policy["terminal_growth"],
            int(policy["explicit_years"]),
            low=policy["implied_growth_min"], high=policy["implied_growth_max"])
    except ValueError:
        # NOT an error to swallow: a price the DCF cannot bracket is a statement about the price.
        note = (
            f"the quoted price implies FCF growth outside "
            f"[{policy['implied_growth_min']:.0%}, {policy['implied_growth_max']:.0%}] for "
            f"{int(policy['explicit_years'])} years at a {policy['discount_rate']:.0%} discount rate — "
            "this price cannot be justified by discounting the company's own cash at all, whichever "
            "end of the band it fails")

    grid = scenario_growth_grid(
        growth.value, bull_spread=policy["bull_spread"], bear_spread=policy["bear_spread"],
        disaster_growth=policy["disaster_growth"])
    scenarios = value_scenario_grid(
        base_fcf=fcf.value, growth_by_scenario=grid, discount_rate=policy["discount_rate"],
        terminal_growth=policy["terminal_growth"], years=int(policy["explicit_years"]),
        net_debt=net_debt, shares_outstanding=shares, price_today=price)

    return ValuationResult(
        "valued", (), price=price, price_on=price_on, shares_cr=shares, market_cap_cr=market_cap,
        net_debt_cr=net_debt, enterprise_value_cr=enterprise_value, base_fcf_cr=fcf.value,
        realised_growth=growth.value, implied_growth=implied, implied_growth_note=note,
        scenarios=tuple(scenarios), assumptions=dict(policy),
        inputs=tuple({f.fact_id: f for f in ids}.values()),
    )


#: Valuation outputs that become derivations, so the Law-1 validator and the citation machinery see
#: them without a second implementation. Name -> (attribute, formula template).
_AS_DERIVATIONS: tuple[tuple[str, str, str], ...] = (
    ("market_cap_cr", "market_cap", "settled close x (PAT / EPS) share count"),
    ("enterprise_value_cr", "enterprise_value", "market cap + net debt"),
    ("implied_growth", "reverse_dcf_implied_growth",
     "growth solved from enterprise value by inverting the DCF"),
)


def valuation_derivations(result: ValuationResult) -> dict[str, D.Derivation]:
    """The valuation's numbers as `Derivation`s, ready to merge into the run's `DerivedSet`.

    `base_case_value_per_share` comes from the BASE scenario specifically — the one centred on the
    company's own realised growth. Naming it here rather than letting an agent choose which scenario
    is "base" is deliberate: "base case" is exactly the label an optimistic reading would quietly
    reassign to the bull column.
    """
    if not result.valued:
        return {}
    inputs = tuple(result.inputs)
    out: dict[str, D.Derivation] = {}
    for attr, metric, formula in _AS_DERIVATIONS:
        value = getattr(result, attr)
        if value is not None:
            out[metric] = D.Derivation(metric, float(value), formula, inputs)
    base = next((s for s in result.scenarios if s.name == "base"), None)
    if base is not None:
        out["base_case_value_per_share"] = D.Derivation(
            "base_case_value_per_share", base.value_per_share,
            f"DCF at the company's realised growth ({base.growth:+.2%}), "
            f"{result.assumptions['discount_rate']:.0%} discount, per share", inputs)
    return out
