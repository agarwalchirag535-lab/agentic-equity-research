"""Enumerate adverse governance events from the exchange's own announcement register (ADR-0062).

WHY A REGISTER AND NOT A LIST OF NAMES. The golden set's positives decide what "caught it" means, and
picking the frauds one already remembers selects for the famous, the late-stage and the obvious — the
cases any system catches, and the ones whose facts everybody has already absorbed. `docs/GOLDEN_SET.md`
§3 therefore requires enumeration from a register, with every exclusion recorded.

BSE publishes every listed company's Regulation 30 disclosures with a subcategory, a date, the scrip code
and the filed PDF. Querying it market-wide for one subcategory over a window is a COMPLETE enumeration of
that event type for that period: not a sample, not a search, and not a memory.

What it is not: a list of frauds. A statutory auditor resigning mid-term is a strong adverse governance
event and it is what the exchange records; whether the company was misstating anything is a separate
question that only an authority's finding settles. The distinction is carried into the case label
(`adverse` vs `fraud`) rather than blurred here.

Everything is injectable so the enumeration is testable with no network.
"""

from __future__ import annotations

import json
import urllib.parse
from dataclasses import dataclass
from datetime import date
from typing import Callable, Iterable, Sequence

#: BSE's own subcategory names, which are the event vocabulary the exchange publishes. Kept verbatim:
#: paraphrasing them into our own words would make the register unreproducible against the source.
EVENT_SUBCATEGORIES: dict[str, str] = {
    "auditor_resignation": "Resignation of Statutory Auditors",
    "cfo_resignation": "Resignation of Chief Financial Officer (CFO)",
    "ceo_resignation": "Resignation of Chief Executive Officer (CEO)",
}

_ANNOUNCEMENTS = "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
_ATTACHMENT = "https://www.bseindia.com/xml-data/corpfiling/AttachHis/{name}"


@dataclass(frozen=True)
class AdverseEvent:
    """One dated, cited event against one listed company."""

    kind: str
    on: date
    scrip_code: str
    company: str
    headline: str
    source: str

    def as_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "date": self.on.isoformat(), "scrip_code": self.scrip_code,
                "company": self.company, "headline": self.headline, "source": self.source}


def _months(start: date, end: date) -> list[tuple[date, date]]:
    """Month-sized windows. The endpoint returns nothing for a range much wider than a month, and a
    silent empty page would read as 'no events' — which is the one answer this must never invent."""
    out: list[tuple[date, date]] = []
    cursor = date(start.year, start.month, 1)
    while cursor <= end:
        nxt = date(cursor.year + (cursor.month == 12), (cursor.month % 12) + 1, 1)
        out.append((max(cursor, start), min(date.fromordinal(nxt.toordinal() - 1), end)))
        cursor = nxt
    return out


def announcement_url(subcategory: str, window: tuple[date, date], page: int = 1) -> str:
    return (f"{_ANNOUNCEMENTS}?pageno={page}&strCat=Company+Update"
            f"&strPrevDate={window[0]:%Y%m%d}&strScrip=&strSearch=P"
            f"&strToDate={window[1]:%Y%m%d}&strType=C"
            f"&subcategory={urllib.parse.quote(subcategory)}")


def adverse_events(
    start: date,
    end: date,
    *,
    kinds: Sequence[str] = ("auditor_resignation",),
    fetch: Callable[[str], str],
) -> list[AdverseEvent]:
    """Every announcement of the named kinds between `start` and `end`, oldest first.

    Complete for the window, not sampled: the exclusions that follow are recorded by the caller, so a
    candidate that never appears here must be one the exchange never published.
    """
    out: list[AdverseEvent] = []
    for kind in kinds:
        subcategory = EVENT_SUBCATEGORIES[kind]
        for window in _months(start, end):
            rows = json.loads(fetch(announcement_url(subcategory, window))).get("Table", [])
            for row in rows:
                attachment = str(row.get("ATTACHMENTNAME") or "").strip()
                out.append(AdverseEvent(
                    kind=kind,
                    on=date.fromisoformat(str(row["NEWS_DT"])[:10]),
                    scrip_code=str(row.get("SCRIP_CD", "")),
                    company=str(row.get("SLONGNAME", "")).strip(),
                    headline=" ".join(str(row.get("HEADLINE", "")).split())[:200],
                    source=_ATTACHMENT.format(name=attachment) if attachment else "",
                ))
    return sorted(out, key=lambda e: (e.on, e.company))


def deduplicate(events: Iterable[AdverseEvent]) -> list[AdverseEvent]:
    """One event per company per kind, keeping the EARLIEST.

    A company files a corrigendum, or announces the same resignation twice. The golden set cares when the
    market first learned, because that is the date an `as_of` has to precede.
    """
    first: dict[tuple[str, str], AdverseEvent] = {}
    for event in sorted(events, key=lambda e: e.on):
        first.setdefault((event.scrip_code, event.kind), event)
    return sorted(first.values(), key=lambda e: (e.on, e.company))


def fetch_url(url: str) -> str:  # pragma: no cover - thin HTTP wrapper
    """GET a BSE API URL. Separated so `adverse_events` stays offline-testable."""
    import ssl
    import urllib.request

    context: ssl.SSLContext | None = None
    try:
        import certifi

        context = ssl.create_default_context(cafile=certifi.where())
    except ImportError:  # a Python with its own CA bundle
        context = None
    request = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.bseindia.com/",
    })
    with urllib.request.urlopen(request, timeout=30, context=context) as response:
        return response.read().decode("utf-8", "replace")
