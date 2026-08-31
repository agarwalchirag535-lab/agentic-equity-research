"""ADR-0055: the manifest-driven reading ingest — the CLI path from a filings manifest to verified,
dated facts. Every way a filing can fail to contribute comes back as an explicit status, never a
silent skip."""

from __future__ import annotations

import hashlib
import json
from datetime import date

from firm.core.facts.store import FactStore
from firm.core.ingest.reading import ingest_readings_manifest, write_reading_packets

# A June-closer's one-page P&L, the reading that answers it, and the manifest that pins both.
PAGE = (
    "Statement of Profit and Loss for the year ended 30th June, 2015\n(` in crores)\n"
    "Particulars  Year ended  Year ended\n30th June, 2015  30th June, 2014\n"
    "Revenue from operations  531.61  438.94\n"
    "Profit for the year  110.02  86.99\n"
)
PDF_BYTES = b"%PDF-fake bytes; the injectable extractor supplies the page text"
SHA = hashlib.sha256(PDF_BYTES).hexdigest()

READING = {"statements": [{
    "statement": "pnl", "basis": "standalone", "period": "FY15", "pages": [1],
    "heading_quote": "Statement of Profit and Loss for the year ended 30th June, 2015",
    "unit_quote": "(` in crores)", "unit": "INR_cr",
    "columns": [
        {"period": "FY15", "label_quote": "Year ended\n30th June, 2015"},
        {"period": "FY14", "label_quote": "30th June, 2014"},
    ],
    "figures": [
        {"metric": "pnl:Sales", "period": "FY15", "value_printed": "531.61", "page": 1,
         "row_label": "Revenue from operations"},
        {"metric": "pnl:Net Profit", "period": "FY15", "value_printed": "110.02", "page": 1,
         "row_label": "Profit for the year"},
    ],
}]}


def _manifest(sha: str = SHA) -> dict:
    return {"ticker": "T", "filings": [{
        "file": "T-AR-FY15.pdf", "period": "FY15", "source_url": "https://x/ar15.pdf",
        "published_at": "2015-09-30", "grade": "A", "sha256": sha,
    }]}


def _extract(payload: bytes) -> list[str]:
    assert payload == PDF_BYTES
    return [PAGE]


def _setup(tmp_path, *, reading=READING, pdf: bool = True):
    bronze = tmp_path / "bronze"
    readings = tmp_path / "readings"
    bronze.mkdir()
    readings.mkdir()
    if pdf:
        (bronze / "T-AR-FY15.pdf").write_bytes(PDF_BYTES)
    if reading is not None:
        (readings / "T-AR-FY15.reading.json").write_text(json.dumps(reading))
    return bronze, readings


def test_a_verified_reading_registers_dated_facts(tmp_path):
    bronze, readings = _setup(tmp_path)
    store = FactStore(":memory:")
    (result,) = ingest_readings_manifest(
        store, _manifest(), readings_dir=readings, bronze=bronze,
        as_of=date(2015, 12, 31), extract=_extract)
    assert result.status == "registered" and len(result.fact_ids) == 2
    fact = store.query_fact("T", "pnl:Sales", "FY15", as_of=date(2015, 12, 31))
    assert fact is not None and fact.period_end == date(2015, 6, 30) and fact.grade == "A"


def test_law_3_an_unpublished_filing_is_not_even_opened(tmp_path):
    bronze, readings = _setup(tmp_path)
    store = FactStore(":memory:")

    def _explode(payload):  # noqa: ARG001 - proof the PDF was never extracted
        raise AssertionError("a filing after as_of must not be opened")

    (result,) = ingest_readings_manifest(
        store, _manifest(), readings_dir=readings, bronze=bronze,
        as_of=date(2015, 6, 1), extract=_explode)
    assert result.status == "not_yet_published" and result.fact_ids == ()


def test_a_missing_reading_is_a_named_gap_not_a_silent_skip(tmp_path):
    bronze, readings = _setup(tmp_path, reading=None)
    (result,) = ingest_readings_manifest(
        FactStore(":memory:"), _manifest(), readings_dir=readings, bronze=bronze,
        as_of=date(2015, 12, 31), extract=_extract)
    assert result.status == "no_reading" and "read-packets" in result.detail


def test_bytes_that_fail_the_pinned_hash_are_never_read(tmp_path):
    bronze, readings = _setup(tmp_path)
    (result,) = ingest_readings_manifest(
        FactStore(":memory:"), _manifest(sha="0" * 64), readings_dir=readings, bronze=bronze,
        as_of=date(2015, 12, 31), extract=_extract)
    assert result.status == "pdf_mismatch" and "not the pinned document" in result.detail


def test_a_refused_reading_reports_its_violations_and_stores_nothing(tmp_path):
    bad = json.loads(json.dumps(READING))
    bad["statements"][0]["figures"][0]["value_printed"] = "999.99"   # not on the page
    bronze, readings = _setup(tmp_path, reading=bad)
    store = FactStore(":memory:")
    (result,) = ingest_readings_manifest(
        store, _manifest(), readings_dir=readings, bronze=bronze,
        as_of=date(2015, 12, 31), extract=_extract)
    assert result.status == "refused"
    assert any(v.rule == "V4_value" for v in result.violations)
    assert store.query_fact("T", "pnl:Sales", "FY15", as_of=date(2015, 12, 31)) is None


def test_a_missing_pdf_is_fetched_verified_and_cached(tmp_path):
    bronze, readings = _setup(tmp_path, pdf=False)
    fetched: list[str] = []

    def fetcher(url: str) -> bytes:
        fetched.append(url)
        return PDF_BYTES

    (result,) = ingest_readings_manifest(
        FactStore(":memory:"), _manifest(), readings_dir=readings, bronze=bronze,
        as_of=date(2015, 12, 31), fetcher=fetcher, extract=_extract)
    assert result.status == "registered"
    assert fetched == ["https://x/ar15.pdf"]
    assert (bronze / "T-AR-FY15.pdf").read_bytes() == PDF_BYTES   # fetched once, cached for next time


def test_packets_are_written_only_for_unanswered_filings(tmp_path):
    bronze, readings = _setup(tmp_path)
    out = tmp_path / "packets"
    assert write_reading_packets(_manifest(), bronze=bronze, out_dir=out,
                                 readings_dir=readings, extract=_extract) == []
    (readings / "T-AR-FY15.reading.json").unlink()
    (written,) = write_reading_packets(_manifest(), bronze=bronze, out_dir=out,
                                       readings_dir=readings, extract=_extract)
    text = (out / "T-AR-FY15.reading-packet.md").read_text()
    assert written.endswith("T-AR-FY15.reading-packet.md")
    assert "Revenue from operations" in text and "pnl:Sales" in text   # page text + vocabulary
