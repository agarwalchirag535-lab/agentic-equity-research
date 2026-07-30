"""Register parsed shareholding patterns as citable governance facts (Phase 3, ADR-0035).

WHY THIS EXISTS
`adapters/india/shareholding.py` parses the filing; nothing wrote the result anywhere an agent could cite.
So `ownership_flows_analyst` ran and abstained — "27 filings ingested, none registered as facts, so no
holding may be cited" — which was honest but useless. A parser whose output no report can quote has not
closed the gap it was written for.

PERIOD AND PUBLICATION DATE
A shareholding pattern is quarterly, so it gets a quarterly period label (`Q2FY25`) rather than the annual
labels the filings ingest uses. `published_at` is the quarter end plus the Reg. 31 filing deadline of 21
days: the filing cannot exist before the quarter it reports, and SEBI requires it within 21 days of quarter
end. Using the quarter end itself would date the document earlier than it can possibly have been public and
quietly break Law 3 in the direction that permits look-ahead — the one direction that matters.

PLEDGE AS A NUMBER
The fact store holds floats, and pledge is a yes/no. It is stored as 1.0/0.0 with unit `bool`, and ONLY when
the filing actually answered the question: an unanswered pledge question writes no fact at all, so a reader
can never mistake "no pledge" for "not asked" (ADR-0027's tri-state, preserved through storage).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence

from firm.adapters.base.extract import extract_document
from firm.adapters.india.shareholding import ShareholdingSummary, parse_shareholding
from firm.core.facts.store import Document, FactStore

#: SEBI Reg. 31: the shareholding pattern is due within 21 days of quarter end.
FILING_DEADLINE_DAYS = 21

PROMOTER_HOLDING = "governance:Promoter Holding"
PUBLIC_HOLDING = "governance:Public Holding"
PROMOTER_PLEDGED = "governance:Promoter Pledged"


def quarter_label(as_on: date) -> str:
    """'2024-09-30' -> 'Q2FY25'. The Indian fiscal year starts in April and is named for its end."""
    fiscal_year = as_on.year + 1 if as_on.month >= 4 else as_on.year
    quarter = ((as_on.month - 4) % 12) // 3 + 1
    return f"Q{quarter}FY{fiscal_year % 100:02d}"


@dataclass(frozen=True)
class GovernanceIngestResult:
    file: str
    period: str | None
    published_at: date | None
    fact_ids: tuple[str, ...]
    skipped_because: str | None = None


def register_shareholding(
    store: FactStore, ticker: str, file: str, summary: ShareholdingSummary, source_url: str = "",
    sha256: str = "",
) -> GovernanceIngestResult:
    """Write one quarter's holding and pledge as grade-A facts bound to the filing.

    A summary the parser refused (categories that do not reconcile) or could not date writes nothing: an
    undated fact cannot be filtered point-in-time, and a fact that failed its own acceptance test should
    never have a reader.
    """
    if not summary.located:
        return GovernanceIngestResult(file, None, None, (), summary.rejected_because or "not parsed")
    if summary.as_on is None:
        return GovernanceIngestResult(
            file, None, None, (),
            "the filing states no reporting date, so it cannot be placed point-in-time (Law 3)",
        )

    as_on = date.fromisoformat(summary.as_on)
    published = as_on + timedelta(days=FILING_DEADLINE_DAYS)
    period = quarter_label(as_on)
    doc_id = f"SHP-{period}-{file}"

    store.add_document(Document(
        doc_id=doc_id, source_url=source_url, sha256=sha256,
        published_at=published, fetched_at=published, grade="A",
        extractor_version="shp-parse@1.0.0",
    ))

    fact_ids: list[str] = []

    def write(metric: str, value: float, unit: str) -> None:
        # A FACT ID MUST BE CITABLE. The metric name carries a space ("governance:Promoter Holding") and the
        # citation grammar — deliberately strict, since it decides whether a number in prose is backed —
        # cannot parse one. Ids built straight from the metric were therefore rejected by the very gate that
        # exists to let an agent quote them: governance facts no report could ever cite. The id is slugged;
        # the metric itself is unchanged, so queries and the report tables read as before.
        slug = metric.split(":", 1)[-1].lower().replace(" ", "_")
        fact_id = f"{doc_id}:{slug}:{period}"
        store.add_fact(
            fact_id=fact_id, doc_id=doc_id, ticker=ticker, metric=metric, period=period,
            value=value, unit=unit,
            locator=f"{summary.locator} (as on {summary.as_on}, filed by {published.isoformat()})",
        )
        fact_ids.append(fact_id)

    write(PROMOTER_HOLDING, float(summary.promoter_pct or 0.0), "pct")
    write(PUBLIC_HOLDING, float(summary.public_pct or 0.0), "pct")
    # Only when the question was actually answered — silence must not read as "no pledge".
    if summary.pledged is not None:
        write(PROMOTER_PLEDGED, 1.0 if summary.pledged else 0.0, "bool")

    return GovernanceIngestResult(file, period, published, tuple(fact_ids))


def ingest_shareholding_manifest(
    store: FactStore, manifest: Mapping[str, Any], *, bronze: str | Path, as_of: date | None = None
) -> list[GovernanceIngestResult]:
    """Parse and register every shareholding filing in a documents manifest, oldest quarter first."""
    ticker = str(manifest["ticker"])
    rows: Sequence[Mapping[str, Any]] = [
        d for d in manifest.get("documents", []) if str(d.get("doc_class")) == "shareholding"
    ]
    out: list[GovernanceIngestResult] = []
    for row in rows:
        path = Path(bronze) / str(row["file"])
        if not path.exists():
            continue
        summary = parse_shareholding(tuple(extract_document(path.read_bytes()).pages))
        result = register_shareholding(
            store, ticker, str(row["file"]), summary,
            source_url=str(row.get("source_url", "")), sha256=str(row.get("sha256", "")),
        )
        # Law 3 applies at ingest as well: a filing disseminated after `as_of` is not registered at all.
        if as_of is not None and result.published_at is not None and result.published_at > as_of:
            continue
        out.append(result)
    return sorted(out, key=lambda r: r.period or "")
