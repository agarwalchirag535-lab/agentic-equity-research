"""Discover annual-report PDFs on a listed company's own investor-relations page (ADR-0026).

WHY THIS IS GENERIC AND NOT ABOUT ONE COMPANY
The owner's point: *"the data is publicly available... as like that, you can find data of the publicly listed
company."* Alkyl Amines was an example of a pattern, not a special case. Every Indian listed company must
publish its annual reports under Reg. 46 of the SEBI LODR, on its own website, as PDFs — so the same three
steps work for any of them: read the IR page, recognise the annual reports among the other PDFs, and write a
manifest that records where each came from and when it was published.

WHAT THIS DELIBERATELY DOES NOT DO
It does not download anything. Discovery and retrieval are separated on purpose: fetching tens of megabytes
from a company's servers is an action a human should authorise per company, and a discovery pass that quietly
pulls files would make that impossible. `discover_filings` takes HTML that a caller already has and returns
candidates; the caller decides what to retrieve.

It also does not guess a publication date it cannot evidence. Law 3 turns on `published_at`, so each
candidate carries `published_at_basis`:

  `upload-path`     the publisher's own URL encodes the month (`/wp-content/uploads/2026/06/...`). This is
                    real evidence: the file existed on their server that month.
  `statutory-proxy` the URL month is *earlier than the financial year it reports* or the document was
                    re-uploaded in a later bulk migration, so the URL says nothing useful. Falls back to the
                    statutory AGM deadline (30 September following the FY close), which is the latest date the
                    report can lawfully have appeared — conservative in the right direction for
                    point-in-time work, and labelled so no reader mistakes it for an observation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

#: An annual report, in the wording Indian companies actually use on their IR pages. Deliberately narrow:
#: "Annual Return" (the MGT-7 statutory filing) and "Annual Secretarial Compliance Report" are different
#: documents, and matching them would put non-financial PDFs into the financial manifest.
_ANNUAL_REPORT = re.compile(r"annual[-_\s]*report", re.IGNORECASE)
_NOT_ANNUAL_REPORT = re.compile(r"annual[-_\s]*(return|secretarial)", re.IGNORECASE)
#: `.../uploads/2026/06/...` — the WordPress convention nearly every Indian IR site uses.
_UPLOAD_MONTH = re.compile(r"/(20\d{2})/(0[1-9]|1[0-2])/")
#: "FY-2025-26", "FY 2025-2026", "2016-17", "FY-2024-25" — the year the report covers.
_FY_RANGE = re.compile(r"(20\d{2})\s*[-_]\s*(20\d{2}|\d{2})")
_HREF = re.compile(r'href="([^"]+\.pdf)"', re.IGNORECASE)

#: The IR sections every SEBI-compliant Indian listed company publishes (Reg. 46 LODR). Fetching only the
#: financials page was an error that cost real capability: it hid 28 shareholding patterns, 15 concall
#: transcripts, 12 voting results and the credit ratings, and led to four agents being declared "blocked on
#: data that does not exist" when the data was two clicks away. The rule this encodes: before concluding an
#: input is unavailable, enumerate every section the regulation requires the company to publish.
IR_SECTIONS: tuple[str, ...] = (
    "financials", "corporate-governance", "general-meetings", "announcements",
    "investor-center", "disclosure-reg-46-of-sebi", "financial-trends",
)

#: Document class -> (match, reject). Order matters: the first class whose pattern matches wins, so the
#: specific patterns precede the general ones ("Annual Return" must be tested before "annual report").
DOCUMENT_CLASSES: tuple[tuple[str, re.Pattern[str], re.Pattern[str] | None], ...] = (
    ("annual_return", re.compile(r"annual[-_\s]*return|mgt-?7", re.IGNORECASE), None),
    ("annual_report", re.compile(r"annual[-_\s]*report", re.IGNORECASE),
     re.compile(r"annual[-_\s]*(return|secretarial)", re.IGNORECASE)),
    # The shareholding pattern carries the promoter PLEDGE column, so it satisfies both prerequisites.
    ("shareholding", re.compile(r"shareholding|share[-_\s]*holding|\bshp\b", re.IGNORECASE), None),
    ("transcript", re.compile(r"transcript|con-?call|earnings[-_\s]*call", re.IGNORECASE), None),
    ("credit_rating", re.compile(r"credit[-_\s]*rating", re.IGNORECASE), None),
    ("voting_result", re.compile(r"voting[-_\s]*result|scrutinis|scrutiniz", re.IGNORECASE), None),
    ("presentation", re.compile(r"presentation|investor[-_\s]*deck", re.IGNORECASE), None),
    ("quarterly_result", re.compile(r"result|financial[-_\s]*results", re.IGNORECASE),
     re.compile(r"voting|newspaper", re.IGNORECASE)),
    ("governance", re.compile(r"corporate[-_\s]*governance|board[-_\s]*meet|policy|policies|code[-_\s]*of",
                              re.IGNORECASE), None),
)


@dataclass(frozen=True)
class Document:
    """A discovered primary-source document of any class, not just an annual report."""

    url: str
    doc_class: str
    period: str | None            # 'FY26' where derivable from the link, else None
    suggested_file: str


def classify(url: str) -> str | None:
    """The document class a link belongs to, or None if it is not one the firm reads."""
    for name, match, reject in DOCUMENT_CLASSES:
        if match.search(url) and not (reject and reject.search(url)):
            return name
    return None


def discover_documents(html: str, ticker: str) -> list[Document]:
    """Every recognised primary-source document in an IR page's HTML, de-duplicated by URL.

    Unlike `discover_filings` this does not require a fiscal year: a shareholding pattern for a quarter or a
    credit-rating letter is worth having even when the period has to be read from the document itself. The
    period is recorded when the link states it and left None when it does not — never guessed, because a
    wrongly dated document breaks Law 3 more quietly than a missing one.
    """
    out: dict[str, Document] = {}
    for url in _HREF.findall(html):
        doc_class = classify(url)
        if doc_class is None:
            continue
        fy = _FY_RANGE.search(url)
        period = _fy_from_range(int(fy.group(1)), fy.group(2)) if fy else None
        stem = re.sub(r"[^A-Za-z0-9]+", "-", url.rsplit("/", 1)[-1][:-4]).strip("-")[:60]
        out[url] = Document(
            url=url, doc_class=doc_class, period=period,
            suggested_file=f"{ticker}-{doc_class}-{stem}.pdf",
        )
    return sorted(out.values(), key=lambda d: (d.doc_class, d.period or "", d.url))


@dataclass(frozen=True)
class FilingCandidate:
    """One discovered annual report, with everything the manifest needs and nothing invented."""

    url: str
    period: str                  # 'FY26' — the Indian fiscal year the report covers
    prior_period: str            # 'FY25'
    published_at: date
    published_at_basis: str      # 'upload-path' | 'statutory-proxy'
    suggested_file: str          # a stable local name for the bronze store


def _fy_from_range(start: int, end_token: str) -> str:
    """('2025', '26') -> 'FY26'. The Indian FY is named for the year it ENDS in."""
    end = int(end_token) if len(end_token) == 4 else int(str(start)[:2] + end_token)
    return f"FY{end % 100:02d}"


def _statutory_deadline(period: str) -> date:
    """The last lawful date an FY's annual report can have appeared: 30 September after the 31 March close."""
    year = 2000 + int(period[2:])
    return date(year, 9, 30)


