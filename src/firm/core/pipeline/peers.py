"""Compare a company against its peers on a COMMON period (Phase 3).

WHY sector_analyst NEEDED THIS
Its mandate is to locate the sector's profit pool and say who holds pricing power. Both are relative
claims — "this company earns more per rupee of sales than the firms it competes with" — and the roster
therefore gave it a `peers` prerequisite that nothing satisfied. Balaji Amines' annual reports were
already in the fact store, grade A, read by nobody: the ADR-0035 pattern a third time, data ingested and
unreachable.

THE TRAP THIS MODULE EXISTS TO AVOID
Comparing each company at *its own* latest period. The subject here has FY26 filed and the peer's latest
is FY25, so "latest vs latest" silently compares a year of one company against a different year of
another — across a period in which input costs, prices and demand all moved. The comparison would look
completely normal and be worthless. Every row therefore carries ONE period used for both sides, chosen as
the latest period where both companies have every input that row needs; a metric with no common period is
reported as incomparable *with the reason*, never dropped.

WHAT IT REFUSES TO DO
No proxies. Inventory days needs COGS, which neither company's ingested metric set carries cleanly, so
inventory days is simply not compared rather than computed off an "expenses" stand-in that would make two
companies' working capital look different when only the approximation differs. And no arithmetic lives
here: every figure comes from `core/compute/ratios.py` (Law 1), with both sides' input fact ids kept so
an agent can cite them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Callable, Mapping, Sequence

from firm.core.compute import ratios
from firm.core.facts.store import Fact, FactStore
from firm.core.pipeline.derive import (
    PAT,
    RECEIVABLES,
    SALES,
    CompanyFacts,
    load_company_facts,
)
from firm.schemas._base import Grade

#: Grade order, weakest last — a comparison is only as good as its worst input, on either side.
_GRADE_ORDER: tuple[Grade, ...] = (Grade.A, Grade.B, Grade.C, Grade.D)


@dataclass(frozen=True)
class Comparison:
    """One cross-company measure: what it needs, and the compute function that produces it."""

    name: str
    unit: str
    inputs: tuple[str, ...]
    formula: str
    fn: Callable[..., float]


#: The measures worth comparing across two companies in the same sector, and computable from the metric
#: set an annual-report walk actually yields on both sides. Deliberately short: each one answers a
#: question `sector_analyst` is asked, and none needs a proxy input.
COMPARISONS: tuple[Comparison, ...] = (
    # Scale: who is bigger. The identity function because sales is compared as filed, not as a ratio.
    Comparison("sales", "INR_cr", (SALES,), "Sales", lambda sales: sales),
    # Profit pool: who captures more of each rupee of revenue.
    Comparison("net_margin", "ratio", (PAT, SALES), "Net Profit / Sales", ratios.net_margin),
    # Bargaining power with customers: who finances whom.
    Comparison("receivable_days", "days", (RECEIVABLES, SALES), "Trade Receivables / Sales * 365",
               ratios.receivable_days),
)

#: Growth is compared over a window rather than at a point, so it is built separately from `COMPARISONS`.
_GROWTH = Comparison("sales_cagr", "ratio", (SALES,), "CAGR(Sales, first..last)", ratios.cagr)


@dataclass(frozen=True)
class PeerFigure:
    """One side of a comparison: the number, and the facts it was computed from."""

    ticker: str
    value: float
    fact_ids: tuple[str, ...]

    @property
    def cite_as(self) -> str:
        return f"[fact:peer:{self.ticker}:{{metric}}]"


@dataclass(frozen=True)
class PeerMetric:
    """One measure, computed for both companies on the SAME period.

    `period` is single by construction. Two periods would make this a different and much more dangerous
    object — the one that compares FY26 against FY25 and reads as though it did not.
    """

    metric: str
    period: str
    unit: str
    formula: str
    subject: PeerFigure
    peer: PeerFigure
    grade: str

    def fact_id(self, ticker: str) -> str:
        """The citable id for one side of this comparison."""
        return f"peer:{ticker}:{self.metric}:{self.period}"


@dataclass(frozen=True)
class PeerComparison:
    """Every measure comparable between two companies, and every measure that was not."""

    subject: str
    peer: str
    metrics: tuple[PeerMetric, ...] = ()
    incomparable: tuple[str, ...] = ()

    @property
    def comparable(self) -> bool:
        return bool(self.metrics)

    def citable(self) -> dict[str, float]:
        """{fact_id: value} for both sides of every row — what the citation gate checks a quote against."""
        out: dict[str, float] = {}
        for metric in self.metrics:
            out[metric.fact_id(self.subject)] = metric.subject.value
            out[metric.fact_id(self.peer)] = metric.peer.value
        return out


def _worst_grade(facts: Sequence[Fact]) -> str:
    seen = {Grade(f.grade) for f in facts}
    for grade in reversed(_GRADE_ORDER):
        if grade in seen:
            return grade.value
    return Grade.D.value  # pragma: no cover - unreachable: callers always pass at least one fact


def _common_periods(subject: CompanyFacts, peer: CompanyFacts, metrics: Sequence[str]) -> list[str]:
    """Periods, oldest first, where BOTH companies have every one of ``metrics``.

    This is the whole point of the module: a period is usable only if both sides can answer it.
    """
    return [
        period for period in subject.periods
        if all(subject.fact(m, period) is not None and peer.fact(m, period) is not None
               for m in metrics)
    ]


def _figure(facts: CompanyFacts, comparison: Comparison, period: str) -> PeerFigure | None:
    inputs = [facts.fact(m, period) for m in comparison.inputs]
    if any(f is None for f in inputs):
        return None  # pragma: no cover - callers pre-filter on _common_periods
    values = [f.value for f in inputs if f is not None]
    try:
        value = comparison.fn(*values)
    except (ValueError, ZeroDivisionError):
        # A zero denominator is a real state of the world (a company with no sales that year), not a bug.
        # It makes the measure undefined, and an undefined measure must not be reported as a number.
        return None
    return PeerFigure(facts.ticker, value,
                      tuple(f.fact_id for f in inputs if f is not None))


def _point_metric(
    subject: CompanyFacts, peer: CompanyFacts, comparison: Comparison
) -> PeerMetric | str:
    """One comparison at the latest common period, or a sentence explaining why there is none."""
    periods = _common_periods(subject, peer, comparison.inputs)
    if not periods:
        needed = ", ".join(comparison.inputs)
        return (f"{comparison.name} is not compared: {subject.ticker} and {peer.ticker} share no period "
                f"in which both disclose {needed}")
    period = periods[-1]
    subject_side = _figure(subject, comparison, period)
    peer_side = _figure(peer, comparison, period)
    if subject_side is None or peer_side is None:
        return (f"{comparison.name} is not compared: it is undefined for at least one company at "
                f"{period}")
    facts = [f for side, company in ((subject_side, subject), (peer_side, peer))
             for f in (company.fact(m, period) for m in comparison.inputs) if f is not None]
    return PeerMetric(
        metric=comparison.name, period=period, unit=comparison.unit, formula=comparison.formula,
        subject=subject_side, peer=peer_side, grade=_worst_grade(facts),
    )


def _growth_metric(subject: CompanyFacts, peer: CompanyFacts) -> PeerMetric | str:
    """Sales CAGR over the longest window BOTH companies cover, so neither gets a friendlier period.

    A peer with five years of history and a subject with twelve must be compared over the five they share;
    measuring each over its own record would compare a half-cycle against a full one.
    """
    periods = _common_periods(subject, peer, _GROWTH.inputs)
    if len(periods) < 2:
        return (f"sales_cagr is not compared: {subject.ticker} and {peer.ticker} share fewer than two "
                f"periods of disclosed Sales")
    first, last = periods[0], periods[-1]
    span = int(last[2:]) - int(first[2:])
    window = f"{first}-{last}"
    sides: list[PeerFigure] = []
    facts: list[Fact] = []
    for company in (subject, peer):
        start, end = company.fact(SALES, first), company.fact(SALES, last)
        if start is None or end is None:
            return f"sales_cagr is not compared: Sales is missing at a window bound"  # pragma: no cover
        try:
            value = ratios.cagr(start.value, end.value, span)
        except ValueError:
            return (f"sales_cagr is not compared: {company.ticker} has a non-positive Sales endpoint "
                    f"over {window}, which has no compound rate")
        sides.append(PeerFigure(company.ticker, value, (start.fact_id, end.fact_id)))
        facts += [start, end]
    return PeerMetric(
        metric=_GROWTH.name, period=window, unit=_GROWTH.unit,
        formula=f"CAGR(Sales, {window})", subject=sides[0], peer=sides[1], grade=_worst_grade(facts),
    )


def compare(subject: CompanyFacts, peer: CompanyFacts) -> PeerComparison:
    """Every comparable measure between two companies, each on a period they both cover."""
    metrics: list[PeerMetric] = []
    incomparable: list[str] = []
    for comparison in (*COMPARISONS, _GROWTH):
        result = (_growth_metric(subject, peer) if comparison is _GROWTH
                  else _point_metric(subject, peer, comparison))
        if isinstance(result, PeerMetric):
            metrics.append(result)
        else:
            incomparable.append(result)
    return PeerComparison(subject.ticker, peer.ticker, tuple(metrics), tuple(incomparable))


def load_peer_comparisons(
    store: FactStore, subject: str, peers: Sequence[str], as_of: date, *, start_year: int = 2015
) -> list[PeerComparison]:
    """Compare ``subject`` against each of ``peers``, reading every side point-in-time (Law 3).

    A peer with no facts as-of the date yields a comparison with nothing in it and a stated reason, rather
    than being dropped: "we have no data on the peer we named" is a finding about the firm's coverage.
    """
    subject_facts = load_company_facts(store, subject, as_of, start_year=start_year)
    out: list[PeerComparison] = []
    for ticker in peers:
        peer_facts = load_company_facts(store, ticker, as_of, start_year=start_year)
        if not peer_facts.periods:
            out.append(PeerComparison(subject, ticker, (), (
                f"no facts for {ticker} published on or before {as_of.isoformat()}, so no measure "
                f"could be compared",
            )))
            continue
        out.append(compare(subject_facts, peer_facts))
    return out


def payload_rows(comparisons: Sequence[PeerComparison]) -> list[dict[str, object]]:
    """The peer block as the agent packet carries it: values, both sides' ids, and what is incomparable."""
    return [
        {
            "peer": comparison.peer,
            "metrics": [
                {
                    "metric": m.metric,
                    "period": m.period,
                    "unit": m.unit,
                    "formula": m.formula,
                    "grade": m.grade,
                    comparison.subject: {
                        "value": m.subject.value,
                        "cite_as": f"[fact:{m.fact_id(comparison.subject)}]",
                    },
                    comparison.peer: {
                        "value": m.peer.value,
                        "cite_as": f"[fact:{m.fact_id(comparison.peer)}]",
                    },
                }
                for m in comparison.metrics
            ],
            "not_compared": list(comparison.incomparable),
        }
        for comparison in comparisons
    ]


def citable_values(comparisons: Sequence[PeerComparison]) -> dict[str, float]:
    """{fact_id: value} across every comparison, for the citation gate."""
    out: dict[str, float] = {}
    for comparison in comparisons:
        out.update(comparison.citable())
    return out


__all__ = [
    "COMPARISONS",
    "Comparison",
    "PeerComparison",
    "PeerFigure",
    "PeerMetric",
    "citable_values",
    "compare",
    "load_peer_comparisons",
    "payload_rows",
]
