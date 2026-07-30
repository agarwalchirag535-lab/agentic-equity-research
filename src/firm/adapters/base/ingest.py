"""Bridge parsed adapter rows into the provenance-carrying fact store (Law 2)."""

from __future__ import annotations

import hashlib
from datetime import date
from typing import Sequence

from firm.adapters.base.interfaces import FinancialRow
from firm.core.facts.store import Document, FactStore


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def ingest_financials(
    store: FactStore,
    rows: Sequence[FinancialRow],
    *,
    doc_id: str,
    source_url: str,
    published_at: date,
    grade: str = "B",
    extractor_version: str = "screener-parser@1.0.0",
    raw_html: str = "",
) -> int:
    """Write a document + one fact per row. Metric is namespaced by statement to avoid collisions.

    ``published_at`` is the fetch date for a current snapshot (honest for as-of=today); pass the true
    filing date when a source exposes it. Returns the number of facts written.
    """
    store.add_document(Document(
        doc_id=doc_id, source_url=source_url, sha256=sha256(raw_html),
        published_at=published_at, fetched_at=published_at, grade=grade,
        extractor_version=extractor_version,
    ))
    for i, r in enumerate(rows):
        store.add_fact(
            fact_id=f"{doc_id}:{i}", doc_id=doc_id, ticker=r.ticker,
            metric=f"{r.statement}:{r.metric}", period=r.period, value=r.value, unit=r.unit,
            locator=f"{r.statement} table",
        )
    return len(rows)
