"""Walk a manifest of audited filings into the fact store as grade-A facts (ADR-0024).

THE GAP THIS CLOSES
STATUS §3A: `backfill_filings()` had no caller and `firm deep-dive` had no way to read an annual report, so
every run rested on a grade-B screener snapshot. The owner's objection was exact — *"the data is downloaded
or seen by the secondary sources, not by the primary sources"*. This module is the primary-source path made
runnable: a manifest of downloaded PDFs in, a decade of grade-A locator-bound facts out.

WHY A MANIFEST RATHER THAN A DIRECTORY SCAN
Law 3 needs a real `published_at` per document, and a filename cannot supply one. The manifest records, per
filing, its `source_url`, its `published_at`, and **the basis for that date** — `upload-path` when the
publisher's own URL evidences it (`/2026/06/...`), `statutory-proxy` when the document was re-uploaded later
and the true date has to be approximated from the AGM deadline. A point-in-time claim resting on a guessed
date is worse than one resting on a stated approximation, so the basis travels with the fact.

WHY EVERY YEAR, NOT JUST THE LATEST
Each annual report prints the prior year as its comparative column, so ten filings yield ten *overlapping*
two-year windows. Where they overlap they must agree, and `crosscheck_overlaps` verifies that they do — an
independent-document consistency test that a restatement or an extraction error both break. On Alkyl Amines
the FY17-FY26 receivables chain reconciles exactly at every join.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from itertools import pairwise
from pathlib import Path
from typing import Any, Mapping, Sequence

from firm.adapters.base.extract import extract_document
from firm.core.facts.store import FactStore
from firm.core.pipeline.filing import FilingSource, register_filing_facts


@dataclass(frozen=True)
class FilingIngestResult:
    """What one filing contributed, including what it could not."""

    file: str
    period: str
    pages: int
    method: str
    complete: bool
    fact_ids: tuple[str, ...]
    stored: Mapping[str, float]          # metric -> canonical ₹ crore value for `period`
    unresolved: Mapping[str, str]        # metric -> why a located row was not trusted


@dataclass(frozen=True)
class Overlap:
    """One (metric, period) figure asserted by two different filings."""

    metric: str
    period: str
    from_filing: str
    from_value: float
    against_filing: str
    against_value: float

    @property
    def delta(self) -> float:
        return self.from_value - self.against_value

    def classify(self, policy: Mapping[str, float]) -> str:
        """`agree` | `rounding` | `restated` | `extraction_error` — three findings and one non-finding.

        The distinction decides what a report may do with the figure, so collapsing it would be a mistake:

        `rounding`         the two documents printed the same figure at different precision. Noise.
        `restated`         a real difference beyond rounding. On Alkyl Amines, FY22 revenue is Rs 1,542.80cr
                           in the FY22 report and Rs 1,541.99cr as the FY23 report's comparative — Rs 0.81cr,
                           0.05%, far above rounding. That is a reclassification the company made and did not
                           headline, and it is exactly the kind of thing a line-by-line reading surfaces.
        `extraction_error` a gap so large relative to the figure that no restatement explains it. FY21
                           inventories read as Rs 0.07cr against Rs 121.90cr corroborated by the FY22 report:
                           our misread, not their accounting. Must be quarantined, never published.
        """
        if self.agrees:
            return "agree"
        gap = abs(self.delta)
        scale = max(abs(self.from_value), abs(self.against_value)) or 1.0
        if gap <= max(float(policy["rounding_abs_cr"]), float(policy["rounding_rel"]) * scale):
            return "rounding"
        if gap / scale > float(policy["extraction_error_rel"]):
            return "extraction_error"
        return "restated"

    @property
    def agrees(self) -> bool:
        """True when the two filings state the SAME figure, allowing only float representation noise.

        Not a materiality tolerance: two filings printing the same year must print the same number, because
        the later one's comparative column IS the earlier one's reported figure. The only slack permitted is
        binary floating point — `183.6629` and `183.66299999999998` are the same figure arrived at by two
        multiplications, and an earlier `round(x, 4)` comparison reported them as a mismatch.
        """
        import math

        return math.isclose(self.from_value, self.against_value, rel_tol=1e-9, abs_tol=1e-9)


def load_manifest(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text())


def filing_from_manifest(entry: Mapping[str, Any], bronze: str | Path) -> FilingSource:
    """Build a `FilingSource` from a manifest row, extracting the PDF's pages on the way."""
    pdf = Path(bronze) / str(entry["file"])
    extraction = extract_document(pdf.read_bytes())
    return FilingSource(
        doc_id=f"AR-{entry['period']}-{entry['file']}",
        source_url=str(entry["source_url"]),
        published_at=date.fromisoformat(str(entry["published_at"])),
        pages=tuple(extraction.pages),
        period=str(entry["period"]),
        prior_period=entry.get("prior_period"),
        grade=str(entry.get("grade", "A")),
        extractor_version=f"ar-walk@1.1.0+{extraction.method}",
        sha256=str(entry.get("sha256", "")),
    )


