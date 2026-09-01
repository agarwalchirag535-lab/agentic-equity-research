"""Registering transcript guidance as citable facts (ADR-0040 — the ADR-0035 step for transcripts)."""

from __future__ import annotations

from datetime import date

import pytest

from firm.adapters.india.transcripts import GuidanceStatement, GuidanceValue, TranscriptSummary
from firm.core.facts.store import FactStore
from firm.core.ingest.transcripts import register_transcript

GROWTH = GuidanceStatement(
    page=16, quote="So, we expect double digit growth in next year around 10% to 15%.",
    kind="statement", topic="volume_growth",
    values=(GuidanceValue(10.0, "pct"), GuidanceValue(15.0, "pct")),
)
ASK = GuidanceStatement(
    page=10, quote="Do we expect to improve to around 21% on net in the next financial year?",
    kind="question", topic="margin", values=(GuidanceValue(21.0, "pct"),),
)


@pytest.fixture()
def store():
    s = FactStore(":memory:")
    yield s
    s.close()


def _summary(**overrides) -> TranscriptSummary:
    base = {"located": True, "call_date": "2025-05-12", "cover_date": "2025-05-16",
                "period": "Q4FY25", "period_basis": "stated", "guidance": (GROWTH, ASK)}
    base.update(overrides)
    return TranscriptSummary(**base)


def test_a_guided_range_becomes_two_citable_facts_with_the_quote_in_the_locator(store):
    result = register_transcript(store, "T", "call.pdf", _summary())
    assert result.period == "Q4FY25"
    assert result.published_at == date(2025, 5, 16)  # the Reg-30 letter's own date
    assert len(result.fact_ids) == 2

    series = store.query_metric_prefix("T", "guidance:", as_of=date(2025, 6, 1))
    assert [f.value for f in series] == [10.0, 15.0]
    assert all(f.grade == "A" and "double digit" in f.locator and "p.16" in f.locator for f in series)


def test_an_analysts_question_is_never_registered_as_guidance(store):
    """The 21% belongs to the analyst who asked it. Storing it would put it in management's mouth."""
    register_transcript(store, "T", "call.pdf", _summary())
    series = store.query_metric_prefix("T", "guidance:", as_of=date(2025, 6, 1))
    assert all("21" not in f.locator for f in series)
    assert all(f.value != 21.0 for f in series)


def test_publication_falls_back_to_the_reg30_deadline_when_no_letter_date(store):
    """Five working days after the call, taken as seven calendar — never earlier than it can be public."""
    result = register_transcript(store, "T", "call.pdf", _summary(cover_date=None))
    assert result.published_at == date(2025, 5, 19)
    # Law 3 through storage: invisible before submission, visible after.
    assert store.query_metric_prefix("T", "guidance:", as_of=date(2025, 5, 18)) == []
    assert len(store.query_metric_prefix("T", "guidance:", as_of=date(2025, 5, 19))) == 2


def test_a_refused_or_undated_transcript_writes_nothing(store):
    refused = TranscriptSummary(located=False, rejected_because="a call announcement is not a transcript")
    assert register_transcript(store, "T", "x.pdf", refused).fact_ids == ()

    undated = _summary(call_date=None, cover_date=None)
    result = register_transcript(store, "T", "y.pdf", undated)
    assert result.fact_ids == ()
    assert "point-in-time" in (result.skipped_because or "")

    unperioded = _summary(period=None, period_basis=None)
    assert "no period" in (register_transcript(store, "T", "z.pdf", unperioded).skipped_because or "")


def test_two_calls_build_a_series_the_single_fact_resolver_would_collapse(store):
    """One quarter carries several guided figures; `query_fact` resolves to one — the prefix query must
    return them all, oldest call first, because drift is only visible as a sequence."""
    register_transcript(store, "T", "h1.pdf", _summary(
        call_date="2024-11-06", cover_date="2024-11-12", period="Q2FY25",
        guidance=(GuidanceStatement(page=9, quote="We expect around 18% growth next year.",
                                    kind="statement", topic="volume_growth",
                                    values=(GuidanceValue(18.0, "pct"),)),),
    ))
    register_transcript(store, "T", "h2.pdf", _summary())

    series = store.query_metric_prefix("T", "guidance:", as_of=date(2025, 6, 1))
    assert [(f.period, f.value) for f in series] == [("Q2FY25", 18.0), ("Q4FY25", 10.0), ("Q4FY25", 15.0)]
