"""Walk an audited filing into facts, notes dispositions and check inputs (Phase 2, ADR-0021).

The primary-source path, made concrete. Owner directive 1 says the audited annual report is the source of
record and screener.in is a grade-B cross-check; this module is where that stops being an aspiration:

* the figures the forensic checks need (receivables, inventory, revenue, cash) are read from the filing
  itself, bound to `(page, line)` by `adapters/base/tables.py`, and **written into the fact store as
  grade-A facts** — so a report citing them cites the filing, not an aggregator;
* the notes to accounts are **enumerated** and every one is **dispositioned** (ADR-0017), with the
  disposition derived from the deterministic checks that touch that note's category;
* mandated disclosures that are absent (Schedule III rows, auditor's report sections) come back as
  `disclosure_gaps` — a signal, never a blank (ADR-0014).

The honesty problem this module has to solve explicitly: 100% note coverage is a publication gate (P1),
and coverage counts *dispositioned* notes. Marking every note `unknown` would satisfy the gate while
reading nothing. So `NotesReview.substantive_share` reports the share of notes whose disposition is
`clean`/`flag` — i.e. a deterministic check actually looked at them — and the verdict ladder consults
that share, not just coverage. Coverage proves enumeration; substantive share proves reading.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Mapping, Sequence

from firm.adapters.base.tables import ExtractedValue, find_statement_row, to_canonical_crore
from firm.adapters.india.filings import disclosure_gaps, forensic_sections
from firm.adapters.india.notes_content import related_party_summary
from firm.adapters.india.notes import (
    Note,
    notes_section_start,
    NoteDisposition,
    caro_candidate_flags,
    coverage,
    enumerate_notes,
    parse_caro_clauses,
    scan_schedule_iii,
    schedule_iii_gaps,
)
from firm.core.facts.store import Document, FactStore
from firm.core.pipeline import derive as D
from firm.core.pipeline.checks import CheckEvaluation, ExternalInputs
from firm.core.report.assemble import NotesReview
from firm.schemas.report import CheckOutcome

#: Filing rows the Phase-2 checks need: metric -> (statement, label keywords, excluded keywords).
#:
#: The `statement` is load-bearing, not decoration. Searching a whole annual report for "Inventories" finds
#: an auditor's sentence about stock verification; searching it for "Trade Receivables" finds the cash-flow
#: statement's movement line, which is a NEGATIVE number. Both happened on the real Alkyl Amines filings
#: (FY20, FY21) and both would have entered the fact store as grade A. Rows are therefore read only from the
#: pages that ARE the balance sheet or the P&L (`find_statement_row`), and a label absent from those pages
#: is UNAVAILABLE rather than sourced from prose.
#:
#: `exclude` still matters: "Trade Receivables ageing schedule" is a Schedule III table, not the balance.
FILING_ROWS: Mapping[str, tuple[str, tuple[str, ...], tuple[str, ...]]] = {
    D.RECEIVABLES: ("balance_sheet", ("trade receivable", "sundry debtor"), ("ageing", "schedule")),
    D.INVENTORY: ("balance_sheet", ("inventories", "inventory"), ("ageing", "policy")),
    D.CASH: ("balance_sheet", ("cash and cash equivalent",), ("ageing", "policy", "other bank")),
    D.SALES: ("pnl", ("revenue from operations", "revenue from operation"), ("note", "policy")),
}

#: Note taxonomy category -> the deterministic checks that read that note. A note whose category has no
#: check cannot be dispositioned by code, and says so.
NOTE_CHECKS: Mapping[str, tuple[str, ...]] = {
    "receivables": ("receivables_divergent",),
    "inventory": ("inventory_divergent",),
    "cash": ("cash_interest_inconsistent", "cash_debt_paradox"),
    "ppe_cwip": ("ageing_cwip",),
    "other_income": ("other_income_heavy",),
    "revenue": ("revenue_inflation", "cfo_pat"),
    "related_party": ("promoter_lending",),
    "loans_advances": ("promoter_lending",),
    "schedule_iii_disclosures": ("disclosure_gap",),
    "provisions": ("provision_book_divergent", "reserve_suppression"),
    "ecl_impairment": ("provision_coverage_low", "gnpa_drift"),
    "borrowings": ("cash_debt_paradox",),
}


@dataclass(frozen=True)
class FilingSource:
    """An extracted, dated filing. `published_at` is the exchange dissemination date (ADR-0018, Law 3)."""

    doc_id: str
    source_url: str
    published_at: date
    pages: tuple[str, ...]
    period: str                      # the FY the filing reports, e.g. 'FY26'
    prior_period: str | None = None  # the comparative column, e.g. 'FY25'
    grade: str = "A"
    extractor_version: str = "ar-walk@1.0.0"
    sha256: str = ""


@dataclass(frozen=True)
class FilingWalk:
    """Everything a filing contributes to a run."""

    notes: tuple[Note, ...]
    external: ExternalInputs
    registered_fact_ids: tuple[str, ...]
    caro_flags: tuple[tuple[str, str], ...]
    missing_disclosures: tuple[str, ...]
    rows: Mapping[str, ExtractedValue]


def register_filing_facts(
    store: FactStore, ticker: str, filing: FilingSource
) -> tuple[dict[str, ExtractedValue], tuple[str, ...], dict[str, str]]:
    """Read the needed rows out of the filing and store them as grade-A, locator-bound facts (Law 2).

    A row that is not present is simply not stored — the check that needed it then reports UNAVAILABLE
    with the input named, which is the behaviour owner directive 2 requires. Returns
    ``(rows, fact_ids, unresolved)``, where `unresolved` maps a metric to why a row that WAS found could
    not be trusted (today: an undeclared unit — see the scale-discipline note below).
    """
    unresolved: dict[str, str] = {}
    store.add_document(Document(
        doc_id=filing.doc_id, source_url=filing.source_url, sha256=filing.sha256,
        published_at=filing.published_at, fetched_at=filing.published_at,
        grade=filing.grade, extractor_version=filing.extractor_version,
    ))
    rows: dict[str, ExtractedValue] = {}
    fact_ids: list[str] = []
    for metric, (statement, keywords, excluded) in FILING_ROWS.items():
        row = find_statement_row(filing.pages, statement, keywords, exclude=excluded)
        if row is None or not row.values:
            continue

        # SCALE DISCIPLINE. Indian filings report in lakhs ("₹ In Lakhs" on the balance-sheet page) while
        # every screener fact in the store is in crore. This used to default the unit to `INR_cr` when the
        # page declared nothing, which stored each filing figure 100x too large — carrying the filing's
        # grade-A stamp, so it would be believed over the correct secondary value. A figure whose scale
        # cannot be established is therefore NOT stored: the check that needed it reports UNAVAILABLE with
        # the input named, which is the same treatment as an absent row and the honest one (ADR-0024).
        if to_canonical_crore(row.values[0], row.unit_hint) is None:
            unresolved[metric] = (
                f"{row.label!r} found at {row.locator} but the page declares no unit the pipeline can "
                f"resolve ({row.unit_hint or 'no declaration'}), so its scale is unknown and it is not "
                f"stored — a wrong scale is indistinguishable from a wrong number once it carries a "
                f"grade-{filing.grade} provenance"
            )
            continue

        rows[metric] = row
        columns = [(filing.period, row.values[0])]
        if filing.prior_period and len(row.values) > 1:
            columns.append((filing.prior_period, row.values[1]))
        for period, value in columns:
            fact_id = f"{filing.doc_id}:{metric}:{period}"
            store.add_fact(
                fact_id=fact_id, doc_id=filing.doc_id, ticker=ticker, metric=metric,
                period=period, value=to_canonical_crore(value, row.unit_hint),
                # The canonical scale is recorded, and the locator keeps the printed scale so a reader can
                # re-derive the figure from the page exactly as printed.
                unit="INR_cr", locator=f"{row.locator} (as printed: {row.unit_hint})",
            )
            fact_ids.append(fact_id)
    return rows, tuple(fact_ids), unresolved


def walk_filing(store: FactStore, ticker: str, filing: FilingSource) -> FilingWalk:
    """Enumerate the notes, scan the mandated disclosures, and register the filing's figures as facts."""
    rows, fact_ids, unresolved = register_filing_facts(store, ticker, filing)
    # Only the notes to the ACCOUNTS count (ADR-0027). An unscoped scan enumerates AGM-notice and
    # directors'-report paragraph numbers, which no financial check can ever disposition.
    notes = tuple(enumerate_notes(filing.pages, first_page=notes_section_start(filing.pages)))

    text = "\n".join(filing.pages)
    sections_missing, _ = disclosure_gaps(forensic_sections(text))
    schedule_missing, _ = schedule_iii_gaps(scan_schedule_iii(filing.pages))
    caro = tuple(caro_candidate_flags(parse_caro_clauses(text)))
    # A row found but unusable is a disclosure/extraction gap in its own right, and must surface rather
    # than vanish into a silently shorter `rows` mapping.
    missing = tuple(sorted({*sections_missing, *schedule_missing, *(
        f"{metric}: {why}" for metric, why in unresolved.items())}))

    # UNITS, AGAIN — and this is the half the first fix missed. `register_filing_facts` normalises what it
    # writes to the fact store, but `ExternalInputs` was still built from `row.values`, i.e. the figure AS
    # PRINTED (lakh). The checks then mixed the two scales: `cash_debt_paradox` divided a lakh cash figure
    # by a crore asset figure and reported "cash/assets 496.6%", which fired a FORENSIC_CAUTION on a company
    # whose real ratio is 4.97%. Ratio-of-pairs checks (receivables vs revenue growth) are scale-invariant
    # and survived, which is exactly why the bug stayed hidden until a check compared across sources.
    #
    # Everything crossing into `ExternalInputs` is therefore converted to canonical ₹ crore here, so a check
    # can never see two scales at once.
    def canonical(metric: str, index: int) -> float | None:
        row = rows.get(metric)
        if row is None or len(row.values) <= index:
            return None
        return to_canonical_crore(row.values[index], row.unit_hint)

    def pair(metric: str) -> tuple[float, float] | None:
        first, second = canonical(metric, 0), canonical(metric, 1)
        return None if first is None or second is None else (first, second)

    ids_by_check: dict[str, tuple[str, ...]] = {}
    locators: dict[str, str] = {}
    for check, metric in (("receivables_divergent", D.RECEIVABLES),
                          ("inventory_divergent", D.INVENTORY),
                          ("revenue_inflation", D.SALES),
                          ("cash_interest_inconsistent", D.CASH),
                          ("cash_debt_paradox", D.CASH)):
        if metric in rows:
            ids_by_check[check] = tuple(i for i in fact_ids if f":{metric}:" in i)
            locators[check] = f"{filing.doc_id} {rows[metric].locator}"
    if missing:
        ids_by_check["disclosure_gap"] = ()
        locators["disclosure_gap"] = filing.doc_id

    # Read the Ind AS 24 note body (ADR-0027) so the related-party notes become SUBSTANTIVE rather than
    # merely enumerated — `NOTE_CHECKS` routes the `related_party` and `loans_advances` categories through
    # `promoter_lending`, so a check that can finally run is what dispositions those notes.
    rp = related_party_summary(filing.pages)
    if rp.located:
        locators["promoter_lending"] = f"{filing.doc_id} {rp.locator}"
        ids_by_check.setdefault("promoter_lending", ())

    external = ExternalInputs(
        receivables=pair(D.RECEIVABLES),
        inventory=pair(D.INVENTORY),
        revenue=pair(D.SALES),
        cash=canonical(D.CASH, 0),
        promoter_lending_disclosed=rp.has_promoter_lending,
        related_party_categories=tuple(sorted(rp.categories)),
        kmp_remuneration_cr=rp.remuneration_cr,
        disclosure_gaps=missing,
        disclosure_scanned=True,
        source_locators=locators,
        fact_ids=ids_by_check,
    )
    return FilingWalk(notes, external, fact_ids, caro, missing, rows)