def ingest_manifest(
    store: FactStore, manifest: Mapping[str, Any], *, bronze: str | Path, as_of: date | None = None
) -> list[FilingIngestResult]:
    """Register every filing in the manifest. Oldest first, so a later filing's figure wins a tie.

    Ordering is deliberate: `store.add_fact` is INSERT-OR-REPLACE keyed by `fact_id`, and each filing writes
    its own `doc_id`-prefixed ids, so nothing is overwritten — but reading oldest-first keeps the *reported*
    (rather than restated) figure discoverable in `crosscheck_overlaps` before the newer one lands.

    `as_of` filters at ingest as well as at query time: a filing disseminated after `as_of` is not read at
    all, because extracting it would leak its notes and auditor language into the run (Law 3, ADR-0021).
    """
    ticker = str(manifest["ticker"])
    entries = sorted(manifest["filings"], key=lambda e: str(e["period"]))
    out: list[FilingIngestResult] = []
    for entry in entries:
        published = date.fromisoformat(str(entry["published_at"]))
        if as_of is not None and published > as_of:
            continue
        filing = filing_from_manifest(entry, bronze)
        rows, fact_ids, unresolved, _values = register_filing_facts(store, ticker, filing)
        out.append(FilingIngestResult(
            file=str(entry["file"]), period=filing.period, pages=len(filing.pages),
            method=filing.extractor_version.split("+")[-1],
            complete=bool(filing.pages),
            fact_ids=fact_ids,
            stored={
                metric: store.query_fact(ticker, metric, filing.period, as_of=published).value
                for metric in rows
                if store.query_fact(ticker, metric, filing.period, as_of=published) is not None
            },
            unresolved=dict(unresolved),
        ))
    return out


def quarantine_extraction_errors(
    store: FactStore,
    ticker: str,
    results: Sequence[FilingIngestResult],
    metrics: Sequence[str],
    policy: Mapping[str, float],
) -> list[Overlap]:
    """Delete every figure two filings contradict each other about beyond any restatement. Returns them.

    This is what turns the overlapping filings from a *report* into a *control*. `crosscheck_overlaps`
    has always been able to tell that the FY18 report says trade payables were ₹67.18cr and the FY19
    report's comparative column says ₹6.65cr — a 90% gap, which no company restates — but nothing acted
    on it, so the misread figure stayed in the store at grade A and would out-rank the screener.

    BOTH sides are removed, not the one that looks wrong. Which document was misread is exactly what the
    disagreement does not say, and picking the larger, the smaller or the newer would be a guess dressed
    as a rule. A metric-year the sources cannot agree on is UNAVAILABLE, with the disagreement published
    (owner directive 2: missing data is a signal, never a blank).

    `restated` overlaps are left alone: a real restatement is a finding about the company, and the
    resolver already prefers the later filing within a grade.
    """
    removed: list[Overlap] = []
    for overlap in crosscheck_overlaps(store, ticker, results, metrics):
        if overlap.classify(policy) != "extraction_error":
            continue
        doomed = [
            fact.fact_id
            for fact in store.facts_for(ticker, overlap.metric, overlap.period)
            if fact.doc_id.endswith(overlap.from_filing) or fact.doc_id.endswith(overlap.against_filing)
        ]
        if store.remove_facts(doomed):
            removed.append(overlap)
    return removed


def crosscheck_overlaps(
    store: FactStore, ticker: str, results: Sequence[FilingIngestResult], metrics: Sequence[str]
) -> list[Overlap]:
    """Every figure two filings both assert, paired for comparison.

    A filing's comparative column restates the prior year, so consecutive filings overlap by one year. This
    is the strongest verification available without a third source: the documents are independent
    publications, and agreement across them means the extraction read both correctly AND the company did not
    quietly restate. A disagreement is a finding either way, which is why it is surfaced rather than
    averaged.
    """
    # Consecutive filings by period: filing N's comparative column covers filing N-1's reported year.
    ordered = sorted(results, key=lambda r: r.period)
    overlaps: list[Overlap] = []
    for prior, newer in zip(ordered, ordered[1:]):
        for metric in metrics:
            # doc_id is f"AR-{period}-{file}", so the filename is everything after the second hyphen.
            claims = {
                fact.doc_id.split("-", 2)[2]: fact.value
                for fact in store.facts_for(ticker, metric, prior.period)
            }
            reported, comparative = claims.get(prior.file), claims.get(newer.file)
            if reported is None or comparative is None:
                continue
            overlaps.append(Overlap(
                metric=metric, period=prior.period,
                from_filing=newer.file, from_value=comparative,
                against_filing=prior.file, against_value=reported,
            ))
    return overlaps


#: Extractor versions carrying this suffix verified every figure against the page text (ADR-0046's
#: V-checks: value found verbatim, statements internally reconciled). A contradiction between two such
#: documents cannot plausibly be a misread on either side — it is the company printing different
#: figures for the same period, i.e. a re-presentation.
VERIFIED_EXTRACTOR_SUFFIX = "+verified"


