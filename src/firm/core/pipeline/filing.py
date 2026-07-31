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

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Mapping, Sequence

from firm.adapters.base.tables import (
    ExtractedValue,
    find_statement_row,
    find_statement_rows,
    numbers_on_line,
    reconcile_to_identity,
    to_canonical_crore,
)
from firm.adapters.india.filings import disclosure_gaps, forensic_sections
from firm.adapters.india.notes_content import related_party_summary
from firm.adapters.india.notes import (
    Note,
    notes_section_start,
    NoteDisposition,
    caro_candidate_flags,
    coverage,
    enumerate_notes,
    note_body,
    parse_caro_clauses,
    scan_schedule_iii,
    schedule_iii_gaps,
)
from firm.core.facts.store import Document, FactStore
from firm.core.pipeline import derive as D
from firm.core.pipeline.checks import CheckEvaluation, ExternalInputs
from firm.core.report.assemble import NotesReview
from firm.schemas.report import CheckOutcome

#: How many printed columns a row may contribute. A filing prints the year and its comparative; the
#: FY18 balance sheet prints a third (the Ind AS transition date), which belongs to neither period the
#: manifest names and is discarded rather than mistaken for a year.
_MAX_COLUMNS = 2


@dataclass(frozen=True)
class RowSpec:
    """Where one metric is printed, and how to read it off the page.

    `statement` is load-bearing, not decoration. Searching a whole annual report for "Inventories" finds
    an auditor's sentence about stock verification; searching it for "Trade Receivables" finds the
    cash-flow statement's movement line, which is a NEGATIVE number. Both happened on the real Alkyl
    Amines filings (FY20, FY21) and both would have entered the fact store as grade A. Rows are therefore
    read only from the pages that ARE the named statement, and a label absent from those pages is
    UNAVAILABLE rather than sourced from prose.

    `exclude` still matters: "Trade Receivables ageing schedule" is a Schedule III table, not the balance.

    `total` sums every matching row instead of taking the first, for the Schedule III lines that are a
    total the filing never prints. Trade payables is the standing example — "…dues of Micro & Small
    Enterprises" and "…dues of creditors other than Micro Enterprises and Small Enterprises" are separate
    rows, and reading the first gives a payables balance ten times too small. Borrowings has the same
    shape (secured / unsecured, long-term / short-term).

    `identity` names a row this one must agree with, checked by `reconcile_to_identity`.

    `fallback` is a second keyword set tried only when the first matches nothing, for a line whose
    presentation changed across the window: trade payables is printed as one row in the FY18 filing and
    split into the two Schedule III components from FY19 on.

    `unit` is the scale the figure is printed at, and defaulting it would be a real error. Every money row
    on these pages is in the unit the page declares ("₹ In Lakhs") and is converted to ₹ crore; **earnings
    per share is not**. EPS is rupees per share, and putting it through the lakh→crore conversion turned
    Rs 35.20 into Rs 0.352 — a number that looks like a plausible EPS for a different company and would
    have made the per-share growth wedge, which is the firm's actual question, meaningless.
    """

    statement: str
    keywords: tuple[str, ...]
    exclude: tuple[str, ...] = ()
    total: bool = False
    identity: tuple[str, ...] = ()
    fallback: tuple[str, ...] = ()
    unit: str = "INR_cr"
    #: Which match to take when a label appears more than once on the statement. An Ind AS balance sheet
    #: prints "Loans", "Other Financial Assets" and "Provisions" twice — once under non-current and once
    #: under current — and taking the first every time would silently report the non-current figure for
    #: both. 0 is the first match, in print order (so non-current, then current).
    occurrence: int = 0


