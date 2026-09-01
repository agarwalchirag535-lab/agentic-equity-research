"""BSE archive adapter — the point-in-time filings spine (ADR-0018, owner decision closing PLAN OQ#1).

Why this source: the exchange archive carries the **dissemination timestamp** for every filing
(`NEWS_DT`/`DissemDT`) and per-year annual-report PDFs going back decades (verified live: RELIANCE
1997–2026). That timestamp is the honest `published_at` Law 3 needs — a fetch date never is.

Endpoints (verified live 2026-07-30; real responses saved as `tests/fixtures/bse_*.json`):
- announcements: `api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w?...&strScrip=<code>...`
- annual reports: `api.bseindia.com/BseIndiaAPI/api/AnnualReport_New/w?scripcode=<code>`
- attachments:   `www.bseindia.com/xml-data/corpfiling/AttachHis/<name>` (200 for live + historical)

Design (Law 6 + ADR-0009 pattern): pure parsers tested against saved fixtures; the live fetcher is
injectable so nothing here needs the network under test. Grades: an announcement row = **B** (exchange
filing); the audited annual report = **A**. NSE mirrors the same filings; it aggressively blocks
non-browser clients (ADR-0009), so BSE is the implemented archive and NSE stays a manual fallback.
Bulk backfill must be polite: throttle, cache to bronze (immutable, SHA-256), resume.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from datetime import date
from typing import Any

from firm.adapters.base.interfaces import Filing

_ANNOUNCEMENTS_URL = (
    "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
    "?pageno={page}&strCat=-1&strPrevDate={start:%Y%m%d}&strScrip={scrip}"
    "&strSearch=P&strToDate={end:%Y%m%d}&strType=C&subcategory=-1"
)
_ANNUAL_REPORTS_URL = "https://api.bseindia.com/BseIndiaAPI/api/AnnualReport_New/w?scripcode={scrip}"
_ATTACH_URL = "https://www.bseindia.com/xml-data/corpfiling/AttachHis/{name}"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer": "https://www.bseindia.com/",
    "Accept": "application/json",
}

# A fetcher takes a URL and returns the response body as text. Injectable for offline tests.
Fetcher = Callable[[str], str]


def attachment_url(attachment_name: str) -> str:
    """Public URL of a filing's PDF attachment (AttachHis serves both live and historical)."""
    return _ATTACH_URL.format(name=attachment_name)


def _iso_date(value: str) -> date:
    """'2026-07-25T14:37:43.477' → date(2026, 7, 25). Raises on malformed input (no silent guess)."""
    return date.fromisoformat(value[:10])


def parse_announcements(payload: dict[str, Any], *, source: str = "bse") -> list[Filing]:
    """Parse the announcements JSON into `Filing` rows.

    `published_at` = the exchange dissemination timestamp (`NEWS_DT`) — never the fetch date (Law 3).
    Rows without a PDF attachment keep `url=""` (the event still happened; callers filter as needed).
    Rows without a NEWS_DT are dropped: an undated filing cannot enter a point-in-time store.
    """
    filings: list[Filing] = []
    for row in payload.get("Table", []):
        news_dt = row.get("NEWS_DT") or ""
        if not news_dt:
            continue
        attachment = (row.get("ATTACHMENTNAME") or "").strip()
        filings.append(Filing(
            ticker=str(row.get("SCRIP_CD", "")),
            doc_id=f"bse:{row.get('NEWSID', '')}",
            title=(row.get("NEWSSUB") or row.get("HEADLINE") or "").strip(),
            url=attachment_url(attachment) if attachment else "",
            published_at=_iso_date(news_dt),
            source=source,
            grade="B",   # exchange filing (SPEC §4)
        ))
    return filings


def parse_annual_reports(payload: dict[str, Any], *, source: str = "bse") -> list[Filing]:
    """Parse the annual-report archive JSON into grade-A `Filing` rows (one per fiscal year).

    `published_at` = `Fld_AuthoriseDate` (when BSE authorised/hosted the AR). Rows without an authorise
    date or a PDF link are dropped — an AR we cannot date or fetch is not archive material.
    """
    filings: list[Filing] = []
    for row in payload.get("Table", []):
        authorised = (row.get("Fld_AuthoriseDate") or "").strip()
        pdf = (row.get("PDFDownload") or "").strip()
        if not authorised or not pdf:
            continue
        filings.append(Filing(
            ticker=str(row.get("Scripcode", "")),
            doc_id=f"bse:ar:{row.get('Scripcode', '')}:{row.get('Year', '')}",
            title=f"Annual Report {row.get('Year', '')} — {row.get('scrip_name', '')}".strip(),
            url=pdf,
            published_at=_iso_date(authorised),
            source=source,
            grade="A",   # audited filing (SPEC §4)
        ))
    return filings


def _default_fetcher(url: str) -> str:  # pragma: no cover - thin network wrapper
    import ssl
    import urllib.request

    try:
        import certifi

        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
        return resp.read().decode("utf-8")


class BseFilingsSource:
    """`FilingsSource` implementation over the BSE archive (announcements + annual reports).

    `scrip_of` maps the firm's ticker to a BSE scrip code (e.g. RELIANCE → 500325); the mapping lives
    with the caller/config, not here. The fetcher is injectable — tests pass fixture-backed fakes.
    """

    name = "bse"

    def __init__(self, scrip_of: dict[str, str], fetcher: Fetcher = _default_fetcher) -> None:
        self._scrip_of = scrip_of
        self._fetch = fetcher

    def filings(self, ticker: str, since: date) -> list[Filing]:
        """Announcements from `since` to today, plus every archived annual report from `since`."""
        scrip = self._scrip_of.get(ticker)
        if scrip is None:
            raise KeyError(f"no BSE scrip code configured for ticker {ticker!r}")
        ann_url = _ANNOUNCEMENTS_URL.format(page=1, start=since, scrip=scrip, end=date.today())
        announcements = parse_announcements(json.loads(self._fetch(ann_url)))
        annual = parse_annual_reports(json.loads(self._fetch(_ANNUAL_REPORTS_URL.format(scrip=scrip))))
        rows = [f for f in announcements + annual if f.published_at >= since]
        # Re-key to the firm's ticker so downstream never sees raw scrip codes.
        return [Filing(ticker=ticker, doc_id=f.doc_id, title=f.title, url=f.url,
                       published_at=f.published_at, source=f.source, grade=f.grade)
                for f in sorted(rows, key=lambda f: f.published_at, reverse=True)]


def filter_by_window(filings: Sequence[Filing], start: date, end: date) -> list[Filing]:
    """Point-in-time helper: filings published within [start, end], newest first."""
    return sorted(
        (f for f in filings if start <= f.published_at <= end),
        key=lambda f: f.published_at,
        reverse=True,
    )