@dataclass(frozen=True)
class StoreContradiction:
    """One (metric, period) two documents contradict beyond any restatement band, plus what it means.

    `kind` is provenance-aware where `Overlap.classify` is value-only: when BOTH sides were verified
    against their pages, "extraction_error" would be a false confession — the honest name is
    `re_presented` (the company changed the figure's basis, e.g. Symphony FY13 printing traded-goods
    purchases inside materials consumed while FY14 splits them). Either way the figure is quarantined:
    two documents that disagree 4x are not a series, and picking a side would be a guess.
    """

    overlap: Overlap
    kind: str  # 're_presented' | 'extraction_error'
    removed_fact_ids: tuple[str, ...]


def quarantine_store_contradictions(
    store: FactStore, ticker: str, as_of: date, policy: Mapping[str, float]
) -> list[StoreContradiction]:
    """Quarantine every (metric, period) that two documents visible as-of contradict beyond restatement.

    The store-driven sibling of `quarantine_extraction_errors`: that one needs walker
    `FilingIngestResult`s, so ADR-0046 reading-path facts had no quarantine at all — six Symphony
    filings could disagree 4x on FY13 materials and both sides stayed grade A. Reads `facts_for`
    directly so it works for facts however they arrived, and only pairs both published on/before
    ``as_of`` (Law 3: a contradiction created by a future filing does not exist yet).

    BOTH sides are removed, same rationale as the walker path: the disagreement does not say which
    document to trust, and a metric-year the sources cannot agree on is UNAVAILABLE with the
    disagreement returned for publication (owner directive 2).
    """
    out: list[StoreContradiction] = []
    metrics = sorted({f.metric for f in store.query_metric_prefix(ticker, "", as_of)})
    for metric in metrics:
        periods = sorted({f.period for f in store.query_metric_prefix(ticker, metric, as_of)
                          if f.metric == metric})
        for period in periods:
            visible = [f for f in store.facts_for(ticker, metric, period) if f.published_at <= as_of]
            for earlier, later in pairwise(visible):
                overlap = Overlap(metric=metric, period=period,
                                  from_filing=later.doc_id, from_value=later.value,
                                  against_filing=earlier.doc_id, against_value=earlier.value)
                if overlap.classify(policy) != "extraction_error":
                    continue
                both_verified = all(
                    f.extractor_version.endswith(VERIFIED_EXTRACTOR_SUFFIX) for f in (earlier, later))
                doomed = tuple(f.fact_id for f in (earlier, later))
                store.remove_facts(doomed)
                out.append(StoreContradiction(
                    overlap=overlap,
                    kind="re_presented" if both_verified else "extraction_error",
                    removed_fact_ids=doomed,
                ))
    return out


@dataclass(frozen=True)
class Restatement:
    """One figure a later filing quietly revised (Overlap class 'restated', lesson 3 of the first
    prediction resolution). Not an extraction error — those are quarantined — and not rounding: a real
    change the company made to an already-published number, which is exactly the quiet-change material
    (FORENSIC_METHODOLOGY P5) a reader should see in one place."""

    metric: str
    period: str
    earlier_doc: str
    earlier_value: float
    later_doc: str
    later_value: float

    @property
    def delta(self) -> float:
        return self.later_value - self.earlier_value

    @property
    def relative(self) -> float:
        scale = max(abs(self.earlier_value), abs(self.later_value)) or 1.0
        return self.delta / scale


def restatement_log(
    store: FactStore,
    ticker: str,
    metrics: Sequence[str] | None,
    as_of: date,
    policy: Mapping[str, float],
) -> list[Restatement]:
    """Every quiet revision between documents visible as-of the run date, oldest first.

    Reads the store directly rather than ingest results, so it works at report time for facts however
    they arrived (walker or ADR-0046 reading), and respects Law 3: a restatement made by a filing
    published after `as_of` does not exist yet. Adjacent-publication pairs only — a figure revised twice
    is two restatements, which is how the reader should see it. PC Jeweller's first entry is the FY18
    filing revising FY17 operating cash flow from 756.48 to 794.35 while current-year cash collapsed.
    """
    if metrics is None:
        metrics = sorted({f.metric for f in store.query_metric_prefix(ticker, "", as_of)
                          if not f.metric.startswith("guidance:")})
    out: list[Restatement] = []
    for metric in metrics:
        periods = {
            fact.period
            for fact in store.query_metric_prefix(ticker, metric, as_of)
            if fact.metric == metric
        }
        for period in sorted(periods):
            visible = [f for f in store.facts_for(ticker, metric, period) if f.published_at <= as_of]
            for earlier, later in pairwise(visible):
                overlap = Overlap(metric=metric, period=period,
                                  from_filing=later.doc_id, from_value=later.value,
                                  against_filing=earlier.doc_id, against_value=earlier.value)
                if overlap.classify(policy) == "restated":
                    out.append(Restatement(metric, period, earlier.doc_id, earlier.value,
                                           later.doc_id, later.value))
    return out
