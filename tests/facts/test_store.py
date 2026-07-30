"""Fact store tests — including the SPEC §11 Phase 0 point-in-time acceptance scenario."""

from datetime import date

from firm.core.facts.store import Document, FactStore


def _doc(doc_id: str, published: date) -> Document:
    return Document(
        doc_id=doc_id,
        source_url=f"https://example.test/{doc_id}",
        sha256="deadbeef",
        published_at=published,
        fetched_at=published,
        grade="A",
        extractor_version="ar-parser@1.0.0",
    )


def test_phase0_point_in_time_acceptance():
    """'revenue FY24 as-of 2024-08-01' returns the number with provenance; the same query
    as-of 2024-04-01 correctly returns nothing (SPEC §11 Phase 0)."""
    with FactStore() as store:
        store.add_document(_doc("AR-FY24", date(2024, 8, 1)))
        store.add_fact("f1", "AR-FY24", "ACME", "revenue", "FY24", 1234.0, "INR_cr", "p.112")

        got = store.query_fact("ACME", "revenue", "FY24", as_of=date(2024, 8, 1))
        assert got is not None
        assert got.value == 1234.0
        # provenance is surfaced (Law 2)
        assert got.grade == "A"
        assert got.extractor_version == "ar-parser@1.0.0"
        assert got.published_at == date(2024, 8, 1)
        assert got.locator == "p.112"

        # Before the annual report was published, the fact does not exist yet (Law 3).
        assert store.query_fact("ACME", "revenue", "FY24", as_of=date(2024, 4, 1)) is None


def test_restatement_is_invisible_until_published():
    """A later restatement must not leak backwards in time."""
    with FactStore() as store:
        store.add_document(_doc("AR-FY24", date(2024, 8, 1)))
        store.add_fact("f1", "AR-FY24", "ACME", "revenue", "FY24", 1234.0, "INR_cr", "p.112")
        # A restated FY24 figure disclosed almost a year later.
        store.add_document(_doc("AR-FY25", date(2025, 6, 1)))
        store.add_fact("f2", "AR-FY25", "ACME", "revenue", "FY24", 1100.0, "INR_cr", "p.130")

        # As-of a date before the restatement: original figure stands.
        before = store.query_fact("ACME", "revenue", "FY24", as_of=date(2024, 12, 1))
        assert before is not None and before.value == 1234.0

        # As-of a date after the restatement: restated figure wins (latest published <= as_of).
        after = store.query_fact("ACME", "revenue", "FY24", as_of=date(2025, 7, 1))
        assert after is not None and after.value == 1100.0


def test_unknown_metric_returns_none():
    with FactStore() as store:
        store.add_document(_doc("AR-FY24", date(2024, 8, 1)))
        store.add_fact("f1", "AR-FY24", "ACME", "revenue", "FY24", 1234.0, "INR_cr", "p.112")
        assert store.query_fact("ACME", "ebitda", "FY24", as_of=date(2024, 8, 1)) is None


# ------------------------------------------------------------------------------------------------
# Provenance outranks recency (ADR-0029) — found by auditing the build against owner directive 1.


def _graded_doc(store, doc_id, published, grade):
    from firm.core.facts.store import Document

    store.add_document(Document(
        doc_id=doc_id, source_url=f"https://example.test/{doc_id}", sha256="0" * 8,
        published_at=published, fetched_at=published, grade=grade,
        extractor_version="test@1.0.0",
    ))


def test_an_audited_filing_outranks_a_fresher_screener_snapshot(store):
    """The real defect: recency alone let an aggregator override the audited figure.

    ALKYLAMINE FY26 revenue resolved to the screener's 1536.00 rather than the filing's 1535.86, because the
    snapshot was taken after the annual report was published. Owner directive 1 says the filing is the source
    of record.
    """
    _graded_doc(store, "AR-FY26", date(2026, 6, 1), "A")
    _graded_doc(store, "screener", date(2026, 7, 23), "B")
    store.add_fact("AR-FY26:sales", "AR-FY26", "T", "pnl:Sales", "FY26", 1535.86, "INR_cr", "p.13 l.14")
    store.add_fact("screener:sales", "screener", "T", "pnl:Sales", "FY26", 1536.0, "INR_cr", "pnl table")

    fact = store.query_fact("T", "pnl:Sales", "FY26", as_of=date(2026, 7, 30))
    assert fact is not None
    assert fact.grade == "A"
    assert fact.value == 1535.86


def test_law_3_still_wins_over_grade(store):
    """A grade-A filing published after `as_of` must stay invisible — provenance never defeats Law 3."""
    _graded_doc(store, "AR-FY26", date(2026, 6, 1), "A")
    _graded_doc(store, "screener", date(2026, 4, 1), "B")
    store.add_fact("AR-FY26:sales", "AR-FY26", "T", "pnl:Sales", "FY26", 1535.86, "INR_cr", "p.13")
    store.add_fact("screener:sales", "screener", "T", "pnl:Sales", "FY26", 1536.0, "INR_cr", "table")

    earlier = store.query_fact("T", "pnl:Sales", "FY26", as_of=date(2026, 5, 1))
    assert earlier is not None and earlier.grade == "B"    # the AR does not exist yet on that date


def test_a_restatement_still_wins_within_its_own_grade(store):
    """Two audited filings, the later correcting the earlier: the correction must be returned."""
    _graded_doc(store, "AR-FY26", date(2026, 6, 1), "A")
    _graded_doc(store, "AR-FY27", date(2027, 6, 1), "A")
    store.add_fact("AR-FY26:sales", "AR-FY26", "T", "pnl:Sales", "FY26", 1535.86, "INR_cr", "p.13")
    store.add_fact("AR-FY27:sales", "AR-FY27", "T", "pnl:Sales", "FY26", 1530.00, "INR_cr", "p.14 comp")

    assert store.query_fact("T", "pnl:Sales", "FY26", as_of=date(2027, 7, 1)).value == 1530.00
    # and before the restatement was published, the original still stands
    assert store.query_fact("T", "pnl:Sales", "FY26", as_of=date(2026, 12, 1)).value == 1535.86