#: A late filer may post a month or two past the AGM deadline; a site migration posts years past it.
_LATE_FILING_GRACE_DAYS = 92


def _plausible_publication(uploaded: date, fy_close: date, deadline: date) -> bool:
    """Whether an upload month can credibly BE this report's publication date.

    Credible means: on or after the financial year closed (a report cannot predate its own period) and no
    later than the AGM deadline plus a grace quarter. Outside that window the URL is recording a bulk
    re-upload, not a publication — on the Alkyl Amines site the FY17-FY21 reports all live under
    `/2022/03/`, five years late for the oldest. Believing it would tell a Phase-6 historical replay that
    the FY17 annual report did not exist until 2022, silently deleting five years of point-in-time evidence.
    """
    grace = date.fromordinal(deadline.toordinal() + _LATE_FILING_GRACE_DAYS)
    return fy_close <= uploaded <= grace


def discover_filings(html: str, ticker: str) -> list[FilingCandidate]:
    """Annual-report candidates found in an IR page's HTML, newest fiscal year first.

    Nothing is fetched and nothing is written. A link is a candidate only if its text names an annual report
    AND a fiscal year can be read off it — a PDF whose year is unknowable cannot be placed in a point-in-time
    series, so it is dropped rather than guessed at.
    """
    seen: dict[str, FilingCandidate] = {}
    for url in _HREF.findall(html):
        if not _ANNUAL_REPORT.search(url) or _NOT_ANNUAL_REPORT.search(url):
            continue
        fy = _FY_RANGE.search(url)
        if fy is None:
            continue
        period = _fy_from_range(int(fy.group(1)), fy.group(2))
        prior = f"FY{(int(period[2:]) - 1) % 100:02d}"

        deadline = _statutory_deadline(period)
        fy_close = date(2000 + int(period[2:]), 3, 31)
        month = _UPLOAD_MONTH.search(url)
        if month is not None and _plausible_publication(
            date(int(month.group(1)), int(month.group(2)), 1), fy_close, deadline
        ):
            published, basis = date(int(month.group(1)), int(month.group(2)), 1), "upload-path"
        else:
            published, basis = deadline, "statutory-proxy"

        candidate = FilingCandidate(
            url=url, period=period, prior_period=prior, published_at=published,
            published_at_basis=basis, suggested_file=f"{ticker}-AR-{period}.pdf",
        )
        # One report per fiscal year; prefer the entry whose date rests on evidence.
        existing = seen.get(period)
        if existing is None or (existing.published_at_basis != "upload-path" and basis == "upload-path"):
            seen[period] = candidate
    return sorted(seen.values(), key=lambda c: c.period, reverse=True)