def disposition_notes(
    notes: Sequence[Note],
    evaluation: CheckEvaluation,
    *,
    disclosure_gaps_found: Sequence[str] = (),
) -> tuple[NotesReview, tuple[NoteDisposition, ...]]:
    """Disposition every enumerated note from the outcome of the checks that read it (ADR-0017).

    `flag` when a check on that note fired, `clean` when one ran and passed, `unknown` when the check's
    inputs were absent or no deterministic check covers the category. Every note gets exactly one
    disposition, so coverage is 100% by construction — and `substantive_share` is what stops that from
    being a free pass.
    """
    dispositions: list[NoteDisposition] = []
    substantive = 0
    for note in notes:
        checks = NOTE_CHECKS.get(note.category, ())
        outcomes = {c: evaluation.outcome(c) for c in checks}
        fired = [c for c, o in outcomes.items() if o is CheckOutcome.FLAG]
        passed = [c for c, o in outcomes.items() if o is CheckOutcome.PASS]
        absent = [c for c, o in outcomes.items() if o is CheckOutcome.UNAVAILABLE]

        if fired:
            status, rationale = "flag", f"check(s) fired on this note: {', '.join(fired)}"
        elif passed:
            status, rationale = "clean", f"check(s) ran and passed: {', '.join(passed)}"
        elif absent:
            status, rationale = "unknown", (
                f"check(s) {', '.join(absent)} could not run — inputs not disclosed in the filing text"
            )
        else:
            status, rationale = "unknown", (
                f"no deterministic check covers category '{note.category}'; narrative review by an "
                "analyst or agent is required before this note can be called clean"
            )
        if status in ("clean", "flag"):
            substantive += 1
        dispositions.append(NoteDisposition(
            note_number=note.number, status=status, rationale=rationale,
            figure_locators=[f"p.{note.page} l.{note.line}"],
        ))

    cov, undispositioned = coverage(notes, dispositions)
    total = len(notes)
    review = NotesReview(
        coverage=cov,
        undispositioned=tuple(undispositioned),
        substantive_share=(substantive / total) if total else 0.0,
        notes_total=total,
        disclosure_gaps=tuple(disclosure_gaps_found),
        scanned=True,
    )
    return review, tuple(dispositions)