#: The metric names live in `derive.py`, which is the registry the rest of the firm reads against; they
#: are aliased here only to keep this table legible.
TOTAL_INCOME = D.TOTAL_INCOME
MATERIALS = D.MATERIALS
INVENTORY_CHANGE = D.INVENTORY_CHANGE
EMPLOYEE_COST = D.EMPLOYEE_COST
OTHER_EXPENSES = D.OTHER_EXPENSES
TOTAL_EXPENSES = D.TOTAL_EXPENSES
TOTAL_TAX = D.TOTAL_TAX
OTHER_BANK = D.OTHER_BANK
PAYABLES = D.PAYABLES
CFF = D.CFF
CAPEX = D.CAPEX
DIVIDEND_PAID = D.DIVIDEND_PAID
INTEREST_PAID = D.INTEREST_PAID
INTEREST_INCOME = D.INTEREST_INCOME

#: Every row the pipeline reads out of an audited annual report, keyed by the metric name the rest of the
#: firm already uses (`core/pipeline/derive.py`). Registering under those names is the point: the resolver
#: orders by `(grade, published_at)`, so a filing figure displaces the screener's wherever both exist.
FILING_ROWS: Mapping[str, RowSpec] = {
    # ---- Statement of Profit and Loss ----------------------------------------------------------
    D.SALES: RowSpec("pnl", ("revenue from operations", "revenue from operation"), ("note", "policy")),
    D.OTHER_INCOME: RowSpec("pnl", ("other income",)),
    TOTAL_INCOME: RowSpec("pnl", ("total income",)),
    MATERIALS: RowSpec("pnl", ("cost of materials consumed",)),
    # The FY22-FY26 filings wrap this label, so the row carrying the figures is the CONTINUATION line
    # ("Work-In-Progress  31  2,841.93  440.42"). Matching the tail as well as the head is what reads it.
    INVENTORY_CHANGE: RowSpec("pnl", ("changes in inventories", "work-in-progress")),
    EMPLOYEE_COST: RowSpec("pnl", ("employee benefit",)),
    D.INTEREST: RowSpec("pnl", ("finance cost",)),
    D.DEPRECIATION: RowSpec("pnl", ("depreciation and amorti",)),
    OTHER_EXPENSES: RowSpec("pnl", ("other expenses",)),
    TOTAL_EXPENSES: RowSpec("pnl", ("total expenses",)),
    # "Profit before Exceptional Items and Tax" does not contain "profit before tax", so the exceptional
    # subtotal is passed over and the statutory PBT line is the one read.
    D.PBT: RowSpec("pnl", ("profit before tax",), ("exceptional",)),
    TOTAL_TAX: RowSpec("pnl", ("total tax expense",)),
    D.PAT: RowSpec("pnl", ("profit after tax", "profit for the year")),
    D.EPS: RowSpec("pnl", ("basic",), unit="INR"),
    # ---- Balance Sheet -------------------------------------------------------------------------
    D.FIXED_ASSETS: RowSpec("balance_sheet", ("property, plant",)),
    D.CWIP: RowSpec("balance_sheet", ("capital work",)),
    D.INVENTORY: RowSpec("balance_sheet", ("inventories", "inventory"), ("ageing", "policy", "changes")),
    D.RECEIVABLES: RowSpec("balance_sheet", ("trade receivable", "sundry debtor"), ("ageing", "schedule")),
    D.CASH: RowSpec(
        "balance_sheet", ("cash and cash equivalent", "cash and bank balances"),
        ("ageing", "policy", "other bank")),
    OTHER_BANK: RowSpec("balance_sheet", ("other bank balances",)),
    D.TOTAL_ASSETS: RowSpec(
        "balance_sheet", ("total assets",),
        identity=("total equity and liabilities", "total equity & liabilities")),
    D.EQUITY_CAPITAL: RowSpec("balance_sheet", ("equity share capital", "share capital"), ("application",)),
    D.RESERVES: RowSpec("balance_sheet", ("other equity", "reserves and surplus")),
    D.BORROWINGS: RowSpec("balance_sheet", ("borrowings",), total=True),
    PAYABLES: RowSpec("balance_sheet", ("enterprises",), total=True, fallback=("trade payable",)),
    # THE REST OF THE BALANCE SHEET. None of these feeds a forensic check; they exist so the claim "the
    # notes were read line by line" can be TESTED rather than asserted. Each one is the face figure a
    # note details, so `reconcile_notes` can require the note's own breakup to add back to it — and a
    # label this table maps to the wrong row shows up immediately as a note that does not tie, instead
    # of as a plausible-looking fact nobody checks.
    D.ROU_ASSETS: RowSpec("balance_sheet", ("right of use", "right-of-use")),
    D.INTANGIBLES: RowSpec("balance_sheet", ("intangible asset",), ("development",)),
    D.NONCURRENT_LOANS: RowSpec("balance_sheet", ("loans",), ("borrowing",)),
    D.CURRENT_LOANS: RowSpec("balance_sheet", ("loans",), ("borrowing",), occurrence=1),
    D.OTHER_NONCURRENT_FIN_ASSETS: RowSpec("balance_sheet", ("other financial assets",)),
    D.OTHER_CURRENT_FIN_ASSETS: RowSpec("balance_sheet", ("other financial assets",), occurrence=1),
    D.OTHER_NONCURRENT_ASSETS: RowSpec("balance_sheet", ("other non-current assets", "other non current")),
    D.OTHER_CURRENT_ASSETS: RowSpec("balance_sheet", ("other current assets",)),
    D.NONCURRENT_PROVISIONS: RowSpec("balance_sheet", ("provisions",)),
    D.CURRENT_PROVISIONS: RowSpec("balance_sheet", ("provisions",), occurrence=1),
    D.DEFERRED_TAX: RowSpec("balance_sheet", ("deferred tax",)),
    D.OTHER_FIN_LIABILITIES: RowSpec("balance_sheet", ("other financial liabilities",)),
    D.OTHER_CURRENT_LIABILITIES: RowSpec("balance_sheet", ("other current liabilities",)),
    # ---- Statement of Cash Flows ---------------------------------------------------------------
    # "net" is required on all three: the bare section headings ("Cash Flows from Investing Activities")
    # match the keywords and carry no figures, but a stray number on such a line would be read as the
    # section's total.
    D.CFO: RowSpec("cashflow", ("net cash flow from operating", "net cash flows from operating",
                                "net cash from operating")),
    D.CFI: RowSpec("cashflow", ("net cash flow from investing", "net cash flows from investing",
                                "net cash from investing")),
    CFF: RowSpec("cashflow", ("net cash flow from financing", "net cash flows from financing",
                              "net cash from financing")),
    CAPEX: RowSpec("cashflow", ("purchase of property", "purchase of fixed")),
    DIVIDEND_PAID: RowSpec("cashflow", ("dividend paid",)),
    INTEREST_PAID: RowSpec("cashflow", ("interest paid",)),
    # The interest the cash actually earned, added back in the operating reconciliation. "received" is
    # excluded because the investing section repeats it on a cash basis, and the accrual figure is the
    # one that belongs against an average balance.
    INTEREST_INCOME: RowSpec("cashflow", ("interest income",), ("received",)),
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
    #: note number -> (status, why) from `reconcile_notes`, for `disposition_notes`.
    reconciliations: Mapping[int, tuple[str, str]] = field(default_factory=dict)


#: Metrics the filing does not print but that follow by arithmetic from rows it does print, as
#: ``metric -> (formula label, needed metrics, function of the per-period values, unit)``.
#:
#: WHY COMPOSE AT ALL. `derive.py` reads `pnl:Operating Profit` and `pnl:Tax %` as facts, and no Indian
#: annual report prints either: an Ind AS P&L stops at "Total Expenses", which bundles finance costs and
#: depreciation that the operating margin must exclude. Leaving them out would mean every return-on-capital
#: figure in the report — ROIC, incremental ROIC, OPM, interest coverage, CFO/EBITDA — kept resolving to
#: the grade-B screener even after the audited P&L was read, which is the exact complaint owner directive 1
#: makes.
#:
#: These are NOT estimates. Each is one subtraction or division over figures printed on a single audited
#: page, the locator names every line it consumed, and the formula travels with the fact so a reader can
#: re-derive it from the page. Nothing is imputed: a composition whose inputs are not all present is not
#: stored (owner directive 3).
COMPOSED_ROWS: Mapping[str, tuple[str, tuple[str, ...], Any, str]] = {
    # Operating expenses on the screener's definition: everything above the operating line. Total Expenses
    # in an Ind AS P&L includes finance costs and depreciation, and both sit below it.
    D.EXPENSES: (
        "Total Expenses - Finance Costs - Depreciation and Amortisation",
        (TOTAL_EXPENSES, D.INTEREST, D.DEPRECIATION),
        lambda v: v[TOTAL_EXPENSES] - v[D.INTEREST] - v[D.DEPRECIATION],
        "INR_cr",
    ),
    D.OPERATING_PROFIT: (
        "Revenue from Operations - (Total Expenses - Finance Costs - Depreciation)",
        (D.SALES, TOTAL_EXPENSES, D.INTEREST, D.DEPRECIATION),
        lambda v: v[D.SALES] - (v[TOTAL_EXPENSES] - v[D.INTEREST] - v[D.DEPRECIATION]),
        "INR_cr",
    ),
    D.TAX_PCT: (
        "Total Tax Expenses / Profit before tax",
        (TOTAL_TAX, D.PBT),
        lambda v: (v[TOTAL_TAX] / v[D.PBT]) if v[D.PBT] else None,
        "ratio",
    ),
    # Free cash flow on the definition the firm uses elsewhere: operating cash less what was spent on
    # property, plant and equipment. The cash-flow statement prints capex as a negative outflow.
    D.FCF: (
        "Net Cash Flows from Operating Activities - Purchase of property, plant and equipment",
        (D.CFO, CAPEX),
        lambda v: v[D.CFO] - abs(v[CAPEX]),
        "INR_cr",
    ),
    D.DIVIDEND_PAYOUT_PCT: (
        "Dividend Paid (cash flow) / Profit After Tax",
        (DIVIDEND_PAID, D.PAT),
        lambda v: (abs(v[DIVIDEND_PAID]) / v[D.PAT]) if v[D.PAT] else None,
        "ratio",
    ),
}


def _read_rows(
    filing: FilingSource,
) -> tuple[dict[str, ExtractedValue], dict[str, tuple[float, ...]], dict[str, str],
           dict[str, tuple[ExtractedValue, ...]]]:
    """Locate every `FILING_ROWS` metric on the filing's audited statements.

    Returns ``(anchor row per metric, canonical ₹-crore column values per metric, notes, parts)``. A
    `total` spec sums its parts column-wise and reports the first as the anchor row; `parts` keeps the
    rest so the locator can name every line the sum consumed.
    """
    rows: dict[str, ExtractedValue] = {}
    values: dict[str, tuple[float, ...]] = {}
    notes: dict[str, str] = {}
    parts_by_metric: dict[str, tuple[ExtractedValue, ...]] = {}
    for metric, spec in FILING_ROWS.items():
        found = find_statement_rows(filing.pages, spec.statement, spec.keywords, exclude=spec.exclude)
        if not found and spec.fallback:
            found = find_statement_rows(
                filing.pages, spec.statement, spec.fallback, exclude=spec.exclude)
        if spec.identity:
            anchor = find_statement_row(filing.pages, spec.statement, spec.identity)
            repaired, note = reconcile_to_identity(
                filing.pages, spec.statement, found[0] if found else None, anchor)
            if note:
                notes[metric] = note
            found = (repaired,) if repaired is not None else ()
        if spec.occurrence:
            found = found[spec.occurrence:]
        if not found:
            continue
        parts = found if spec.total else found[:1]

        # SCALE DISCIPLINE. Indian filings report in lakhs ("₹ In Lakhs" on the balance-sheet page) while
        # every screener fact in the store is in crore. This used to default the unit to `INR_cr` when the
        # page declared nothing, which stored each filing figure 100x too large — carrying the filing's
        # grade-A stamp, so it would be believed over the correct secondary value. A figure whose scale
        # cannot be established is therefore NOT stored: the check that needed it reports UNAVAILABLE with
        # the input named, which is the same treatment as an absent row and the honest one (ADR-0024).
        canonical: list[tuple[float, ...]] = []
        for part in parts:
            converted = tuple(
                (v if spec.unit != "INR_cr" else to_canonical_crore(v, part.unit_hint))
                for v in part.values[:_MAX_COLUMNS])
            if any(c is None for c in converted) or not converted:
                notes[metric] = (
                    f"{part.label!r} found at {part.locator} but the page declares no unit the pipeline "
                    f"can resolve ({part.unit_hint or 'no declaration'}), so its scale is unknown and it "
                    f"is not stored — a wrong scale is indistinguishable from a wrong number once it "
                    f"carries a grade-{filing.grade} provenance"
                )
                canonical = []
                break
            canonical.append(converted)  # type: ignore[arg-type]
        if not canonical:
            continue
        width = min(len(c) for c in canonical)
        rows[metric] = parts[0]
        parts_by_metric[metric] = tuple(parts)
        values[metric] = tuple(sum(c[i] for c in canonical) for i in range(width))
    return rows, values, notes, parts_by_metric


def register_filing_facts(
    store: FactStore, ticker: str, filing: FilingSource
) -> tuple[dict[str, ExtractedValue], tuple[str, ...], dict[str, str], dict[str, tuple[float, ...]]]:
    """Read the audited statements out of the filing and store them as grade-A, locator-bound facts.

    A row that is not present is simply not stored — the check that needed it then reports UNAVAILABLE
    with the input named, which is the behaviour owner directive 2 requires. Returns
    ``(rows, fact_ids, unresolved, values)``, where `unresolved` maps a metric to why a row that WAS found
    could not be trusted (an undeclared unit, or a total that fails the balance-sheet identity) and
    `values` carries the canonical ₹-crore columns — already summed and identity-checked, which the raw
    `rows` are not.
    """
    store.add_document(Document(
        doc_id=filing.doc_id, source_url=filing.source_url, sha256=filing.sha256,
        published_at=filing.published_at, fetched_at=filing.published_at,
        grade=filing.grade, extractor_version=filing.extractor_version,
    ))
    rows, values, unresolved, summed_parts = _read_rows(filing)
    periods = [filing.period] + ([filing.prior_period] if filing.prior_period else [])
    fact_ids: list[str] = []

    def store_fact(metric: str, period: str, value: float, unit: str, locator: str) -> None:
        fact_id = f"{filing.doc_id}:{metric}:{period}"
        store.add_fact(
            fact_id=fact_id, doc_id=filing.doc_id, ticker=ticker, metric=metric,
            period=period, value=value, unit=unit, locator=locator,
        )
        fact_ids.append(fact_id)

    for metric, columns in values.items():
        row = rows[metric]
        summed = summed_parts.get(metric, ())
        # A summed metric's locator names every line in the sum, not just the first, or the figure could
        # not be checked against the page.
        detail = (f" + {', '.join(p.locator for p in summed[1:])}" if len(summed) > 1 else "")
        for index, period in enumerate(periods):
            if index >= len(columns):
                break
            # The canonical scale is recorded, and the locator keeps the printed scale so a reader can
            # re-derive the figure from the page exactly as printed.
            store_fact(metric, period, columns[index], FILING_ROWS[metric].unit,
                       f"{row.locator}{detail} (as printed: {row.unit_hint})")

    for metric, (formula, needed, fn, unit) in COMPOSED_ROWS.items():
        for index, period in enumerate(periods):
            if not all(m in values and index < len(values[m]) for m in needed):
                continue
            computed = fn({m: values[m][index] for m in needed})
            if computed is None:
                continue
            store_fact(
                metric, period, computed, unit,
                # The locator names every printed line the composition consumed, in order, so the figure
                # can be re-derived from the page without trusting this code.
                "composed: " + formula + " @ " + ", ".join(f"{m}={rows[m].locator}" for m in needed),
            )
    return rows, tuple(fact_ids), unresolved, values


def walk_filing(store: FactStore, ticker: str, filing: FilingSource) -> FilingWalk:
    """Enumerate the notes, scan the mandated disclosures, and register the filing's figures as facts."""
    rows, fact_ids, unresolved, values = register_filing_facts(store, ticker, filing)
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
    # `values` is the single normalised source for both the fact store and the checks, so the two can no
    # longer drift: it is already in ₹ crore, already summed where a metric spans rows, and already
    # identity-checked where a total has an identity to satisfy.
    def canonical(metric: str, index: int) -> float | None:
        columns = values.get(metric)
        return None if columns is None or len(columns) <= index else columns[index]

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
    return FilingWalk(notes, external, fact_ids, caro, missing, rows,
                      reconcile_notes(filing, notes, values))


#: Note title keyword -> the statement line the note details. A note to the accounts is not free prose:
#: it is the breakup of one number on the face of the statements, and it must add back to that number.
#: Matching on the TITLE rather than the taxonomy category is deliberate — "COST OF MATERIAL CONSUMED"
#: and "OTHER EXPENSES" are both expense notes and detail entirely different lines.
#: Order matters — the FIRST key found in the title wins, so the specific precedes the general.
#: "CHANGES IN INVENTORIES OF FINISHED GOODS AND WORK-IN-PROGRESS" contains "inventories", and matching
#: that first sent a P&L movement note looking for the balance-sheet stock figure it does not carry.
NOTE_TIES: Mapping[str, str] = {
    "changes in inventories": INVENTORY_CHANGE,
    "property, plant": D.FIXED_ASSETS,
    "inventories": D.INVENTORY,
    "trade receivables": D.RECEIVABLES,
    "cash and cash equivalents": D.CASH,
    "other bank balances": D.OTHER_BANK,
    "equity share capital": D.EQUITY_CAPITAL,
    "other equity": D.RESERVES,
    "trade payables": PAYABLES,
    "revenue from operations": D.SALES,
    "other income": D.OTHER_INCOME,
    "cost of material": MATERIALS,
    "employee benefits expense": EMPLOYEE_COST,
    "finance costs": D.INTEREST,
    "depreciation": D.DEPRECIATION,
    "other expenses": OTHER_EXPENSES,
    "right of use": D.ROU_ASSETS,
    "non current financial assets - loans": D.NONCURRENT_LOANS,
    "current financial assets - loans": D.CURRENT_LOANS,
    "non current financial assets - other": D.OTHER_NONCURRENT_FIN_ASSETS,
    "current financial assets - other": D.OTHER_CURRENT_FIN_ASSETS,
    "other non current assets": D.OTHER_NONCURRENT_ASSETS,
    "other current assets": D.OTHER_CURRENT_ASSETS,
    "long term provisions": D.NONCURRENT_PROVISIONS,
    "short term provisions": D.CURRENT_PROVISIONS,
    "deferred tax": D.DEFERRED_TAX,
    "other financial liabilit": D.OTHER_FIN_LIABILITIES,
    "other current liabilities": D.OTHER_CURRENT_LIABILITIES,
    "short term borrowings": D.BORROWINGS,
}

#: How close a note's total must be to the statement line, in ₹ crore. Both are read off the same filing
#: at the same printed precision, so this is float noise, not a materiality band.
_TIE_TOLERANCE = 0.02


def reconcile_notes(
    filing: FilingSource,
    notes: Sequence[Note],
    values: Mapping[str, tuple[float, ...]],
) -> dict[int, tuple[str, str]]:
    """Check each note's body against the statement line it details. `{note number: (status, why)}`.

    THE TEST. A note to the accounts exists to break one figure on the face of the statements into its
    parts, so somewhere in its body that figure must appear. "Note 29 Other Income" must carry ₹3,165.21
    lakh; "Note 35 Other Expenses" must carry ₹32,175.62 lakh. This is the cheapest real reading of the
    notes available, and unlike enumeration it cannot be satisfied by a heading.

    Why a non-tie is `unknown` and not `flag`. A note that does not reconcile is far more likely to be a
    row this extractor could not read than a company misstating its own subtotal — the notes carry
    sub-totals, prior-year columns and continuation tables that a line-anchored reader will miss. Calling
    that a red flag would charge the company for our extraction, which owner directive (ADR-0022) rules
    out explicitly. It is reported as unread, with the figure that was being looked for.
    """
    out: dict[int, tuple[str, str]] = {}
    for note in notes:
        low = note.title.lower()
        metric = next((m for keyword, m in NOTE_TIES.items() if keyword in low), None)
        if metric is None or metric not in values or not values[metric]:
            continue
        expected = values[metric][0]
        printed: list[float] = []
        for line in note_body(filing.pages, notes, note):
            printed.extend(to_canonical_crore(v, _page_unit(filing, note.page)) or 0.0
                           for v in numbers_on_line(line))
        if any(abs(v - expected) <= _TIE_TOLERANCE for v in printed):
            out[note.number] = ("clean", (
                f"the note's own figures reconcile to the {metric} line on the face of the statements "
                f"(₹{expected:,.2f}cr) — the breakup was read, not merely listed"
            ))
        elif printed:
            out[note.number] = ("unknown", (
                f"the note carries {len(printed)} figures but none reconciles to the {metric} line it "
                f"details (₹{expected:,.2f}cr), so the breakup could not be tied to the statements — "
                f"treated as unread rather than as a discrepancy, because a line-anchored reader misses "
                f"continuation tables that the company did print"
            ))
        else:
            out[note.number] = ("unknown", (
                f"no figures could be read from this note's body, so its reconciliation to the "
                f"{metric} line was not attempted"
            ))
    return out


def _page_unit(filing: FilingSource, page: int) -> str:
    """The scale declared on the page a note starts on, so its figures compare with the statements."""
    from firm.adapters.base.tables import page_unit_hint

    return page_unit_hint(filing.pages[page - 1]) if 0 < page <= len(filing.pages) else ""


def disposition_notes(
    notes: Sequence[Note],
    evaluation: CheckEvaluation,
    *,
    disclosure_gaps_found: Sequence[str] = (),
    reconciliations: Mapping[int, tuple[str, str]] | None = None,
) -> tuple[NotesReview, tuple[NoteDisposition, ...]]:
    """Disposition every enumerated note from what actually read it (ADR-0017, extended by ADR-0038).

    Two independent readings, in priority order:

    1. **A deterministic forensic check on that note's category.** `flag` when one fired, `clean` when one
       ran and passed. This is the strongest reading and it wins.
    2. **The note's own reconciliation to the statement line it details** (`reconcile_notes`). A note whose
       figures add back to the face of the balance sheet or P&L has been read in the only sense that
       matters — the breakup was parsed and it ties.

    Anything else is `unknown` with the reason. Every note gets exactly one disposition, so coverage is
    100% by construction — and `substantive_share` is what stops that from being a free pass.
    """
    dispositions: list[NoteDisposition] = []
    ties = reconciliations or {}
    substantive = 0
    for note in notes:
        checks = NOTE_CHECKS.get(note.category, ())
        outcomes = {c: evaluation.outcome(c) for c in checks}
        fired = [c for c, o in outcomes.items() if o is CheckOutcome.FLAG]
        passed = [c for c, o in outcomes.items() if o is CheckOutcome.PASS]
        absent = [c for c, o in outcomes.items() if o is CheckOutcome.UNAVAILABLE]
        tie_status, tie_reason = ties.get(note.number, ("", ""))

        if fired:
            status, rationale = "flag", f"check(s) fired on this note: {', '.join(fired)}"
        elif passed:
            status, rationale = "clean", f"check(s) ran and passed: {', '.join(passed)}"
        elif tie_status == "clean":
            status, rationale = "clean", tie_reason
        elif absent:
            status, rationale = "unknown", (
                f"check(s) {', '.join(absent)} could not run — inputs not disclosed in the filing text"
                + (f"; {tie_reason}" if tie_reason else "")
            )
        elif tie_reason:
            status, rationale = "unknown", tie_reason
        else:
            status, rationale = "unknown", (
                f"no deterministic check covers category '{note.category}' and the note details no line "
                "on the face of the statements that it could be reconciled against; narrative review by "
                "an analyst or agent is required before this note can be called clean"
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
