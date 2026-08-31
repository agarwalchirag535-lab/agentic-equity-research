"""A period label is not a period, part two: WHEN a company closes its books (ADR-0049).

Symphony Ltd closed on 30 June through FY15 and on 31 March from FY17. `FY15` therefore means a
different twelve months for it than for almost every other Indian company. Adapted at the branch merge
(ADR-0054): the sibling line REFUSED growth rates across the change; the trunk CORRECTS the exponent
to the true elapsed years between the stated closes — no figure is estimated, only the clock — so
these tests now assert the correction, and `fiscal_calendar_change` remains the narratable fact.
"""

from __future__ import annotations

from datetime import date

import pytest

from firm.core.facts.store import Document, FactStore
from firm.core.pipeline import derive as D

#: (period, period_end) — Symphony's real calendar around the move.
JUNE_YEARS = {"FY14": date(2014, 6, 30), "FY15": date(2015, 6, 30)}
MARCH_YEARS = {"FY17": date(2017, 3, 31), "FY18": date(2018, 3, 31)}


def _store(calendar: dict[str, date], sales: dict[str, float]) -> FactStore:
    store = FactStore(":memory:")
    for period, ends in calendar.items():
        doc = f"AR-{period}"
        pub = date(ends.year, 12, 1)
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
    assert fact is not None and fact.period_end == date(2015, 6, 30)


def test_a_consistent_calendar_computes_growth_as_before():
    facts = D.load_company_facts(
        _store(MARCH_YEARS, {"FY17": 764.75, "FY18": 798.25}), "T", date(2018, 12, 31),
        start_year=2017)
    assert facts.fiscal_calendar_change("FY17", "FY18") is None
    derived = D.derive_metrics(facts)
    assert derived.values["revenue_cagr"].value == pytest.approx(798.25 / 764.75 - 1, abs=1e-6)


def test_growth_across_a_moved_year_end_compounds_over_the_true_elapsed_years():
    """FY14 closed 30 June 2014 and FY18 closed 31 March 2018 — 3.7515 years lived, 4 counted by the
    labels. The rate is computed, not refused, and the formula prints the exponent it used."""
    facts = D.load_company_facts(
        _store({**JUNE_YEARS, **MARCH_YEARS},
               {"FY14": 532.70, "FY15": 578.89, "FY17": 764.75, "FY18": 798.25}),
        "T", date(2018, 12, 31), start_year=2014)
    assert facts.fiscal_calendar_change("FY14", "FY18") == (6, 3)   # still a narratable fact
    derived = D.derive_metrics(facts)
    got = derived.values["revenue_cagr"]
    true_years = (date(2018, 3, 31) - date(2014, 6, 30)).days / 365.2425
    assert got.value == pytest.approx((798.25 / 532.70) ** (1 / true_years) - 1, abs=1e-4)
    assert f"1/{round(true_years, 4)}" in got.formula


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
