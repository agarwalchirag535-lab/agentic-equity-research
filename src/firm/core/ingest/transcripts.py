"""Register parsed transcript guidance as citable facts (Phase 3, ADR-0036).

WHY THIS EXISTS
ADR-0036 parsed the transcripts; this is the ADR-0035 step for them — a parsed quote nothing can cite is
not evidence. Registered here, "we expect double digit growth around 10% to 15%" becomes two facts an
agent can quote by id, each carrying the verbatim sentence and its page in the locator, so the citation
gate can hold the agent to exactly what management said and where.

WHAT A GUIDANCE FACT IS — AND IS NOT
It is a record that management ATTACHED THIS NUMBER TO THE FUTURE on this call. It is data about
management (house standard: a management claim is data about management, not about the business), graded A
because the transcript is the company's own Reg-30 filing — the provenance of the *statement* is primary
even though the statement itself is a promise. Only sentences classified `statement` are registered:
an analyst's question is never management's guidance, and that distinction was drawn at the parser.

PUBLICATION DATE
The transcript becomes public when the company submits it, not when the call happens. The Reg-30 letter's
own date is used when page 1 carries one; otherwise the SEBI deadline (five working days after the call,
taken as seven calendar days) — the same conservative direction as the shareholding deadline in
`governance.py`: never date a document earlier than it can have been public.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence

from firm.adapters.base.extract import extract_document
from firm.adapters.india.transcripts import TranscriptSummary, parse_transcript
from firm.core.facts.store import Document, FactStore

#: SEBI Reg. 30 Schedule III Para A(15A): the transcript is due within five working days of the call.
#: Seven calendar days covers five working days across any weekend.
REG30_DEADLINE_DAYS = 7

#: Every guidance metric shares this prefix, so one point-in-time query reads the whole series.
GUIDANCE_PREFIX = "guidance:"

#: A locator must stay readable in a report table; a quote is truncated there, never in the store's quote.
_LOCATOR_QUOTE_CHARS = 220


@dataclass(frozen=True)
class TranscriptIngestResult:
    file: str
    period: str | None
    published_at: date | None
    fact_ids: tuple[str, ...]
    skipped_because: str | None = None


def register_transcript(
    store: FactStore, ticker: str, file: str, summary: TranscriptSummary,
    source_url: str = "", sha256: str = "",
) -> TranscriptIngestResult:
    """Write one call's guided figures as grade-A facts bound to the transcript.

    A summary the parser refused writes nothing, and so does an undated call: without a call date there is
    no defensible publication date, and an undated fact cannot be filtered point-in-time (Law 3).
    """
    if not summary.located:
        return TranscriptIngestResult(file, None, None, (), summary.rejected_because or "not parsed")
    if summary.call_date is None:
        return TranscriptIngestResult(
            file, None, None, (),
            "no call date could be read, so the transcript cannot be placed point-in-time (Law 3)",
        )
    if summary.period is None:
        return TranscriptIngestResult(
            file, None, None, (),
            "no quarter could be read or inferred, so the guidance has no period to hang from",
        )

    published = (
        date.fromisoformat(summary.cover_date) if summary.cover_date is not None
        else date.fromisoformat(summary.call_date) + timedelta(days=REG30_DEADLINE_DAYS)
    )
    doc_id = f"TRN-{summary.period}-{file}"

    store.add_document(Document(
        doc_id=doc_id, source_url=source_url, sha256=sha256,
        published_at=published, fetched_at=published, grade="A",
        extractor_version="transcript-parse@1.0.0",
    ))

    fact_ids: list[str] = []
    for statement in summary.guidance:
        if statement.kind != "statement":
            continue  # an analyst's ask must never be stored as management's guidance
        for value in statement.values:
            # Ordinal suffix, because one quarter legitimately carries several guided figures — even two
            # under the same topic ("10% to 15%") — and ids must never collide into silent overwrites.
            fact_id = f"{doc_id}:guidance_{statement.topic}:{summary.period}:{len(fact_ids) + 1}"
            quote = statement.quote[:_LOCATOR_QUOTE_CHARS]
            store.add_fact(
                fact_id=fact_id, doc_id=doc_id, ticker=ticker,
                metric=f"{GUIDANCE_PREFIX}{statement.topic}", period=summary.period,
                value=value.value, unit=value.unit,
                locator=f'p.{statement.page} — "{quote}" (call {summary.call_date})',
            )
            fact_ids.append(fact_id)

    return TranscriptIngestResult(file, summary.period, published, tuple(fact_ids))


def ingest_transcript_manifest(
    store: FactStore, manifest: Mapping[str, Any], *, bronze: str | Path, as_of: date | None = None
) -> list[TranscriptIngestResult]:
    """Parse and register every transcript in a documents manifest, oldest call first."""
    ticker = str(manifest["ticker"])
    rows: Sequence[Mapping[str, Any]] = [
        d for d in manifest.get("documents", []) if str(d.get("doc_class")) == "transcript"
    ]
    out: list[TranscriptIngestResult] = []
    for row in rows:
        path = Path(bronze) / str(row["file"])
        if not path.exists():
            continue
        summary = parse_transcript(tuple(extract_document(path.read_bytes()).pages))
        result = register_transcript(
            store, ticker, str(row["file"]), summary,
            source_url=str(row.get("source_url", "")), sha256=str(row.get("sha256", "")),
        )
        # Law 3 applies at ingest as well: a transcript submitted after `as_of` is not registered at all.
        if as_of is not None and result.published_at is not None and result.published_at > as_of:
            continue
        out.append(result)
    return sorted(out, key=lambda r: r.period or "")
