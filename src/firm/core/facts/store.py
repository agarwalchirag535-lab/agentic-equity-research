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
from typing import Sequence

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
    locator   TEXT NOT NULL,           -- page/paragraph within the document
    -- ISO date the period ENDS, when the source stated it; '' when it did not. A period label is not a
    -- period (ADR-0048/0049): Symphony reports June year-ends until FY15 and March after, so `FY15`
    -- means 30-Jun-2015 for that company and 31-Mar-2015 for most others. Growth across a year-end
    -- change compares windows that do not line up, and nothing could see it before this column.
    period_end TEXT NOT NULL DEFAULT ''
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
    #: ISO date the period ends, or '' when the source did not state it. Never inferred from the label:
    #: inferring a March close is exactly the assumption this field exists to stop making.
    period_end: str = ""


class FactStore:
    def __init__(self, path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(_SCHEMA)
        # A store written before period_end existed is still readable; the column arrives empty, which
        # is the honest value for a fact whose source never stated its period end.
        if "period_end" not in {r["name"] for r in self._conn.execute("PRAGMA table_info(facts)")}:
            self._conn.execute("ALTER TABLE facts ADD COLUMN period_end TEXT NOT NULL DEFAULT ''")
            self._conn.commit()

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
        value: float, unit: str, locator: str, period_end: str = "",
    ) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO facts "
            "(fact_id, doc_id, ticker, metric, period, value, unit, locator, period_end) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (fact_id, doc_id, ticker, metric, period, value, unit, locator, period_end),
        )
        self._conn.commit()

    def remove_facts(self, fact_ids: Sequence[str]) -> int:
        """Delete facts by id, returning how many rows went. Used only to QUARANTINE a figure two
        independent documents contradict each other about (`crosscheck_overlaps`).

        Deleting from a fact store is not something to do casually, so the one caller is narrow by
        design: it removes a figure that cannot be true rather than leaving a wrong number in place with
        a grade-A stamp on it. The gap that remains is visible; the wrong number would not have been.
        """
        if not fact_ids:
            return 0
        cursor = self._conn.execute(
            f"DELETE FROM facts WHERE fact_id IN ({','.join('?' * len(fact_ids))})", tuple(fact_ids))
        self._conn.commit()
        return int(cursor.rowcount)

    def _row_to_fact(self, row: sqlite3.Row) -> Fact:
        return Fact(
            fact_id=row["fact_id"], doc_id=row["doc_id"], ticker=row["ticker"],
            metric=row["metric"], period=row["period"], value=row["value"], unit=row["unit"],
            locator=row["locator"], published_at=date.fromisoformat(row["published_at"]),
            grade=row["grade"], extractor_version=row["extractor_version"],
            period_end=(row["period_end"] if "period_end" in row.keys() else ""),
        )

    def query_fact(self, ticker: str, metric: str, period: str, as_of: date) -> Fact | None:
        """Point-in-time read (Law 3): the BEST-SOURCED fact for (ticker, metric, period) published on or
        before ``as_of``. Returns None if nothing was published yet as-of that date.

        Resolution order is `(grade, published_at DESC)` — best grade first, most recent within a grade.
        Grade leads deliberately, and this was a real defect until 2026-07-30: ordering by recency alone let a
        screener snapshot taken today outrank the audited annual report published last month, so ALKYLAMINE's
        FY26 revenue resolved to the aggregator's ₹1,536cr instead of the filing's ₹1,535.86cr. Ten annual
        reports were being ingested and the published report still quoted the aggregator wherever both sources
        carried a row — `fact_citations` held zero grade-A entries. Owner directive 1 is explicit that the
        audited filing is the source of record and screener.in is a grade-B cross-check, so provenance has to
        outrank recency.

        Two behaviours preserved on purpose:

        * **Law 3 is untouched.** The `published_at <= as_of` filter still runs first, so nothing a source
          published after the query date can be seen at any grade.
        * **A restatement still wins within its own grade.** When a later annual report corrects an earlier
          one, both are grade A and the more recent publication is returned. What no longer happens is a
          *lower-grade* source overriding an audited figure merely by being fresher.
        """
        row = self._conn.execute(
            """
            SELECT f.*, d.published_at, d.grade, d.extractor_version
            FROM facts f JOIN documents d ON f.doc_id = d.doc_id
            WHERE f.ticker = ? AND f.metric = ? AND f.period = ? AND d.published_at <= ?
            ORDER BY d.grade ASC, d.published_at DESC, f.rowid DESC
            LIMIT 1
            """,
            (ticker, metric, period, as_of.isoformat()),
        ).fetchone()
        return self._row_to_fact(row) if row is not None else None

    def facts_for(self, ticker: str, metric: str, period: str) -> list[Fact]:
        """EVERY stored fact for (ticker, metric, period), oldest source first — not point-in-time.

        Deliberately unfiltered by `as_of`, because its purpose is the opposite of `query_fact`'s: comparing
        what *different documents* assert about the same year. Two annual reports overlap by one year (the
        later one's comparative column restates the earlier one's reported figure), and where they disagree
        either the company restated or an extractor misread — both findings. Use `query_fact` for anything
        a report relies on; use this only to audit the sources against each other (ADR-0024).
        """
        rows = self._conn.execute(
            """
            SELECT f.*, d.published_at, d.grade, d.extractor_version
            FROM facts f JOIN documents d ON f.doc_id = d.doc_id
            WHERE f.ticker = ? AND f.metric = ? AND f.period = ?
            ORDER BY d.published_at ASC, f.rowid ASC
            """,
            (ticker, metric, period),
        ).fetchall()
        return [self._row_to_fact(row) for row in rows]

    def query_metric_prefix(self, ticker: str, prefix: str, as_of: date) -> list[Fact]:
        """Point-in-time read (Law 3) of EVERY fact whose metric starts with ``prefix``.

        `query_fact` resolves (metric, period) to a single best fact, which is right for a balance-sheet
        row and wrong for guidance: one call quarter carries several guided figures ("Rs. 150 crores
        capex", "10% to 15% growth"), each its own fact under the same metric label. This returns them
        all, oldest quarter first, so a reader sees guidance as the time series it is. The
        `published_at <= as_of` filter is identical to `query_fact`'s — Law 3 lives here, never at the
        agent layer.
        """
        rows = self._conn.execute(
            """
            SELECT f.*, d.published_at, d.grade, d.extractor_version
            FROM facts f JOIN documents d ON f.doc_id = d.doc_id
            WHERE f.ticker = ? AND f.metric LIKE ? || '%' AND d.published_at <= ?
            ORDER BY d.published_at ASC, f.rowid ASC
            """,
            (ticker, prefix, as_of.isoformat()),
        ).fetchall()
        return [self._row_to_fact(row) for row in rows]
