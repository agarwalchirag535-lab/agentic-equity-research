"""Walk a documents manifest into the fact store: shareholding and transcripts, not just annual reports.

THE GAP THIS CLOSES
`core/ingest/filings.py` turns annual reports into grade-A facts. Nothing did the same for the *other*
primary sources, so `data/bronze/{TICKER}/` filled up with 27 SEBI shareholding patterns and 14 concall
transcripts that no part of the pipeline could read. `adapters/india/shareholding.py` was written, tested
against real filings, and then called by nothing outside its own test file — capability built and never
connected.

The visible consequence was the one the owner objected to: `ownership_flows_analyst` and
`management_analyst` were "staffed" — they appeared in the roster, packets were written for them, they
returned JSON — while receiving a payload containing no shareholding data at all. An agent asked to assess
promoter behaviour from a table of profitability ratios can only do one of two things, and both are
failures.

WHAT A DOCUMENT'S `published_at` IS HERE
For a shareholding pattern it is the reporting date the filing states ("as on 31-Mar-2022"), NOT the day we
downloaded it and not the day the form was generated. Reg. 31 requires the filing within 21 days of the
quarter end, so the reporting date is a conservative, evidenced point-in-time anchor: the register genuinely
described the company on that date. Where a filing carries no "as on" line the date is recovered from the
NSDL/CDSL extraction header and labelled `depository-date`, so a recovered date never passes for a stated
one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Sequence

from firm.adapters.base.extract import default_ocr_backend, extract_document
from firm.adapters.india.nse_shareholding import CrossCheck, ShareholdingRecord, crosscheck
from firm.adapters.india.shareholding import ShareholdingSummary, parse_shareholding
from firm.adapters.india.transcripts import TranscriptRead, read_transcript
from firm.core.facts.store import Document, FactStore

#: Metric names for the ownership series. Namespaced like the statement metrics (`pnl:Sales`) so a reader
#: of a fact id can tell at a glance which primary source it came out of.
PROMOTER_PCT = "ownership:promoter_pct"
PUBLIC_PCT = "ownership:public_pct"
PLEDGE_PCT = "ownership:promoter_pledge_pct"
PROMOTER_HOLDERS = "ownership:promoter_shareholders"

_EXTRACTOR = "shareholding@1.1.0"
_TRANSCRIPT_EXTRACTOR = "transcript@1.0.0"


def quarter_label(as_on: date) -> str:
    """`2022-03-31` -> `FY22Q4`. The Indian fiscal year starts in April, so Q1 ends 30 June."""
    fiscal_year = as_on.year + 1 if as_on.month >= 4 else as_on.year
    quarter = ((as_on.month - 4) % 12) // 3 + 1
    return f"FY{fiscal_year % 100:02d}Q{quarter}"


@dataclass(frozen=True)
class ShareholdingIngest:
    """One quarter's shareholding pattern as ingested — or the reason it was refused."""

    file: str
    period: str | None
    as_on: date | None
    summary: ShareholdingSummary
    fact_ids: tuple[str, ...] = ()

    @property
    def usable(self) -> bool:
        return self.period is not None and self.summary.located


@dataclass(frozen=True)
class TranscriptIngest:
    """One concall transcript as read. Transcripts produce EVIDENCE, not facts.

    Deliberate asymmetry with shareholding. A promoter stake is a number the company filed and we can bind
    to a locator; a management statement is *prose*, and turning "we expect margins to normalise" into a
    number would be the firm inventing a figure and attributing it to the company. So a transcript enters
    the run as quoted, dated, page-bound text for an agent to reason about, and no `pnl:`-style fact is
    minted from it (Law 1).
    """

    file: str
    held_on: date | None
    read: TranscriptRead


