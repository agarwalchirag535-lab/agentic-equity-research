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

from firm.adapters.base.tables import (
    ExtractedValue,
    find_statement_row,
    find_statement_row_sum,
    to_canonical_crore,
)
from firm.adapters.india.ageing import AgeingTable, parse_ageing_table
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
from firm.core.pipeline.checks import AgeingEvidence, CheckEvaluation, ExternalInputs
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
    # "Trade Payables" appears on the balance sheet as a bare header with the split (micro/small vs others)
    # on the lines beneath, so `total outstanding dues` is the label that actually carries the figure on
    # several of these filings; both spellings are accepted (ADR-0038).
    D.PAYABLES: ("balance_sheet", ("trade payable", "total outstanding dues"), ("ageing", "schedule")),
    D.CASH: ("balance_sheet", ("cash and cash equivalent",), ("ageing", "policy", "other bank")),
    D.SALES: ("pnl", ("revenue from operations", "revenue from operation"), ("note", "policy")),
    # The line the CWIP ageing schedule ages. Without it that schedule's grade-A total could only be
    # reconciled against a grade-B screener figure — mixed-provenance arithmetic inside the very check
    # whose job is to establish that a table can be trusted (ADR-0028, ADR-0039). `amounts in` is
    # excluded because it is the ageing table's own column header, not a balance.
    D.CWIP: ("balance_sheet", ("capital work-in-progress", "capital work in progress"),
             ("ageing", "policy", "amounts in")),
}

#: Rows whose total is printed only as components: metric -> (anchor keywords, component keywords).
#: See `find_statement_row_sum` for why a single-row read of these is not merely incomplete but wrong.
COMPONENT_SUM_ROWS: Mapping[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    D.PAYABLES: (("trade payable",), ("outstanding dues",)),
}

#: Note taxonomy category -> the deterministic checks that read that note. A note whose category has no
#: check cannot be dispositioned by code, and says so.
#:
#: The ageing entries (ADR-0039) are what turn three enumerated-but-unread notes into SUBSTANTIVE ones:
#: `payables` had no check against it at all, so every trade-payables note in every report was
#: dispositioned `unknown` — 100% covered and zero read, the exact theatre `substantive_share` exists to
#: expose. If you add a note category, add its checks here or coverage becomes theatre again.
NOTE_CHECKS: Mapping[str, tuple[str, ...]] = {
    "receivables": ("receivables_divergent", "receivables_ageing_tail", "receivables_disputed"),
    "inventory": ("inventory_divergent",),
    "cash": ("cash_interest_inconsistent", "cash_debt_paradox"),
    "ppe_cwip": ("ageing_cwip", "stalled_capex"),
    "payables": ("payables_ageing_tail",),
    "other_income": ("other_income_heavy",),
    "revenue": ("revenue_inflation", "cfo_pat"),
    "related_party": ("promoter_lending",),
    "loans_advances": ("promoter_lending",),
    "schedule_iii_disclosures": ("disclosure_gap", "ageing_reconciliation"),
    "provisions": ("provision_book_divergent", "reserve_suppression"),
    "ecl_impairment": ("provision_coverage_low", "gnpa_drift"),
    "borrowings": ("cash_debt_paradox",),
}

#: ageing table kind -> (total metric, {classified row metric: the `AgeingTable` property that holds it},
#: {bucket metric: the age in years it sums from}). Split three ways because the three groups have
#: different trust conditions: the total and the classified rows survive a table whose columns could not
#: be matched to their headers, the bucket sums do not (ADR-0038's alignment contract, ADR-0039).
AGEING_FACTS: Mapping[str, tuple[str, Mapping[str, str], Mapping[str, float]]] = {
    "cwip": (
        D.CWIP_AGEING_TOTAL,
        {D.CWIP_AGEING_SUSPENDED: "suspended"},
        {D.CWIP_AGEING_BEYOND_1Y: 1.0, D.CWIP_AGEING_2_3Y: 2.0, D.CWIP_AGEING_BEYOND_3Y: 3.0},
    ),
    "receivables": (
        D.RECEIVABLES_AGEING_TOTAL,
        {D.RECEIVABLES_AGEING_DISPUTED: "disputed", D.RECEIVABLES_AGEING_IMPAIRED: "impaired"},
        {D.RECEIVABLES_AGEING_BEYOND_1Y: 1.0, D.RECEIVABLES_AGEING_BEYOND_3Y: 3.0},
    ),
    "payables": (
        D.PAYABLES_AGEING_TOTAL,
        {D.PAYABLES_AGEING_DISPUTED: "disputed"},
        {D.PAYABLES_AGEING_BEYOND_1Y: 1.0},
    ),
}

