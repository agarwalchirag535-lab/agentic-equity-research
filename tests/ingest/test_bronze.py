"""Tests for the immutable bronze archive + resumable backfill (Law 7, ADR-0018). No network."""

from datetime import date

from firm.adapters.base.interfaces import Filing
from firm.core.ingest.bronze import (
    BronzeRecord,
    BronzeStore,
    backfill_filings,
    sha256_bytes,
)

FETCHED = date(2026, 7, 30)


def _filing(doc_id: str, url: str = "https://x/a.pdf", grade: str = "A") -> Filing:
    return Filing(ticker="RELIANCE", doc_id=doc_id, title=f"t-{doc_id}", url=url,
                  published_at=date(2026, 5, 28), source="bse", grade=grade)


def test_put_is_content_addressed_and_immutable(tmp_path):
    store = BronzeStore(tmp_path)
    rec = store.put(_filing("bse:1"), b"PDFBYTES", fetched_at=FETCHED)
    assert rec.sha256 == sha256_bytes(b"PDFBYTES")
    assert store.read_payload(rec) == b"PDFBYTES"
    assert rec.published_at == date(2026, 5, 28)      # exchange date carried through (Law 3)

    # identical content from a second filing -> blob written ONCE, manifest still records both
    rec2 = store.put(_filing("bse:2"), b"PDFBYTES", fetched_at=FETCHED)
    assert rec2.path == rec.path
    blobs = [p for p in tmp_path.rglob("*") if p.is_file() and p.name != "manifest.jsonl"]
    assert len(blobs) == 1
    assert len(store.records()) == 2


def test_records_roundtrip_and_has():
    rec = BronzeRecord(
        doc_id="d", ticker="T", title="ti", source_url="u", published_at=date(2026, 1, 2),
        grade="A", sha256="abc", path="ab/abc", fetched_at=FETCHED,
    )
    assert BronzeRecord.from_json(rec.to_json()) == rec


def test_store_empty_and_has(tmp_path):
    store = BronzeStore(tmp_path)
    assert store.root == tmp_path
    assert store.records() == [] and store.archived_doc_ids() == set()
    assert store.has("nope") is False
    store.put(_filing("bse:1"), b"x", fetched_at=FETCHED)
    assert store.has("bse:1") is True


def test_records_ignores_blank_manifest_lines(tmp_path):
    store = BronzeStore(tmp_path)
    store.put(_filing("bse:1"), b"x", fetched_at=FETCHED)
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(manifest.read_text() + "\n\n")   # trailing blank lines must not break parsing
    assert len(store.records()) == 1


def test_backfill_archives_and_is_idempotent(tmp_path):
    store = BronzeStore(tmp_path)
    calls: list[str] = []

    def fetcher(url: str) -> bytes:
        calls.append(url)
        return b"content-" + url.encode()

    filings = [_filing("bse:1", "https://x/1.pdf"), _filing("bse:2", "https://x/2.pdf")]
    r1 = backfill_filings(store, filings, fetcher, fetched_at=FETCHED)
    assert len(r1.archived) == 2 and r1.complete and len(calls) == 2

    # re-run: everything already archived -> resumable, ZERO refetches
    r2 = backfill_filings(store, filings, fetcher, fetched_at=FETCHED)
    assert r2.archived == [] and r2.skipped_existing == ["bse:1", "bse:2"] and len(calls) == 2


def test_backfill_skips_attachmentless_and_records_failures(tmp_path):
    store = BronzeStore(tmp_path)

    def fetcher(url: str) -> bytes:
        if "boom" in url:
            raise RuntimeError("404 from exchange")
        if "empty" in url:
            return b""
        return b"ok"

    filings = [
        _filing("bse:no-url", url=""),                    # announcement with no attachment
        _filing("bse:boom", "https://x/boom.pdf"),        # fetch error
        _filing("bse:empty", "https://x/empty.pdf"),      # empty payload
        _filing("bse:good", "https://x/good.pdf"),
    ]
    res = backfill_filings(store, filings, fetcher, fetched_at=FETCHED)
    assert res.skipped_no_url == ["bse:no-url"]
    assert [d for d, _ in res.failed] == ["bse:boom", "bse:empty"]
    assert [r.doc_id for r in res.archived] == ["bse:good"]
    assert res.complete is False                          # a gap is VISIBLE, not silent


def test_backfill_throttle_and_limit(tmp_path):
    store = BronzeStore(tmp_path)
    ticks: list[int] = []
    filings = [_filing(f"bse:{i}", f"https://x/{i}.pdf") for i in range(5)]

    res = backfill_filings(
        store, filings, lambda url: b"ok", fetched_at=FETCHED,
        throttle=lambda: ticks.append(1), limit=2,
    )
    assert len(res.archived) == 2 and len(ticks) == 2     # polite: capped fetches, throttled each time

    # the next chunk resumes where the previous stopped
    res2 = backfill_filings(store, filings, lambda url: b"ok", fetched_at=FETCHED, limit=2)
    assert [r.doc_id for r in res2.archived] == ["bse:2", "bse:3"]