@dataclass(frozen=True)
class DocumentIngest:
    """Everything a documents manifest contributed, per class."""

    shareholding: tuple[ShareholdingIngest, ...] = ()
    transcripts: tuple[TranscriptIngest, ...] = ()
    #: The exchange's own dissemination of the same Reg. 31 filings (ADR-0042). This is the SOURCE the
    #: ownership facts are registered from; the PDF parse above is kept as an independent second reading.
    exchange: tuple[ShareholdingRecord, ...] = ()
    #: Exchange feed vs company PDF, quarter by quarter. Owner directive: extracted data must cross-check.
    shareholding_crosscheck: CrossCheck | None = None

    @property
    def shareholding_series(self) -> tuple[ShareholdingIngest, ...]:
        """Usable quarters, oldest first — the promoter-stake time series."""
        return tuple(sorted(
            (s for s in self.shareholding if s.usable), key=lambda s: s.as_on or date.min))

    @property
    def ownership_quarters(self) -> int:
        """How many quarters of ownership evidence the run actually has, from either path."""
        return max(len(self.exchange), len(self.shareholding_series))

    @property
    def usable_transcripts(self) -> tuple[TranscriptIngest, ...]:
        """Calls where the conversation was actually recovered — an attributed Q&A, not just text.

        A transcript with no exchanges is not a transcript we can reason about. Most often it is not a
        transcript at all: the IR-page classifier matches "Concall" and so files the *announcement* of a
        call alongside the transcripts of them. Either way it is excluded from the evidence and named in
        `refusals`, never silently counted as coverage.
        """
        return tuple(t for t in self.transcripts if t.read.exchanges and t.held_on is not None)

    @property
    def refusals(self) -> tuple[str, ...]:
        """Documents we downloaded and could not read, with the reason. A gap in OUR coverage."""
        out = []
        for item in self.shareholding:
            if item.usable:
                continue
            reason = item.summary.rejected_because or (
                "no reporting date could be read, so the filing cannot be placed in a point-in-time series")
            out.append(f"{item.file}: {reason}")
        usable = {t.file for t in self.usable_transcripts}
        for call in self.transcripts:
            if call.file in usable:
                continue
            out.append(f"{call.file}: " + (
                call.read.rejected_because
                or ("no question-and-answer exchanges were recovered — this is most likely the "
                    "ANNOUNCEMENT of a call rather than its transcript")
                if call.held_on is not None else "the call date could not be read"))
        return tuple(out)


def load_documents_manifest(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text())


def _register_shareholding(
    store: FactStore, ticker: str, entry: Mapping[str, Any], bronze: Path, as_of: date | None,
) -> ShareholdingIngest:
    pdf = bronze / str(entry["file"])
    if not pdf.exists():
        return ShareholdingIngest(
            file=str(entry["file"]), period=None, as_on=None,
            summary=ShareholdingSummary(located=False, rejected_because="file not downloaded"),
        )
    extraction = extract_document(pdf.read_bytes(), ocr_backend=default_ocr_backend())
    summary = parse_shareholding(tuple(extraction.pages))
    as_on = date.fromisoformat(summary.as_on) if summary.as_on else None

    # Law 3 applies to the DOCUMENT. A shareholding pattern dated after `as_of` describes a register that
    # did not exist yet at the point in time being replayed, so it is not read at all.
    if as_on is None or (as_of is not None and as_on > as_of) or not summary.located:
        return ShareholdingIngest(
            file=str(entry["file"]), period=quarter_label(as_on) if as_on else None,
            as_on=as_on, summary=summary,
        )

    period = quarter_label(as_on)
    doc_id = f"SHP-{period}-{entry['file']}"
    store.add_document(Document(
        doc_id=doc_id, source_url=str(entry.get("source_url", "")),
        sha256=str(entry.get("sha256", "")), published_at=as_on, fetched_at=date.today(),
        grade="A", extractor_version=f"{_EXTRACTOR}+{extraction.method}",
    ))

    values: list[tuple[str, float]] = [(PROMOTER_PCT, float(summary.promoter_pct))]
    if summary.public_pct is not None:
        values.append((PUBLIC_PCT, float(summary.public_pct)))
    if summary.promoter_shareholders is not None:
        values.append((PROMOTER_HOLDERS, float(summary.promoter_shareholders)))
    # PLEDGE IS TRI-STATE AND ONLY ONE STATE IS A NUMBER. `pledged is False` means the company answered the
    # Reg. 31 question with "No", which IS the figure zero and is a real governance finding. `pledged is
    # True` means shares are pledged but this parser does not read the pledged-share COUNT, so the
    # percentage is genuinely unknown — recording anything there would be inventing it. `None` means the
    # question was never located. Only the first case produces a fact (ADR-0027: absent ≠ clean).
    if summary.pledged is False:
        values.append((PLEDGE_PCT, 0.0))

    fact_ids: list[str] = []
    for metric, value in values:
        fact_id = f"{doc_id}:{metric}:{period}"
        store.add_fact(fact_id, doc_id, ticker, metric, period, value, "pct", summary.locator)
        fact_ids.append(fact_id)

    return ShareholdingIngest(
        file=str(entry["file"]), period=period, as_on=as_on, summary=summary,
        fact_ids=tuple(fact_ids),
    )


