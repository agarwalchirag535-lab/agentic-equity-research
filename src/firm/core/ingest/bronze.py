"""Immutable bronze archive + resumable backfill (Law 7 "raw immutable"; ADR-0018).

Why this exists: the exchange archive is the point-in-time spine, but both exchanges change and block
endpoints. Once a filing is archived locally it must never be lost or silently rewritten — so bronze is
**content-addressed and append-only**:

- payload bytes are stored under their SHA-256; identical content is never written twice;
- a JSONL manifest records `(doc_id, sha256, published_at, source_url, grade, fetched_at)` per filing —
  `published_at` is the exchange dissemination date, carried through unchanged (Law 3);
- re-running a backfill **skips what is already archived** (idempotent, resumable after a crash or a
  rate-limit stop), so a partial pull is always safe to repeat;
- a fetch failure is *recorded and skipped*, never fabricated and never fatal: the run reports what it
  could not get so a gap is visible rather than silently absent (ADR-0014).

No network code here — the fetcher is injected (Law 6), which also makes this fully testable offline.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable, Sequence

from firm.adapters.base.interfaces import Filing

# Fetch raw bytes for a URL. Injected so bronze never depends on a transport (Law 6).
BytesFetcher = Callable[[str], bytes]
# Optional politeness hook called before each network fetch (throttle/sleep in production).
Throttle = Callable[[], None]

_MANIFEST = "manifest.jsonl"


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class BronzeRecord:
    """One archived filing. `path` is relative to the bronze root, keyed by content hash."""

    doc_id: str
    ticker: str
    title: str
    source_url: str
    published_at: date
    grade: str
    sha256: str
    path: str
    fetched_at: date

    def to_json(self) -> str:
        return json.dumps({
            "doc_id": self.doc_id, "ticker": self.ticker, "title": self.title,
            "source_url": self.source_url, "published_at": self.published_at.isoformat(),
            "grade": self.grade, "sha256": self.sha256, "path": self.path,
            "fetched_at": self.fetched_at.isoformat(),
        }, sort_keys=True)

    @staticmethod
    def from_json(line: str) -> "BronzeRecord":
        d = json.loads(line)
        return BronzeRecord(
            doc_id=d["doc_id"], ticker=d["ticker"], title=d["title"], source_url=d["source_url"],
            published_at=date.fromisoformat(d["published_at"]), grade=d["grade"],
            sha256=d["sha256"], path=d["path"], fetched_at=date.fromisoformat(d["fetched_at"]),
        )


class BronzeStore:
    """Content-addressed, append-only local archive of raw filings."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._manifest_path = self._root / _MANIFEST

    @property
    def root(self) -> Path:
        return self._root

    def records(self) -> list[BronzeRecord]:
        """Every archived record, in append order. Blank manifest lines are ignored."""
        if not self._manifest_path.exists():
            return []
        return [
            BronzeRecord.from_json(line)
            for line in self._manifest_path.read_text().splitlines()
            if line.strip()
        ]

    def archived_doc_ids(self) -> set[str]:
        return {r.doc_id for r in self.records()}

    def has(self, doc_id: str) -> bool:
        return doc_id in self.archived_doc_ids()

    def read_payload(self, record: BronzeRecord) -> bytes:
        return (self._root / record.path).read_bytes()

    def put(self, filing: Filing, payload: bytes, *, fetched_at: date) -> BronzeRecord:
        """Archive `payload` for `filing`. Content-addressed: identical bytes are written only once.

        Appends a manifest row even when the blob already existed (a second filing may legitimately
        carry identical content); the blob itself is never rewritten, so bronze stays immutable.
        """
        digest = sha256_bytes(payload)
        rel = f"{digest[:2]}/{digest}"
        blob = self._root / rel
        if not blob.exists():
            blob.parent.mkdir(parents=True, exist_ok=True)
            blob.write_bytes(payload)
        record = BronzeRecord(
            doc_id=filing.doc_id, ticker=filing.ticker, title=filing.title,
            source_url=filing.url, published_at=filing.published_at, grade=filing.grade,
            sha256=digest, path=rel, fetched_at=fetched_at,
        )
        with self._manifest_path.open("a") as fh:
            fh.write(record.to_json() + "\n")
        return record


@dataclass(frozen=True)
class BackfillResult:
    """What a backfill run actually did — gaps are reported, never hidden."""

    archived: list[BronzeRecord] = field(default_factory=list)
    skipped_existing: list[str] = field(default_factory=list)   # doc_ids already in bronze
    skipped_no_url: list[str] = field(default_factory=list)      # filing has no attachment
    failed: list[tuple[str, str]] = field(default_factory=list)  # (doc_id, error)

    @property
    def complete(self) -> bool:
        """True when nothing failed. A False here is a visible data gap for the caller to surface."""
        return not self.failed


def backfill_filings(
    store: BronzeStore,
    filings: Sequence[Filing],
    fetcher: BytesFetcher,
    *,
    fetched_at: date,
    throttle: Throttle | None = None,
    limit: int | None = None,
) -> BackfillResult:
    """Archive every filing's payload into bronze — idempotent, resumable, polite.

    Already-archived doc_ids are skipped without a fetch (so re-running after a rate-limit stop resumes
    rather than re-downloads). `throttle` is called before each real fetch. A per-filing failure is
    recorded and the run continues; `limit` caps fetches per run for polite chunked backfills.
    """
    result = BackfillResult()
    existing = store.archived_doc_ids()
    fetched = 0
    for filing in filings:
        if filing.doc_id in existing:
            result.skipped_existing.append(filing.doc_id)
            continue
        if not filing.url:
            result.skipped_no_url.append(filing.doc_id)
            continue
        if limit is not None and fetched >= limit:
            break
        if throttle is not None:
            throttle()
        try:
            payload = fetcher(filing.url)
        except Exception as exc:  # noqa: BLE001 - a source failure must not abort the whole backfill
            result.failed.append((filing.doc_id, str(exc)))
            continue
        fetched += 1
        if not payload:
            result.failed.append((filing.doc_id, "empty payload"))
            continue
        record = store.put(filing, payload, fetched_at=fetched_at)
        existing.add(filing.doc_id)
        result.archived.append(record)
    return result
