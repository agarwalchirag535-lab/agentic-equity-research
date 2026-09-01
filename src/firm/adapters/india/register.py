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

#: BSE's own (category, subcategory) names — the event vocabulary the exchange publishes. Kept
#: VERBATIM, whitespace included: the API's subcategory filter is an exact match against the parent
#: category ("strCat=-1" with a subcategory returns nothing), and the CIRP subcategory really does
#: carry a double space before "(CIRP)". Paraphrasing any of these into our own words — or our own
#: typography — would make the register silently return zero events and read as "nothing happened"
#: (the ADR-0060 orthography lesson, on the enumeration side).
EVENT_SUBCATEGORIES: dict[str, tuple[str, str]] = {
    "auditor_resignation": ("Company Update", "Resignation of Statutory Auditors"),
    "cfo_resignation": ("Company Update", "Resignation of Chief Financial Officer (CFO)"),
    "ceo_resignation": ("Company Update", "Resignation of Chief Executive Officer (CEO)"),
    # The high-yield adverse streams (ADR-0061). An auditor resignation needs its letter read — 1 in 20
    # is genuinely adverse — but a company disclosing its own payment default, or filing CIRP updates,
    # has SELF-DECLARED the qualifying event; the reading step confirms rather than classifies.
    "loan_default": ("Others",
                     ("Disclosures by listed entities of defaults on payment of interest/ repayment of "
                      "principal amount for loans including revolving facilities like cash credit from "
                      "banks / financial institutions.")),
    "debt_security_default": ("Others",
                              ("Disclosures by listed entities of defaults on payment of interest/ "
                               "repayment of principal amount for unlisted debt securities i.e. NCDs "
                               "and NCRPS.")),
    "cirp_update": ("Company Update",
                    "Updates - Corporate Insolvency Resolution Process  (CIRP)"),
    "coc_meeting": ("Company Update", "Intimation of meeting of Committee of Creditors"),
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


def announcement_url(subcategory: str, window: tuple[date, date], page: int = 1,
                     category: str = "Company Update") -> str:
    return (f"{_ANNOUNCEMENTS}?pageno={page}&strCat={urllib.parse.quote(category)}"
            f"&strPrevDate={window[0]:%Y%m%d}&strScrip=&strSearch=P"
            f"&strToDate={window[1]:%Y%m%d}&strType=C"
            f"&subcategory={urllib.parse.quote(subcategory)}")


def adverse_events(
    start: date,
    end: date,
    *,
    kinds: Sequence[str] = ("auditor_resignation",),
    fetch: Callable[[str], str],
    passes: int = 1,
) -> list[AdverseEvent]:
    """Every announcement of the named kinds between `start` and `end`, oldest first.

    Complete for the window, not sampled: the exclusions that follow are recorded by the caller, so a
    candidate that never appears here must be one the exchange never published.

    `passes` re-runs the whole enumeration and UNIONS the rows. Measured live (ADR-0061): under a
    sustained request stream the BSE endpoint returns PARTIAL pages with no error — a 39-window sweep
    saw 3 of October 2021's 10 default disclosures, and the same window queried alone returned all 10,
    three times in a row. A silent partial is worse than a failure because it reads as "no events".
    One pass is a sample; two agreeing passes are an enumeration.
    """
    merged: dict[tuple[str, str, date, str], AdverseEvent] = {}
    for _ in range(max(1, passes)):
        for event in _enumerate_once(start, end, kinds=kinds, fetch=fetch):
            merged.setdefault((event.kind, event.scrip_code, event.on, event.source), event)
    return sorted(merged.values(), key=lambda e: (e.on, e.company))


def _enumerate_once(
    start: date,
    end: date,
    *,
    kinds: Sequence[str],
    fetch: Callable[[str], str],
) -> list[AdverseEvent]:
    out: list[AdverseEvent] = []
    for kind in kinds:
        category, subcategory = EVENT_SUBCATEGORIES[kind]
        for window in _months(start, end):
            # Page until a PARTIAL page: the endpoint serves 50 rows per page, and stopping at page 1
            # sampled the busy months while claiming to enumerate them — auditor resignations fit in
            # one page per month, market-wide default disclosures do not. A page shorter than 50 is
            # the last one; the cap is a runaway guard, far above any observed month.
            for page in range(1, 201):
                rows = json.loads(fetch(
                    announcement_url(subcategory, window, page=page, category=category))).get("Table", [])
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
                if len(rows) < 50:
                    break
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
    """GET a BSE API URL, with a short retry. Separated so `adverse_events` stays offline-testable.

    The retry is not politeness, it is correctness: a multi-kind enumeration is hundreds of requests,
    one transient timeout used to abort the whole run with nothing written, and an enumeration that
    dies mid-window is worse than none — the caller cannot tell "no events" from "gave up".
    """
    import ssl
    import time
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
    last: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=30, context=context) as response:
                return response.read().decode("utf-8", "replace")
        except (TimeoutError, OSError) as exc:
            last = exc
            time.sleep(2.0 * (attempt + 1))
    raise last if last is not None else RuntimeError(f"unreachable: {url}")


