"""A period label is not a period, part two: WHEN a company closes its books (ADR-0049).

Symphony Ltd closed on 30 June through FY15 and on 31 March from FY17. `FY15` therefore means a
different twelve months for it than for almost every other Indian company, and a growth rate spanning
the change compares windows that do not line up.
"""

from __future__ import annotations

from datetime import date

import pytest

from firm.core.facts.store import Document, FactStore
from firm.core.pipeline import derive as D

#: (period, period_end) — Symphony's real calendar around the move.
JUNE_YEARS = {"FY14": "2014-06-30", "FY15": "2015-06-30"}
MARCH_YEARS = {"FY17": "2017-03-31", "FY18": "2018-03-31"}


def _store(calendar: dict[str, str], sales: dict[str, float]) -> FactStore:
    store = FactStore(":memory:")
    for period, ends in calendar.items():
        doc = f"AR-{period}"
        pub = date(int(ends[:4]), 12, 1)
        store.add_document(Document(doc_id=doc, source_url="u", sha256="", published_at=pub,
                                    fetched_at=pub, grade="A", extractor_version="t@1"))
        for metric, value in ((D.SALES, sales[period]), (D.PAT, sales[period] * 0.2)):
            store.add_fact(fact_id=f"{doc}:{metric}:{period}", doc_id=doc, ticker="T", metric=metric,
                           period=period, value=value, unit="INR_cr", locator="p.1",
                           period_end=ends)
    return store


def test_period_end_round_trips_through_the_store():
    store = _store(JUNE_YEARS, {"FY14": 532.70, "FY15": 578.89})
    fact = store.query_fact("T", D.SALES, "FY15", date(2018, 12, 31))
    assert fact is not None and fact.period_end == "2015-06-30"


def test_a_consistent_calendar_computes_growth_as_before():
    facts = D.load_company_facts(
        _store(MARCH_YEARS, {"FY17": 764.75, "FY18": 798.25}), "T", date(2018, 12, 31),
        start_year=2017)
    assert facts.fiscal_calendar_change("FY17", "FY18") is None
    derived = D.derive_metrics(facts)
    assert derived.values["revenue_cagr"].value == pytest.approx(798.25 / 764.75 - 1, abs=1e-6)


def test_growth_across_a_moved_year_end_is_refused_with_the_reason():
    facts = D.load_company_facts(
        _store({**JUNE_YEARS, **MARCH_YEARS},
               {"FY14": 532.70, "FY15": 578.89, "FY17": 764.75, "FY18": 798.25}),
        "T", date(2018, 12, 31), start_year=2014)
    assert facts.fiscal_calendar_change("FY14", "FY18") == (6, 3)
    derived = D.derive_metrics(facts)
    for metric in ("revenue_cagr", "pat_cagr"):
        assert metric not in derived.values
        why = derived.missing[metric][0]
        assert "moved its financial year-end" in why and "June close -> March" in why


def test_a_close_month_is_read_never_inferred():
    """A fact whose source did not state its period end contributes no opinion about the calendar —
    it is unknown, not assumed to be March."""
    store = FactStore(":memory:")
    pub = date(2018, 12, 1)
    store.add_document(Document(doc_id="AR-X", source_url="u", sha256="", published_at=pub,
                                fetched_at=pub, grade="A", extractor_version="t@1"))
    store.add_fact(fact_id="AR-X:s:FY18", doc_id="AR-X", ticker="T", metric=D.SALES, period="FY18",
                   value=1.0, unit="INR_cr", locator="p.1")           # no period_end
    facts = D.load_company_facts(store, "T", date(2018, 12, 31), start_year=2018)
    assert facts.fiscal_close_month("FY18") is None
    assert facts.fiscal_calendar_change("FY18", "FY18") is None       # unknown never fabricates a change