#: The `1-2 years` column, which is a bucket rather than a "beyond" sum — the age ladder in
#: `derive.cwip_age_from_schedule` needs it on its own to tell a two-year-old block from a one-year-old.
AGEING_SINGLE_BUCKETS: Mapping[str, tuple[str, str]] = {
    "cwip": (D.CWIP_AGEING_1_2Y, "1-2 years"),
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


def _register_document(store: FactStore, filing: FilingSource) -> None:
    """Record the filing as a document. Idempotent, so each registrar can stand on its own.

    `published_at` is the exchange dissemination date and never the fetch date — it is what makes the
    Law 3 `published_at <= as_of` filter mean anything for every fact hung off this document.
    """
    store.add_document(Document(
        doc_id=filing.doc_id, source_url=filing.source_url, sha256=filing.sha256,
        published_at=filing.published_at, fetched_at=filing.published_at,
        grade=filing.grade, extractor_version=filing.extractor_version,
    ))


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
    _register_document(store, filing)
    rows: dict[str, ExtractedValue] = {}
    fact_ids: list[str] = []
    for metric, (statement, keywords, excluded) in FILING_ROWS.items():
        row = find_statement_row(filing.pages, statement, keywords, exclude=excluded)
        # Schedule III splits trade payables into micro/small and other, and the balance-sheet HEADER
        # carries no figure — so the single-row reader returns the micro/small component (₹1,550cr of a
        # ₹15,121cr line) as though it were the total. Sum the components instead (ADR-0038).
        if metric in COMPONENT_SUM_ROWS:
            anchors, components = COMPONENT_SUM_ROWS[metric]
            summed = find_statement_row_sum(filing.pages, statement, anchors, components)
            if summed is not None:
                row = summed
            elif row is not None:
                unresolved[metric] = (
                    f"{row.label!r} found at {row.locator} but its Schedule III component rows could not "
                    f"be summed, and the row the reader landed on is one component rather than the line "
                    f"total — storing it would publish a fraction of the real figure at grade "
                    f"{filing.grade}"
                )
                continue
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


def register_ageing_facts(
    store: FactStore, ticker: str, filing: FilingSource
) -> tuple[dict[str, AgeingTable], tuple[str, ...], dict[str, AgeingEvidence]]:
    """Parse the three Schedule III ageing schedules and store what they say as grade-A facts.

    ADR-0038 built the parser and stopped there: the tables were read into an object nothing consumed, so
    `ageing_cwip` still had no input and three notes were still dispositioned `unknown`. This is the wire.

    Which figures become facts is governed by the parser's alignment contract, not by convenience. A
    table whose rows do not sum to their own printed totals still yields its total and its classified
    rows (those are row totals, read whole), but every bucket sum is withheld — publishing a
    "beyond one year" figure from columns we could not match to their headers would put the filing's
    grade-A stamp on a guess, which is the one failure worse than an absent number.
    """
    _register_document(store, filing)
    tables: dict[str, AgeingTable] = {}
    evidence: dict[str, AgeingEvidence] = {}
    all_ids: list[str] = []

    for kind, (total_metric, classified, buckets) in AGEING_FACTS.items():
        table = parse_ageing_table(filing.pages, kind)
        tables[kind] = table
        mine: list[str] = []

        def store_fact(metric: str, value: float, table: AgeingTable = table,
                       mine: list[str] = mine) -> None:
            fact_id = f"{filing.doc_id}:{metric}:{filing.period}"
            store.add_fact(
                fact_id=fact_id, doc_id=filing.doc_id, ticker=ticker, metric=metric,
                period=filing.period, value=value, unit="INR_cr",
                locator=f"{table.locator} ({table.kind} ageing schedule, Schedule III)",
            )
            mine.append(fact_id)

        if table.located and table.total > 0:
            store_fact(total_metric, table.total)
            for metric, prop in classified.items():
                store_fact(metric, float(getattr(table, prop)))
            for metric, years in buckets.items():
                aged = table.aged_beyond(years)
                if aged is not None:
                    store_fact(metric, aged)
            single = AGEING_SINGLE_BUCKETS.get(kind)
            if single is not None:
                balance = table.bucket_total(single[1])
                if balance is not None:
                    store_fact(single[0], balance)

        evidence[kind] = AgeingEvidence(
            kind=kind, located=table.located, aligned=table.located and table.aligned,
            locator=f"{filing.doc_id} {table.locator}", reason=table.reason,
            buckets=table.buckets, fact_ids=tuple(mine),
        )
        all_ids.extend(mine)
    return tables, tuple(all_ids), evidence


def walk_filing(store: FactStore, ticker: str, filing: FilingSource) -> FilingWalk:
    """Enumerate the notes, scan the mandated disclosures, and register the filing's figures as facts."""
    rows, statement_fact_ids, unresolved = register_filing_facts(store, ticker, filing)
    _, ageing_fact_ids, ageing = register_ageing_facts(store, ticker, filing)
    fact_ids = (*statement_fact_ids, *ageing_fact_ids)
    # Only the notes to the ACCOUNTS count (ADR-0027). An unscoped scan enumerates AGM-notice and
    # directors'-report paragraph numbers, which no financial check can ever disposition.
    notes = tuple(enumerate_notes(filing.pages, first_page=notes_section_start(filing.pages)))

    text = "\n".join(filing.pages)
    sections_missing, _ = disclosure_gaps(forensic_sections(text))
    # Pass the filing's own period so the scan applies the law as it stood for that year (ADR-0037).
    schedule_missing, _ = schedule_iii_gaps(
        scan_schedule_iii(filing.pages, period=filing.period))
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

    # Each ageing check cites the schedule it read, and the reconciliation check cites all three
    # schedules plus the statement rows they age — that check exists precisely to compare the two.
    for check, kind in (("ageing_cwip", "cwip"), ("stalled_capex", "cwip"),
                        ("receivables_ageing_tail", "receivables"),
                        ("receivables_disputed", "receivables"),
                        ("payables_ageing_tail", "payables")):
        if ageing[kind].located:
            locators[check] = ageing[kind].locator
            ids_by_check[check] = ageing[kind].fact_ids
    if any(e.located for e in ageing.values()):
        locators["ageing_reconciliation"] = filing.doc_id
        ids_by_check["ageing_reconciliation"] = fact_ids

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
        ageing=ageing,
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
