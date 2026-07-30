"""Provenance-carrying fact store with a point-in-time query layer (Laws 2 & 3).

Law 3 is enforced HERE, at the query layer, not in agents: every read filters
``documents.published_at <= as_of``. No agent can ever see a fact from a document published after the
run's ``as_of`` — that is what makes historical evaluation honest and prevents look-ahead bias.

Law 2: every fact joins to its document for full provenance ``(doc_id, locator, published_at,
extractor_version, grade)``.

Backed by stdlib SQLite so there is no vendor-hosted state (Law 6). Use ``:memory:`` for tests.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    doc_id            TEXT PRIMARY KEY,
    source_url        TEXT NOT NULL,
    sha256            TEXT NOT NULL,
    published_at      TEXT NOT NULL,   -- ISO 'YYYY-MM-DD'; ISO strings sort chronologically
    fetched_at        TEXT NOT NULL,
    grade             TEXT NOT NULL,   -- A/B/C/D (SPEC §4)
    extractor_version TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS facts (
    fact_id   TEXT PRIMARY KEY,
    doc_id    TEXT NOT NULL REFERENCES documents(doc_id),
    ticker    TEXT NOT NULL,
    metric    TEXT NOT NULL,
    period    TEXT NOT NULL,           -- e.g. 'FY24', 'Q1FY25'
    value     REAL NOT NULL,
    unit      TEXT NOT NULL,
    locator   TEXT NOT NULL            -- page/paragraph within the document
);
CREATE INDEX IF NOT EXISTS idx_facts_lookup ON facts(ticker, metric, period);
"""


@dataclass(frozen=True)
class Document:
    doc_id: str
    source_url: str
    sha256: str
    published_at: date
    fetched_at: date
    grade: str
    extractor_version: str


@dataclass(frozen=True)
class Fact:
    """A stored fact with its provenance surfaced (Law 2)."""

    fact_id: str
    doc_id: str
    ticker: str
    metric: str
    period: str
    value: float
    unit: str
    locator: str
    published_at: date
    grade: str
    extractor_version: str


class FactStore:
    def __init__(self, path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "FactStore":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def add_document(self, doc: Document) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO documents VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                doc.doc_id, doc.source_url, doc.sha256, doc.published_at.isoformat(),
                doc.fetched_at.isoformat(), doc.grade, doc.extractor_version,
            ),
        )
        self._conn.commit()

    def add_fact(
        self, fact_id: str, doc_id: str, ticker: str, metric: str, period: str,
        value: float, unit: str, locator: str,
    ) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO facts VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (fact_id, doc_id, ticker, metric, period, value, unit, locator),
        )
        self._conn.commit()

    def _row_to_fact(self, row: sqlite3.Row) -> Fact:
        return Fact(
            fact_id=row["fact_id"], doc_id=row["doc_id"], ticker=row["ticker"],
            metric=row["metric"], period=row["period"], value=row["value"], unit=row["unit"],
            locator=row["locator"], published_at=date.fromisoformat(row["published_at"]),
            grade=row["grade"], extractor_version=row["extractor_version"],
        )

    def query_fact(self, ticker: str, metric: str, period: str, as_of: date) -> Fact | None:
        """Point-in-time read (Law 3): the latest fact for (ticker, metric, period) whose source was
        published on or before ``as_of``. Returns None if nothing was published yet as-of that date.

        A later restatement is invisible until its own ``published_at`` — so a query dated before the
        restatement correctly returns the original figure.
        """
        row = self._conn.execute(
            """
            SELECT f.*, d.published_at, d.grade, d.extractor_version
            FROM facts f JOIN documents d ON f.doc_id = d.doc_id
            WHERE f.ticker = ? AND f.metric = ? AND f.period = ? AND d.published_at <= ?
            ORDER BY d.published_at DESC, f.rowid DESC
            LIMIT 1
            """,
            (ticker, metric, period, as_of.isoformat()),
        ).fetchone()
        return self._row_to_fact(row) if row is not None else None