def market_cap_cr(scrip_code: str, fetch: Callable[[str], str]) -> float | None:
    """Today's market cap in ₹ crore from the exchange's peer-group row: LTP × shares outstanding
    (equity capital / face value). None when the exchange reports no tradable equity — suspended,
    delisted, or debt-only.

    KNOWN BIAS, recorded rather than hidden (ADR-0061): this is TODAY's cap, and the golden set's
    question is whether the company was in-universe AT `as_of` — before the event. A company that
    collapsed 95% after its event reads below the floor today while it was squarely in-universe when
    the firm would have been looking. Triage on this number therefore excludes the hardest-hit true
    positives; a floor exclusion from today's cap is a PROVISIONAL exclusion, and the historical cap
    is the input that would make it a real one.
    """
    url = f"https://api.bseindia.com/BseIndiaAPI/api/EQPeerGp/w?scripcode={scrip_code}&scripcomare="
    try:
        rows = json.loads(fetch(url)).get("Table", [])
    except (ValueError, KeyError):
        return None
    for row in rows:
        if str(row.get("scrip_cd", "")) == str(scrip_code):
            try:
                ltp, equity, face = float(row["LTP"]), float(row["Equity"]), float(row["FACE_VALUE"])
            except (KeyError, TypeError, ValueError):
                return None
            if ltp <= 0 or equity <= 0 or face <= 0:
                return None
            return ltp * equity / face
    return None


def triage(
    events: Sequence[AdverseEvent],
    mcap_of: Callable[[str], float | None],
    *,
    floor_cr: float,
    ceiling_cr: float,
) -> tuple[list[dict], list[dict]]:
    """Split enumerated events into golden-set candidates and recorded exclusions by the mcap band.

    ONLY the band is applied here. The universe's other exclusions (NCLT, suspension) are for the
    investable screen — for the golden set a company under CIRP is not an exclusion, it is the label.
    Every exclusion carries its reason (docs/GOLDEN_SET.md §3: a selection whose rejections are
    invisible cannot be audited for bias).
    """
    candidates: list[dict] = []
    excluded: list[dict] = []
    caps: dict[str, float | None] = {}
    for event in events:
        if event.scrip_code not in caps:
            caps[event.scrip_code] = mcap_of(event.scrip_code)
        cap = caps[event.scrip_code]
        row = {**event.as_dict(), "mcap_cr_today": round(cap, 2) if cap is not None else None}
        if cap is None:
            excluded.append({**row, "exclusion":
                             "no market cap reported — suspended, delisted or not equity-traded"})
        elif cap < floor_cr:
            excluded.append({**row, "exclusion":
                             f"market cap Rs {cap:,.0f}cr below the universe floor of Rs {floor_cr:,.0f}cr "
                             "(TODAY'S cap — provisional for a collapsed company, see market_cap_cr)"})
        elif cap > ceiling_cr:
            excluded.append({**row, "exclusion":
                             f"market cap Rs {cap:,.0f}cr above the universe ceiling of Rs {ceiling_cr:,.0f}cr"})
        else:
            candidates.append(row)
    return candidates, excluded
