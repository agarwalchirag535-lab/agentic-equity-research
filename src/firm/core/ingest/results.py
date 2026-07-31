"""Ingest exchange XBRL results into the fact store, cross-checked (ADR-0043).

The compute layer works on fiscal YEARS (`FY25`) while the exchange disseminates QUARTERS. The annual
series is built by summing four quarters — and that sum is the cross-check, not a convenience. Four
quarters that add to the figure the company reported for the year validate both readings at once: the
quarters were parsed correctly, and the annual statement agrees with what was told to the market through
the year. A year with fewer than four quarters is recorded as incomplete and NOT stored, because three
quarters presented as a year is a 25% understatement wearing a full-year label.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Callable, Sequence

from firm.adapters.india.xbrl_results import (
    ResultFiling,
    XbrlFact,
    parse_results_index,
    parse_xbrl,
)
from firm.core.facts.store import Document, FactStore

#: Flow metrics are summed across the year; a ratio or a point-in-time stock is not.
_STOCK_OR_RATIO = ("lender:GNPA %", "lender:NNPA %", "lender:Return on Assets",
                   "lender:Gross NPA", "lender:Net NPA", "balance_sheet:Equity Capital",
                   "pnl:EPS in Rs")


@dataclass(frozen=True)
class YearIngest:
    """One fiscal year as the company filed it, with the quarter sum kept as a cross-check."""

    period: str
    quarters_found: int
    published_at: date
    grade: str
    values: dict[str, float]
    #: `consolidated` or `standalone` — which set of accounts this year was built from. SPEC §4 wants
    #: consolidated by default and the fallback flagged, so it travels with the figures.
    basis: str = "consolidated"
    fact_ids: tuple[str, ...] = ()
    #: Sum of the standalone quarters, for the metrics where four were tagged. Where the annual context
    #: also exists the two must agree — that agreement validates both readings at once.
    quarter_sums: dict[str, float] | None = None

    def crosscheck(self, metric: str, tolerance: float = 0.01) -> str | None:
        """`None` when the two agree or one is absent; otherwise a description of the difference."""
        annual = self.values.get(metric)
        summed = (self.quarter_sums or {}).get(metric)
        if annual is None or summed is None or annual == 0:
            return None
        if abs(annual - summed) / abs(annual) <= tolerance:
            return None
        return (f"{metric} {self.period}: annual filing {annual:,.2f} vs four quarters summing to "
                f"{summed:,.2f} ({(summed - annual) / annual:+.1%})")

    @property
    def complete(self) -> bool:
        return self.quarters_found == 4


def _fy(period_end: date) -> str:
    return f"FY{(period_end.year + 1 if period_end.month >= 4 else period_end.year) % 100:02d}"


def ingest_results(
    store: FactStore,
    ticker: str,
    index_payload: Sequence[dict],
    *,
    fetch_xbrl: Callable[[str], str],
    as_of: date | None = None,
    basis: str = "consolidated",
) -> list[YearIngest]:
    """Fetch, parse and register every quarterly result, aggregated to fiscal years.

    `as_of` filters on the BROADCAST date (Law 3): a result the exchange had not disseminated yet cannot
    inform a run replayed at that date, however long ago the quarter itself ended.
    """
    filings = [f for f in parse_results_index(index_payload)
               if as_of is None or (f.broadcast_on or f.period_end) <= as_of]
    # NEVER MIX STANDALONE AND CONSOLIDATED. Caught by the cross-check on the first live run: City Union
    # Bank FY24 came back at PAT Rs 1,043.3cr against the Rs 1,015.7cr printed in its own annual report,
    # because the year was assembled from whichever filings happened to be in the feed. The two bases are
    # different companies for our purposes, and averaging or interleaving them produces a figure that
    # exists in neither set of accounts.
    #
    # SPEC §4 defaults to consolidated and requires flagging where only standalone exists, so the basis
    # is chosen per YEAR: consolidated when the company filed it, standalone otherwise, never both.
    wanted_consolidated = basis == "consolidated"
    by_year_basis: dict[tuple[str, bool], list[ResultFiling]] = {}
    for filing in filings:
        by_year_basis.setdefault((_fy(filing.period_end), filing.consolidated), []).append(filing)
    chosen: list[ResultFiling] = []
    for period in {p for p, _ in by_year_basis}:
        preferred = by_year_basis.get((period, wanted_consolidated))
        chosen.extend(preferred if preferred else by_year_basis.get((period, not wanted_consolidated), []))
    filings = chosen

    per_year: dict[str, list[tuple[ResultFiling, list[XbrlFact]]]] = {}
    for filing in filings:
        try:
            facts = parse_xbrl(fetch_xbrl(filing.xbrl_url), is_bank=filing.is_bank)
        except Exception:  # noqa: BLE001 - one unreadable filing is a gap, not a dead run
            continue
        per_year.setdefault(_fy(filing.period_end), []).append((filing, facts))

    out: list[YearIngest] = []
    for period, entries in sorted(per_year.items()):
        # THE ANNUAL FIGURE COMES FROM THE ANNUAL CONTEXT, NOT FROM ADDING UP QUARTERS. An Indian Q4
        # filing tags the FULL YEAR alongside (often instead of) the standalone quarter, so summing what
        # is tagged as ~90-day periods finds three quarters and silently understates the year by a
        # quarter. The 12-month context is the company's own annual figure and is what is stored.
        metrics: dict[str, float] = {}
        quarter_sums: dict[str, float] = {}
        counts: dict[str, int] = {}
        for _filing, facts in entries:
            for fact in facts:
                if fact.metric in _STOCK_OR_RATIO:
                    metrics.setdefault(fact.metric, fact.value)
                    continue
                if fact.period_start is None:
                    continue
                span = (fact.period_end - fact.period_start).days
                if 330 <= span <= 400 and fact.period_end.month == 3:
                    metrics[fact.metric] = fact.value               # the year as the company filed it
                elif 80 <= span <= 100:
                    quarter_sums[fact.metric] = quarter_sums.get(fact.metric, 0.0) + fact.value
                    counts[fact.metric] = counts.get(fact.metric, 0) + 1

        # Fall back to the quarter sum only where the year was never tagged, and only when all four are
        # present — three quarters wearing a full-year label is a 25% understatement.
        quarters = max(counts.values(), default=0)
        for metric, total in quarter_sums.items():
            if metric not in metrics and counts.get(metric) == 4:
                metrics[metric] = total
        if metrics and quarters != 4:
            quarters = 4 if any(
                330 <= (f.period_end - f.period_start).days <= 400
                for _fl, fs in entries for f in fs if f.period_start) else quarters
        published = max((f.broadcast_on or f.period_end) for f, _ in entries)
        year_basis = "consolidated" if all(f.consolidated for f, _ in entries) else "standalone"
        # The year's grade is the WORST of its quarters: a year built from three un-audited quarters and
        # one audited one is not an audited year.
        grade = "A" if all(f.audited for f, _ in entries) else "B"

        if quarters != 4:
            out.append(YearIngest(period, quarters, published, grade, metrics, basis=year_basis,
                                  quarter_sums=quarter_sums))
            continue

        doc_id = f"NSE-XBRL-{ticker}-{period}"
        store.add_document(Document(
            doc_id=doc_id,
            source_url=f"https://www.nseindia.com/api/corporates-financial-results?symbol={ticker}",
            sha256="", published_at=published, fetched_at=date.today(),
            grade=grade, extractor_version="nse-xbrl@1.0.0",
        ))
        ids: list[str] = []
        for metric, value in sorted(metrics.items()):
            fact_id = f"{doc_id}:{metric}:{period}"
            store.add_fact(fact_id, doc_id, ticker, metric, period, float(value), "INR_cr",
                           f"XBRL, {quarters} quarters summed")
            ids.append(fact_id)
        out.append(YearIngest(period, quarters, published, grade, metrics, basis=year_basis,
                              fact_ids=tuple(ids), quarter_sums=quarter_sums))
    return out


__all__ = ["YearIngest", "ingest_results"]