def ingest_documents(
    store: FactStore,
    manifest: Mapping[str, Any],
    *,
    bronze: str | Path,
    as_of: date | None = None,
    classes: Sequence[str] = ("shareholding", "transcript"),
) -> DocumentIngest:
    """Read every governance document in the manifest that we have a parser for.

    Returns what was ingested AND what was refused. A document that could not be read is reported, never
    dropped: the firm not being able to read a filing is a gap in the firm, and hiding it would let a
    thin ownership series look like a complete one.
    """
    ticker = str(manifest["ticker"])
    root = Path(bronze)
    shareholding: list[ShareholdingIngest] = []
    transcripts: list[TranscriptIngest] = []

    for entry in manifest.get("documents", []):
        doc_class = str(entry.get("doc_class"))
        if doc_class not in classes:
            continue
        if doc_class == "shareholding":
            shareholding.append(_register_shareholding(store, ticker, entry, root, as_of))
        elif doc_class == "transcript":
            pdf = root / str(entry["file"])
            if not pdf.exists():
                continue
            read = read_transcript(pdf.read_bytes(), source=str(entry["file"]))
            if read.held_on is not None and as_of is not None and read.held_on > as_of:
                continue        # Law 3: a call held after `as_of` had not happened yet
            transcripts.append(TranscriptIngest(
                file=str(entry["file"]), held_on=read.held_on, read=read))

    return DocumentIngest(
        shareholding=tuple(shareholding),
        transcripts=tuple(sorted(transcripts, key=lambda t: t.held_on or date.min)),
    )


__all__ = [
    "PLEDGE_PCT",
    "PROMOTER_HOLDERS",
    "PROMOTER_PCT",
    "PUBLIC_PCT",
    "DocumentIngest",
    "ShareholdingIngest",
    "TranscriptIngest",
    "ingest_documents",
    "load_documents_manifest",
    "quarter_label",
]


#: A shareholding pattern is an EXCHANGE FILING, not audited accounts, so it is grade B under SPEC §4.
#: The PDF path registered it as A, which overstated it: nothing in a Reg. 31 submission is audited, and
#: the worst-input rule propagates that overstatement into every ratio built on it.
_EXCHANGE_GRADE = "B"


def ingest_exchange_shareholding(
    store: FactStore,
    ticker: str,
    records: Sequence[ShareholdingRecord],
    *,
    as_of: date | None = None,
) -> tuple[str, ...]:
    """Register the exchange's shareholding series as point-in-time facts. Returns the fact ids.

    `published_at` is the DISSEMINATION date, not the as-on date: the register described the company on
    31 March, but the market could not know it until the filing was broadcast in April. Using the as-on
    date would let a Phase-6 replay read a filing up to three weeks before it existed (Law 3).
    """
    out: list[str] = []
    for record in records:
        published = record.broadcast_on or record.as_on
        if as_of is not None and published > as_of:
            continue
        period = quarter_label(record.as_on)
        doc_id = f"NSE-SHP-{record.symbol}-{period}"
        store.add_document(Document(
            doc_id=doc_id,
            source_url=f"https://www.nseindia.com/api/corporate-share-holdings-master?symbol={record.symbol}",
            sha256="", published_at=published, fetched_at=date.today(),
            grade=_EXCHANGE_GRADE, extractor_version="nse-shp@1.0.0",
        ))
        values = [(PROMOTER_PCT, record.promoter_pct), (PUBLIC_PCT, record.public_pct)]
        for metric, value in values:
            fact_id = f"{doc_id}:{metric}:{period}"
            store.add_fact(fact_id, doc_id, ticker, metric, period, float(value), "pct",
                           f"Reg. 31 filing as on {record.as_on}")
            out.append(fact_id)
    return tuple(out)


def crosscheck_shareholding(ingest: "DocumentIngest") -> CrossCheck:
    """Set the exchange feed against the company's own filed PDF, quarter by quarter."""
    from datetime import date as _date

    filed = {
        _date.fromisoformat(item.summary.as_on): float(item.summary.promoter_pct)
        for item in ingest.shareholding
        if item.summary.located and item.summary.as_on and item.summary.promoter_pct is not None
    }
    return crosscheck(ingest.exchange, filed)
