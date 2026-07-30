"""Tests for the BSE archive adapter — parsers run against REAL saved API responses (fixtures fetched
live from api.bseindia.com on 2026-07-30), so the schema under test is the schema in production."""

import json
from datetime import date
from pathlib import Path

import pytest

from firm.adapters.base.interfaces import Filing, FilingsSource
from firm.adapters.india.exchange import (
    BseFilingsSource,
    attachment_url,
    filter_by_window,
    parse_announcements,
    parse_annual_reports,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
ANNOUNCEMENTS = json.loads((FIXTURES / "bse_announcements_reliance.json").read_text())
ANNUAL_REPORTS = json.loads((FIXTURES / "bse_annual_reports_reliance.json").read_text())


# ---- announcements parser -----------------------------------------------------------------------
def test_parse_announcements_real_fixture():
    rows = parse_announcements(ANNOUNCEMENTS)
    assert len(rows) == 50                                     # full page parsed
    first = rows[0]
    assert first.ticker == "500325"
    assert first.doc_id.startswith("bse:")
    assert first.grade == "B"                                  # exchange filing
    assert first.published_at == date(2026, 7, 25)             # NEWS_DT, not fetch date (Law 3)
    assert first.url.startswith("https://www.bseindia.com/xml-data/corpfiling/AttachHis/")


def test_parse_announcements_drops_undated_keeps_unattached():
    payload = {"Table": [
        {"NEWSID": "x", "SCRIP_CD": 1, "NEWSSUB": "undated", "NEWS_DT": "", "ATTACHMENTNAME": "a.pdf"},
        {"NEWSID": "y", "SCRIP_CD": 1, "NEWSSUB": "no pdf", "NEWS_DT": "2026-01-05T10:00:00",
         "ATTACHMENTNAME": ""},
    ]}
    rows = parse_announcements(payload)
    assert len(rows) == 1                                      # undated dropped — can't be point-in-time
    assert rows[0].title == "no pdf" and rows[0].url == ""     # attachment-less kept, url empty


def test_parse_announcements_empty_payload():
    assert parse_announcements({}) == []


# ---- annual-report parser -----------------------------------------------------------------------
def test_parse_annual_reports_real_fixture():
    # Real archive depth (verified 2026-07-30): BSE LISTS 1997-2026 but rows before 2012 carry no
    # authorise date and/or no PDF link — the parser rightly drops them (an AR we cannot date or fetch
    # is not archive material). Dated, downloadable depth = 2012-2026 = 15 years > the 10-yr target.
    rows = parse_annual_reports(ANNUAL_REPORTS)
    years = {r.doc_id.rsplit(":", 1)[1] for r in rows}
    assert "2026" in years and "2012" in years
    assert "1997" not in years                                 # listed by BSE, but undated/linkless
    assert len(rows) == 15
    for r in rows:
        assert r.grade == "A"                                  # audited filing
        assert r.url.startswith("https://")
        assert isinstance(r.published_at, date)


def test_parse_annual_reports_drops_undated_or_linkless():
    payload = {"Table": [
        {"Scripcode": "1", "Year": "2020", "Fld_AuthoriseDate": "", "PDFDownload": "https://x/y.pdf"},
        {"Scripcode": "1", "Year": "2021", "Fld_AuthoriseDate": "2021-08-07T11:00:00", "PDFDownload": ""},
    ]}
    assert parse_annual_reports(payload) == []


# ---- helpers ------------------------------------------------------------------------------------
def test_attachment_url():
    assert attachment_url("abc.pdf") == "https://www.bseindia.com/xml-data/corpfiling/AttachHis/abc.pdf"


def test_filter_by_window():
    rows = parse_announcements(ANNOUNCEMENTS)
    july = filter_by_window(rows, date(2026, 7, 1), date(2026, 7, 31))
    assert july and all(date(2026, 7, 1) <= f.published_at <= date(2026, 7, 31) for f in july)
    assert july == sorted(july, key=lambda f: f.published_at, reverse=True)   # newest first


# ---- the FilingsSource implementation -----------------------------------------------------------
def _fake_fetcher(url: str) -> str:
    if "AnnualReport_New" in url:
        return json.dumps(ANNUAL_REPORTS)
    return json.dumps(ANNOUNCEMENTS)


def test_bse_filings_source_conforms_and_rekeys_ticker():
    src = BseFilingsSource({"RELIANCE": "500325"}, fetcher=_fake_fetcher)
    assert isinstance(src, FilingsSource)                      # protocol conformance (Law 6)
    rows = src.filings("RELIANCE", since=date(2020, 1, 1))
    assert rows and all(isinstance(f, Filing) for f in rows)
    assert all(f.ticker == "RELIANCE" for f in rows)           # scrip code never leaks downstream
    assert all(f.published_at >= date(2020, 1, 1) for f in rows)
    grades = {f.grade for f in rows}
    assert grades == {"A", "B"}                                # ARs (A) + announcements (B) merged
    assert rows == sorted(rows, key=lambda f: f.published_at, reverse=True)


def test_bse_filings_source_unknown_ticker_raises():
    src = BseFilingsSource({}, fetcher=_fake_fetcher)
    with pytest.raises(KeyError):
        src.filings("UNKNOWN", since=date(2020, 1, 1))
