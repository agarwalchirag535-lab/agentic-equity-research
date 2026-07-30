"""Registering shareholding patterns as citable facts (ADR-0035)."""

from __future__ import annotations

from datetime import date

import pytest

from firm.adapters.india.shareholding import ShareholdingSummary
from firm.core.facts.store import FactStore
from firm.core.ingest.governance import (
    PROMOTER_HOLDING,
    PROMOTER_PLEDGED,
    quarter_label,
    register_shareholding,
)


@pytest.fixture()
def store():
    s = FactStore(":memory:")
    yield s
    s.close()


def test_quarter_label_follows_the_indian_fiscal_year():
    assert quarter_label(date(2024, 6, 30)) == "Q1FY25"
    assert quarter_label(date(2024, 9, 30)) == "Q2FY25"
    assert quarter_label(date(2024, 12, 31)) == "Q3FY25"
    assert quarter_label(date(2025, 3, 31)) == "Q4FY25"


def test_publication_date_is_the_filing_deadline_not_the_quarter_end(store):
    """Dating a filing at its quarter end would place it public before it can exist — look-ahead.

    SEBI Reg. 31 gives 21 days after quarter end, so that is the earliest defensible date.
    """
    summary = ShareholdingSummary(located=True, promoter_pct=71.96, public_pct=28.04,
                                  pledged=False, as_on="2024-09-30", page=3)
    result = register_shareholding(store, "T", "shp.pdf", summary)

    assert result.period == "Q2FY25"
    assert result.published_at == date(2024, 10, 21)
    # Invisible the day before it was due, visible after — Law 3 through storage.
    assert store.query_fact("T", PROMOTER_HOLDING, "Q2FY25", as_of=date(2024, 10, 20)) is None
    fact = store.query_fact("T", PROMOTER_HOLDING, "Q2FY25", as_of=date(2024, 10, 21))
    assert fact is not None and fact.value == 71.96 and fact.grade == "A"


def test_an_unanswered_pledge_question_writes_no_fact(store):
    """The ADR-0027 tri-state must survive storage: silence is not "no pledge"."""
    answered = ShareholdingSummary(located=True, promoter_pct=71.96, public_pct=28.04,
                                   pledged=False, as_on="2024-09-30")
    register_shareholding(store, "ANSWERED", "a.pdf", answered)
    fact = store.query_fact("ANSWERED", PROMOTER_PLEDGED, "Q2FY25", as_of=date(2025, 1, 1))
    assert fact is not None and fact.value == 0.0

    silent = ShareholdingSummary(located=True, promoter_pct=71.96, public_pct=28.04,
                                 pledged=None, as_on="2024-09-30")
    register_shareholding(store, "SILENT", "b.pdf", silent)
    assert store.query_fact("SILENT", PROMOTER_PLEDGED, "Q2FY25", as_of=date(2025, 1, 1)) is None


def test_a_refused_or_undated_summary_writes_nothing(store):
    """A figure that failed its own acceptance test must never reach a reader."""
    refused = ShareholdingSummary(located=False, rejected_because="does not reconcile to 100%")
    assert register_shareholding(store, "T", "x.pdf", refused).fact_ids == ()

    undated = ShareholdingSummary(located=True, promoter_pct=71.96, public_pct=28.04, as_on=None)
    result = register_shareholding(store, "T", "y.pdf", undated)
    assert result.fact_ids == ()
    assert "point-in-time" in (result.skipped_because or "")
