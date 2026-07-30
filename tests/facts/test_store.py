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
