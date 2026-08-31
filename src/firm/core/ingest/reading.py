"""Reading a filing: an LLM (or a human) proposes transcriptions, this module disposes (ADR-0046).

WHY THIS EXISTS — THE PC JEWELLER RUN
The hand-coded row-locator, on its second real company, stored 25 grade-A facts from the WRONG TABLE:
it matched the Ind AS transition note ("Effect of Ind AS adoption on the balance sheet as at 31 March
2016") instead of the FY17 balance sheet, mapped its `Previous GAAP | adjustment` columns to
`FY17 | FY16`, and the store then said total assets were −₹6.41cr — at grade A, past the identity check
(the wrong table also balances) and past the unit check (the wrong table also declares crores).
Statement location and column semantics are reading-comprehension problems; patterns answer them wrong
with full confidence.

THE SPLIT
A *proposer* — any LLM behind `core/llm/provider.py`, or a human answering a packet (ADR-0010) — reads
the extracted page text and claims: this page carries this audited statement (heading quoted verbatim),
these columns mean these fiscal periods (labels quoted verbatim), the unit declaration reads thus
(quoted), and each required metric's printed value is exactly this string. The proposer never computes,
never converts, never nets. This module then verifies every claim deterministically and registers only
what survives:

  V1  the statement heading appears verbatim on the claimed page, names the claimed fiscal year, and
      agrees with the claimed basis (a standalone heading must not say "consolidated");
  V2  the unit quote appears on the page and resolves in the unit vocabulary;
  V3  every period column's label quote appears on the page and names that period's calendar year —
      the check the transition note cannot pass ("Previous GAAP" and "adjustments" name no year);
  V4  every transcribed value appears verbatim on the claimed page — a proposer cannot invent a figure
      that survives literal search of the page it cited;
  V5  the balance sheet balances: total assets = total equity and liabilities;
  V6  transcribed P&L expense parts do not exceed the transcribed total (one-sided: the vocabulary is
      not exhaustive, so parts may be missing but may never overshoot);
  V7  CFO + CFI + CFF reconciles to the net change in cash when all four rows were transcribed;
  V9  the converted figure is a plausible ₹-crore magnitude (a backwards unit is caught here).

Cross-filing comparative quarantine (V8, ADR-0036) runs unchanged over the registered facts — it is a
control on documents, not on this module, and lives in `core/ingest/filings.py`.

Law 1 is intact: transcription is not authorship. The number stored is `parse(printed) × declared_unit`,
computed here, in trusted code, from a string proven to exist on an audited page.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from firm.adapters.base.tables import parse_number
from firm.core.facts.store import Document, FactStore

#: Unit vocabulary: declared unit id -> multiplier to canonical ₹ crore. Extends `tables._TO_CRORE` with
#: plain rupees, the scale every pre-2016 Indian filing prints ("`" over a column of ten-digit figures).
#: PC Jeweller FY13: revenue 40,184,193,574 plain rupees = ₹4,018.42cr.
UNIT_TO_CRORE: Mapping[str, float] = {"INR_cr": 1.0, "INR_lakh": 1e-2, "INR": 1e-7}

#: A converted figure beyond this magnitude (₹ crore, absolute) is a unit error, not a fact. No Indian
#: listed company has a ₹1-crore-crore balance sheet row.
PLAUSIBLE_CRORE_MAX = 1e7

#: Per-share metrics are printed in rupees regardless of the statement's money scale — an EPS of 21.13
#: on a "₹ in lacs" statement is ₹21.13, and scaling it by the statement unit corrupts it (caught live by
#: the FY15/FY16 cross-filing quarantine: 21.13 lakh-scaled to 0.21 against the next year's 21.13).
PER_SHARE_METRICS = frozenset({"pnl:EPS in Rs"})

#: Verification-only metric ids: transcribed so the identities can be checked, never registered as facts.
VERIFY_TOTAL_EQ_LIAB = "verify:Total Equity and Liabilities"
VERIFY_NET_CHANGE_IN_CASH = "verify:Net Change in Cash"
VERIFICATION_ONLY = frozenset({VERIFY_TOTAL_EQ_LIAB, VERIFY_NET_CHANGE_IN_CASH})

#: Rows that make up "total expenses" for the one-sided V6 sum check.
_PNL_EXPENSE_PARTS = (
    "pnl:Cost of Materials Consumed", "pnl:Purchases of Stock-in-Trade", "pnl:Changes in Inventories",
    "pnl:Employee Benefits", "pnl:Interest", "pnl:Depreciation", "pnl:Other Expenses",
)

#: Metric families that are FLOWS (measured over a period) rather than STOCKS (measured at an instant).
#: The distinction is what makes a stub period safe to read: a nine-month P&L is not an annual P&L, but
#: the balance sheet closing it is a perfectly ordinary balance sheet.
FLOW_PREFIXES = ("pnl:", "cashflow:")

#: How a filing states a period's length in its own words. Symphony changed its year-end from June to
#: March and filed a NINE-MONTH transition period labelled "Nine months ended 31/03/2016"; the firm read
#: it as FY16 and would have compared it to twelve-month years on both sides — revenue "fell 23%" when it
#: grew 2.7%, and receivable days inflated 33%. A period label is not a period.
_MONTH_WORDS: Mapping[str, int] = {
    "twelve": 12, "eleven": 11, "ten": 10, "nine": 9, "eight": 8, "seven": 7,
    "six": 6, "five": 5, "four": 4, "three": 3, "two": 2, "one": 1,
}
_MONTHS_WORD = re.compile(
    rf"\b({'|'.join(_MONTH_WORDS)})\s+months?\b", re.IGNORECASE)
_MONTHS_DIGIT = re.compile(r"\b(\d{1,2})\s+months?\b", re.IGNORECASE)
_FULL_YEAR = re.compile(r"\byear\s+ended", re.IGNORECASE)


#: How a filing writes the month a period ends in: '30/06/2015', '30th June, 2015', 'June 30, 2015'.
_MONTH_NAMES: Mapping[int, tuple[str, ...]] = {
    1: ("january", "jan"), 2: ("february", "feb"), 3: ("march", "mar"), 4: ("april", "apr"),
    5: ("may",), 6: ("june", "jun"), 7: ("july", "jul"), 8: ("august", "aug"),
    9: ("september", "sep", "sept"), 10: ("october", "oct"), 11: ("november", "nov"),
    12: ("december", "dec"),
}


def _names_month_and_year(text: str, ends: date) -> bool:
    """True when `text` names the month and year `ends` falls in, spelled or numeric.

    Numeric forms are matched as a whole date ('30/06/2015', '2015-06-30') so that a stray '06'
    elsewhere in a quote cannot vouch for a June year-end."""
    if str(ends.year) not in text:
        return False
    lowered = text.casefold()
    if any(word in lowered for word in _MONTH_NAMES[ends.month]):
        return True
    y, m, d = ends.year, ends.month, ends.day
    numeric = (
        rf"\b{d:02d}\s*[/.-]\s*{m:02d}\s*[/.-]\s*{y}\b",      # 30/06/2015
        rf"\b{y}\s*[/.-]\s*{m:02d}\s*[/.-]\s*{d:02d}\b",      # 2015-06-30
        rf"\b{d}\s*[/.-]\s*{m}\s*[/.-]\s*{y}\b",              # 30/6/2015
    )
    return any(re.search(pat, text) for pat in numeric)


def months_stated(text: str) -> int | None:
    """The period length the text states UNAMBIGUOUSLY in its own words, else None.

    'Nine months ended 31/03/2016' -> 9 · 'for the year ended 31 March 2018' -> 12 · 'As at 31/03/2018'
    -> None (a balance-sheet column states an instant, not a length, and correctly so).

    None is also the answer when the text states TWO different lengths, which is not a corner case: a
    transition filing prints its header across two lines ("Year ended  Nine months ended" / "31/03/2017
    31/03/2016"), so any quote long enough to carry a column's year may also carry its neighbour's
    length. Contradicting the proposer requires an unambiguous contradiction; where the words are
    ambiguous the declared `months` stands and the reader can check the locator."""
    found = {_MONTH_WORDS[m.group(1).lower()] for m in _MONTHS_WORD.finditer(text)}
    found |= {int(m.group(1)) for m in _MONTHS_DIGIT.finditer(text)}
    if not found and _FULL_YEAR.search(text):
        found = {12}
    elif found and _FULL_YEAR.search(text):
        found |= {12}
    return found.pop() if len(found) == 1 else None


_NIL = re.compile(r"^(?:[-–—]|NIL)$", re.IGNORECASE)
_YEAR = re.compile(r"(20\d{2}|19\d{2})")


def _normalise(text: str) -> str:
    """Whitespace-collapsed, casefolded — the small-caps fonts scramble case ('casH fLoW statEmEnt')."""
    return re.sub(r"\s+", " ", text).casefold().strip()


def _fy_year(period: str) -> str | None:
    """'FY17' -> '2017' (the Indian fiscal year is named for the calendar year it ends in)."""
    m = re.fullmatch(r"FY(\d{2})", period.strip())
    return f"20{m.group(1)}" if m else None


@dataclass(frozen=True)
class ProposedColumn:
    """One figure column and what the proposer says it means. `period` is None for a column that is not
    a reporting period (a GAAP-transition adjustment, a percentage column) — such columns exist so the
    proposer can be honest about the table's shape, and their figures are never registered."""

    period: str | None          # 'FY17' | None
    label_quote: str            # verbatim from the page, e.g. 'year ended 31 march 2017'
    #: Months this column covers, when the proposer states it. None means "read it from the words":
    #: the column label first, then the statement heading. A flow column whose length cannot be
    #: established either way is refused rather than assumed to be a year (V3b).
    months: int | None = None
    #: ISO date the column's period ENDS ('2015-06-30'), when the proposer states it. Verified against
    #: the label's own words (V3c): the label must name that month and year. Symphony closed its books
    #: on 30 June until FY15 and on 31 March after, so `FY15` means different twelve months for it than
    #: for almost every other Indian company, and a growth rate spanning the change is not a growth rate.
    ends: str | None = None


@dataclass(frozen=True)
class ProposedFigure:
    metric: str                 # canonical id ('pnl:Sales') or a verify:* id
    period: str                 # must be one of the statement's declared column periods
    value_printed: str          # EXACTLY as printed: '8,104.75', '(405.43)', '40,184,193,574', '-'
    page: int                   # 1-based page carrying this row
    row_label: str              # as printed, for the locator


@dataclass(frozen=True)
class ProposedStatement:
    statement: str              # 'balance_sheet' | 'pnl' | 'cashflow'
    basis: str                  # 'standalone' | 'consolidated'
    period: str                 # the filing's own fiscal year, e.g. 'FY17'
    pages: tuple[int, ...]      # 1-based pages of the statement
    heading_quote: str          # verbatim heading, e.g. 'Balance Sheet as at 31 March 2017'
    unit_quote: str             # verbatim declaration, e.g. '(` in crores)'
    unit: str                   # key of UNIT_TO_CRORE
    columns: tuple[ProposedColumn, ...]
    figures: tuple[ProposedFigure, ...]


@dataclass(frozen=True)
class Violation:
    rule: str                   # 'V1_heading' | 'V2_unit' | 'V3_column' | 'V4_value' | 'V5_identity' | ...
    statement: str              # '{basis} {statement}'
    detail: str


@dataclass(frozen=True)
class VerifiedFigure:
    metric: str
    period: str
    value_crore: float          # canonical scale
    page: int
    row_label: str
    value_printed: str
    unit: str                   # the DECLARED unit, kept so a reader can re-derive from the page
    #: Months the figure's period covers — 12 for an ordinary year, 9 for a transition stub, None for a
    #: stock figure (a balance sheet states an instant, not a length).
    period_months: int | None = None
    #: ISO date the period ends, when the filing stated it and the verifier confirmed it; '' otherwise.
    period_end: str = ""


@dataclass(frozen=True)
class StatementReading:
    """One statement's outcome: either its verified figures, or the violations that refused it."""

    statement: str
    basis: str
    heading_quote: str
    figures: tuple[VerifiedFigure, ...] = ()
    violations: tuple[Violation, ...] = ()

    @property
    def verified(self) -> bool:
        return not self.violations


def _letters(text: str) -> str:
    """Alphanumerics only, lowercased. Display fonts scramble both case and intra-word spacing —
    'ConsoliDA teD B Al AnCe sHeet' is how a real heading survives text extraction — so the SEMANTIC
    checks (which statement, which year, which basis) compare on letters alone. Figure search (V4) never
    uses this: commas and parentheses are load-bearing there."""
    return re.sub(r"[^0-9a-z]", "", text.casefold())


def _find_on_pages(quote: str, pages: Sequence[str], page_numbers: Sequence[int]) -> bool:
    needle = _normalise(quote)
    if not needle:
        return False
    return any(
        needle in _normalise(pages[n - 1]) for n in page_numbers if 1 <= n <= len(pages)
    )


def _find_letters_on_pages(quote: str, pages: Sequence[str], page_numbers: Sequence[int]) -> bool:
    needle = _letters(quote)
    if not needle:
        return False
    return any(
        needle in _letters(pages[n - 1]) for n in page_numbers if 1 <= n <= len(pages)
    )


def _tolerance(*values: float) -> float:
    """Reconciliation slack: rounding on each printed row, scaled to the figures being tied."""
    scale = max((abs(v) for v in values), default=0.0)
    return max(0.5, 0.002 * scale)


def verify_statement(stmt: ProposedStatement, pages: Sequence[str]) -> StatementReading:
    """Every ADR-0046 check against the actual page text. A structural failure (V1/V2/V3/V5/V6/V7)
    refuses the whole statement — if the table or its columns are misidentified, every figure in it is
    suspect; a per-figure failure (V4/V9) refuses that figure alone."""
    name = f"{stmt.basis} {stmt.statement}"
    violations: list[Violation] = []

    # V1 — the heading exists, names the fiscal year, and agrees with the claimed basis.
    if not _find_letters_on_pages(stmt.heading_quote, pages, stmt.pages[:1] or stmt.pages):
        violations.append(Violation("V1_heading", name,
                                    f"heading {stmt.heading_quote!r} not found on p.{stmt.pages[:1]}"))
    year = _fy_year(stmt.period)
    if year and year not in _letters(stmt.heading_quote):
        violations.append(Violation(
            "V1_heading", name,
            f"heading {stmt.heading_quote!r} does not name {year} — wrong year's statement, or a "
            "transition/restatement table"))
    heading_letters = _letters(stmt.heading_quote)
    if stmt.basis == "standalone" and "consolidated" in heading_letters:
        violations.append(Violation("V1_heading", name, "claimed standalone but heading says consolidated"))
    if stmt.basis == "consolidated" and "consolidated" not in heading_letters:
        violations.append(Violation("V1_heading", name, "claimed consolidated but heading does not say so"))

    # V2 — the unit declaration exists and is in the vocabulary.
    if stmt.unit not in UNIT_TO_CRORE:
        violations.append(Violation("V2_unit", name, f"unknown unit {stmt.unit!r}"))
    if not _find_on_pages(stmt.unit_quote, pages, stmt.pages):
        violations.append(Violation("V2_unit", name,
                                    f"unit declaration {stmt.unit_quote!r} not found on pages {stmt.pages}"))

    # V3 — every period column's label exists on the page and names that period's calendar year.
    # V3b — and, for a FLOW statement, its length is established and agrees with the filing's own words.
    is_flow = stmt.statement in ("pnl", "cashflow")
    heading_months = months_stated(stmt.heading_quote)
    declared_periods: set[str] = set()
    months_by_period: dict[str, int] = {}
    ends_by_period: dict[str, str] = {}
    for col in stmt.columns:
        if col.period is None:
            continue
        declared_periods.add(col.period)
        if is_flow:
            # Precedence: what the proposer declared, then the column's own words, then the heading's.
            # The column beats the heading because a transition filing says "year ended" at the top and
            # "Nine months ended" over the stub column — which is exactly the case this rule exists for.
            stated = months_stated(col.label_quote)
            effective = col.months if col.months is not None else (
                stated if stated is not None else heading_months)
            if effective is None:
                violations.append(Violation(
                    "V3b_period_length", name,
                    f"column {col.label_quote!r} ({col.period}): neither the column nor the heading "
                    "states a period length, so it cannot be assumed to be a year — declare `months`"))
            else:
                if col.months is not None and stated is not None and stated != col.months:
                    violations.append(Violation(
                        "V3b_period_length", name,
                        f"column {col.label_quote!r} declares {col.months} months but its own words say "
                        f"{stated}"))
                months_by_period[col.period] = effective
        col_year = _fy_year(col.period)
        if col_year is None:
            violations.append(Violation("V3_column", name, f"unparseable period {col.period!r}"))
            continue
        if col_year not in _letters(col.label_quote):
            violations.append(Violation(
                "V3_column", name,
                f"column {col.label_quote!r} claimed as {col.period} does not name {col_year} — "
                "a column that names no year is not a reporting period"))
        if not _find_letters_on_pages(col.label_quote, pages, stmt.pages):
            violations.append(Violation("V3_column", name,
                                        f"column label {col.label_quote!r} not found on pages {stmt.pages}"))
        # V3c — a declared period end must be one the label actually names, in month and year.
        if col.ends is not None:
            try:
                ends = date.fromisoformat(col.ends)
            except ValueError:
                violations.append(Violation("V3c_period_end", name,
                                            f"column {col.period}: unparseable end date {col.ends!r}"))
            else:
                if not _names_month_and_year(col.label_quote, ends) and not _names_month_and_year(
                        stmt.heading_quote, ends):
                    violations.append(Violation(
                        "V3c_period_end", name,
                        f"column {col.label_quote!r} claimed to end {col.ends} but neither it nor the "
                        f"heading names {ends:%B %Y} — a period end is read, never assumed"))
                elif str(ends.year) != col_year:
                    violations.append(Violation(
                        "V3c_period_end", name,
                        f"column {col.period} ends {col.ends}, which is not in {col_year}"))
                else:
                    ends_by_period[col.period] = col.ends

    # V4 + V9 — each figure: printed string on its page, parseable, plausible once converted.
    factor = UNIT_TO_CRORE.get(stmt.unit)
    verified: list[VerifiedFigure] = []
    by_metric: dict[tuple[str, str], float] = {}
    for fig in stmt.figures:
        if fig.period not in declared_periods:
            violations.append(Violation("V3_column", name,
                                        f"{fig.metric} {fig.period}: period not among declared columns"))
            continue
        printed = fig.value_printed.strip()
        if _NIL.fullmatch(printed):
            value = 0.0
        else:
            parsed = parse_number(printed)
            if parsed is None:
                violations.append(Violation("V4_value", name,
                                            f"{fig.metric} {fig.period}: unparseable {printed!r}"))
                continue
            if not _find_on_pages(printed, pages, (fig.page,)):
                violations.append(Violation(
                    "V4_value", name,
                    f"{fig.metric} {fig.period}: {printed!r} does not appear on p.{fig.page}"))
                continue
            value = parsed
        if factor is None:
            continue  # already a V2 violation; nothing sane to convert with
        crore = value if fig.metric in PER_SHARE_METRICS else value * factor
        if abs(crore) > PLAUSIBLE_CRORE_MAX:
            violations.append(Violation("V9_plausibility", name,
                                        f"{fig.metric} {fig.period}: {crore:,.0f}cr is not a plausible "
                                        f"magnitude — unit {stmt.unit!r} is suspect"))
            continue
        by_metric[(fig.metric, fig.period)] = crore
        verified.append(VerifiedFigure(fig.metric, fig.period, crore, fig.page, fig.row_label,
                                       printed, stmt.unit, months_by_period.get(fig.period),
                                       ends_by_period.get(fig.period, "")))

    # V5 — the balance sheet balances, for every period figures were actually transcribed for. A period
    # whose column was declared but not transcribed is simply absent — declaring the table's shape
    # honestly must not oblige the proposer to read every column.
    transcribed_periods = sorted({p for (_, p) in by_metric})
    if stmt.statement == "balance_sheet":
        for period in transcribed_periods:
            assets = by_metric.get(("balance_sheet:Total Assets", period))
            eq_liab = by_metric.get((VERIFY_TOTAL_EQ_LIAB, period))
            if assets is None or eq_liab is None:
                violations.append(Violation(
                    "V5_identity", name,
                    f"{period}: both totals must be transcribed to verify the identity "
                    f"(assets={'present' if assets is not None else 'missing'}, "
                    f"equity+liabilities={'present' if eq_liab is not None else 'missing'})"))
            elif abs(assets - eq_liab) > _tolerance(assets, eq_liab):
                violations.append(Violation(
                    "V5_identity", name,
                    f"{period}: total assets {assets:,.2f} ≠ total equity+liabilities {eq_liab:,.2f}"))

    # V6 — transcribed expense parts may fall short of the total (vocabulary is not exhaustive) but may
    # never overshoot it.
    if stmt.statement == "pnl":
        for period in transcribed_periods:
            total = by_metric.get(("pnl:Total Expenses", period))
            parts = [by_metric[(m, period)] for m in _PNL_EXPENSE_PARTS if (m, period) in by_metric]
            if total is not None and len(parts) >= 3 and sum(parts) > total + _tolerance(total):
                violations.append(Violation(
                    "V6_pnl_sum", name,
                    f"{period}: transcribed expense parts sum {sum(parts):,.2f} > total {total:,.2f}"))

    # V7 — the cash-flow statement reconciles to its own net-change row.
    if stmt.statement == "cashflow":
        for period in transcribed_periods:
            legs = [by_metric.get((m, period)) for m in (
                "cashflow:Cash from Operating Activity", "cashflow:Cash from Investing Activity",
                "cashflow:Cash from Financing Activity")]
            net = by_metric.get((VERIFY_NET_CHANGE_IN_CASH, period))
            if net is not None and all(v is not None for v in legs):
                total = sum(v for v in legs if v is not None)
                if abs(total - net) > _tolerance(total, net):
                    violations.append(Violation(
                        "V7_cashflow", name,
                        f"{period}: CFO+CFI+CFF {total:,.2f} ≠ net change {net:,.2f}"))

    if violations:
        return StatementReading(stmt.statement, stmt.basis, stmt.heading_quote,
                                violations=tuple(violations))
    return StatementReading(stmt.statement, stmt.basis, stmt.heading_quote, figures=tuple(verified))


@dataclass(frozen=True)
class FilingReading:
    """A whole filing's verified reading: what may be registered, and what was refused, with reasons."""

    doc_id: str
    statements: tuple[StatementReading, ...]

    @property
    def violations(self) -> tuple[Violation, ...]:
        return tuple(v for s in self.statements for v in s.violations)


def verify_proposal(
    doc_id: str, statements: Sequence[ProposedStatement], pages: Sequence[str]
) -> FilingReading:
    return FilingReading(doc_id, tuple(verify_statement(s, pages) for s in statements))


def register_reading(
    store: FactStore,
    ticker: str,
    reading: FilingReading,
    *,
    source_url: str,
    published_at,
    sha256: str = "",
    grade: str = "A",
    preferred_basis: str = "consolidated",
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Store every verified figure of ONE basis as locator-bound facts.

    One basis per filing, because the store keys a metric-period to a single series (PLAN assumption 1:
    consolidated is the default; standalone only when consolidated was not verified). Verification-only
    rows are never stored.

    A FLOW figure from a period that is not twelve months is **not stored** (and is returned in
    `skipped_stub_flows` so the caller can publish the reason). Symphony's nine-month transition period
    is why: stored as if it were a year, it made revenue "fall 23%" when it grew 2.7%, inflated
    receivable days 33%, and would have fired `receivables_divergent` on a clean compounder. Annualising
    it would be estimating a number that carries a forensic conclusion, which owner directive 3 forbids;
    a hole the checks report as UNAVAILABLE is the honest alternative. STOCK figures from the same
    filing are stored normally — a balance sheet closing a stub period is an ordinary balance sheet.

    Returns `(fact_ids, skipped_stub_flows)`.
    """
    chosen = [s for s in reading.statements if s.verified and s.basis == preferred_basis]
    if not chosen:
        fallback = "standalone" if preferred_basis == "consolidated" else "consolidated"
        chosen = [s for s in reading.statements if s.verified and s.basis == fallback]
    if not chosen:
        return (), ()

    store.add_document(Document(
        doc_id=reading.doc_id, source_url=source_url, sha256=sha256,
        published_at=published_at, fetched_at=published_at,
        grade=grade, extractor_version="llm-read@1.0.0+verified",
    ))
    fact_ids: list[str] = []
    skipped: list[str] = []

    def write(metric: str, period: str, value: float, locator: str, period_end: str = "") -> None:
        fact_id = f"{reading.doc_id}:{metric}:{period}"
        unit = "INR" if metric in PER_SHARE_METRICS else "INR_cr"
        store.add_fact(fact_id=fact_id, doc_id=reading.doc_id, ticker=ticker, metric=metric,
                       period=period, value=value, unit=unit, locator=locator, period_end=period_end)
        fact_ids.append(fact_id)

    for stmt in chosen:
        for fig in stmt.figures:
            if fig.metric in VERIFICATION_ONLY:
                continue
            if (fig.metric.startswith(FLOW_PREFIXES) and fig.period_months is not None
                    and fig.period_months != 12):
                skipped.append(
                    f"{fig.metric} {fig.period}: the filing reports it over {fig.period_months} months, "
                    "not a year — not comparable with annual figures, and not annualised")
                continue
            write(fig.metric, fig.period, fig.value_crore,
                  f"p.{fig.page} '{fig.row_label}' (as printed: {fig.value_printed} {fig.unit}; "
                  f"{stmt.basis}; {stmt.heading_quote})", fig.period_end)
        # Composed in trusted code, never by the proposer (ADR-0037 practice): a total the filing
        # prints only as parts is the sum of the printed rows, its locator naming both so a reader can
        # redo the addition. Borrowings (non-current + current) and trade payables (the Schedule III
        # micro/other split every modern filing uses) are the two such totals.
        if stmt.statement == "balance_sheet":
            parts = {(f.metric, f.period): f for f in stmt.figures}
            periods = {f.period for f in stmt.figures}
            # A total the filing prints only as parts. The lender rule is a THREE-part sum and is
            # tried first: a lender that also prints a current/non-current split would otherwise
            # compose the wrong total from the wrong two rows.
            composed = (
                ("balance_sheet:Borrowings",
                 ("balance_sheet:Debt Securities",
                  "balance_sheet:Borrowings (Other than Debt Securities)",
                  "balance_sheet:Subordinated Liabilities")),
                ("balance_sheet:Borrowings",
                 ("balance_sheet:Non-Current Borrowings", "balance_sheet:Current Borrowings")),
                ("balance_sheet:Trade Payables",
                 ("balance_sheet:Trade Payables (Micro)", "balance_sheet:Trade Payables (Other)")),
            )
            for period in sorted(periods):
                done: set[str] = set()
                for total_metric, part_metrics in composed:
                    if total_metric in done or (total_metric, period) in parts:
                        continue
                    found = [parts.get((m, period)) for m in part_metrics]
                    if any(f is None for f in found):
                        continue
                    write(total_metric, period, sum(f.value_crore for f in found),
                          " + ".join(f"p.{f.page} '{f.row_label}'" for f in found)
                          + f" (composed: {' + '.join(f.value_printed for f in found)} "
                            f"{found[0].unit}; {stmt.basis})", found[0].period_end)
                    done.add(total_metric)
    return tuple(fact_ids), tuple(skipped)


# --------------------------------------------------------------------------------------------------
# Notes enumeration by reading (the line-by-line rule, owner directive 6).
# --------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class ProposedNote:
    """One note to the accounts, as the proposer read it: '36a', its printed title, its 1-based page."""

    label: str
    title: str
    page: int


def verify_notes(proposals: Sequence[ProposedNote], pages: Sequence[str]) -> tuple[list, list[Violation]]:
    """Verify a proposed note enumeration and return `(notes, violations)` — `notes` are
    `adapters.india.notes.Note` objects ready for `walk_filing(notes_override=...)`.

    The pattern enumerator on PC Jeweller FY17 "found" ten notes that were transition-note sub-items and
    AGM paragraphs; a proposer reads the real 1-52. The checks mirror what typography cannot fake:

      N1  the note's title appears on its claimed page (letters-only — display fonts scramble spacing);
      N2  labels are unique (sub-notes '45a'/'45b' are distinct; a duplicate is a misread);
      N3  pages never decrease in listed order — notes print in sequence (the ADR-0038 insight);
      N4  numeric parts never decrease either, for the same reason.

    Any violation refuses the WHOLE enumeration: coverage arithmetic over a partly-wrong note list would
    be theatre with a denominator."""
    from firm.adapters.india.notes import Note

    violations: list[Violation] = []
    seen: set[str] = set()
    prev_page, prev_num = 0, 0
    notes: list[Note] = []
    for p in proposals:
        m = re.fullmatch(r"(\d{1,3})([a-z]?)", p.label.strip(), re.IGNORECASE)
        if m is None:
            violations.append(Violation("N2_label", "notes", f"unparseable note label {p.label!r}"))
            continue
        number, suffix = int(m.group(1)), m.group(2).lower()
        if p.label in seen:
            violations.append(Violation("N2_label", "notes", f"duplicate note label {p.label!r}"))
        seen.add(p.label)
        if not _find_letters_on_pages(p.title, pages, (p.page,)):
            violations.append(Violation(
                "N1_title", "notes", f"note {p.label} title {p.title!r} not found on p.{p.page}"))
        if p.page < prev_page:
            violations.append(Violation(
                "N3_order", "notes",
                f"note {p.label} on p.{p.page} before p.{prev_page} — notes print in sequence"))
        if number < prev_num:
            violations.append(Violation(
                "N4_order", "notes", f"note {p.label} number falls after {prev_num}"))
        prev_page, prev_num = p.page, number
        notes.append(Note(number=number, title=p.title, page=p.page, line=1, suffix=suffix))
    if violations:
        return [], violations
    return notes, []


@dataclass(frozen=True)
class ProposedRelatedParty:
    """The proposer's reading of the Ind AS 24 note: where it is, what channels it discloses, and the
    KMP compensation total exactly as printed. `categories` uses the `notes_content` vocabulary
    (remuneration, rent, dividend, loans_given, guarantees, sales, purchases, loans_taken, ...)."""

    note_label: str
    page: int
    title_quote: str            # verbatim heading, e.g. 'note: 37 related party transactions:'
    categories: tuple[str, ...]
    kmp_remuneration_printed: str | None = None   # e.g. '6.95' — must appear on a claimed page
    remuneration_page: int | None = None


def verify_related_party(proposal: ProposedRelatedParty, pages: Sequence[str]):
    """Verify and convert to a `RelatedPartySummary` for `walk_filing(related_party_override=...)`.

    Same discipline as statements: the title must sit on the claimed page, the printed remuneration
    figure must be found verbatim on its page. Categories are the proposer's classification of channels
    the note discloses — a judgment call the tri-state downstream treats as 'the note was read'."""
    from firm.adapters.india.notes_content import RelatedPartySummary

    violations: list[Violation] = []
    if not _find_letters_on_pages(proposal.title_quote, pages, (proposal.page,)):
        violations.append(Violation("N1_title", "related_party",
                                    f"title {proposal.title_quote!r} not found on p.{proposal.page}"))
    remuneration = None
    if proposal.kmp_remuneration_printed is not None:
        page = proposal.remuneration_page or proposal.page
        if not _find_on_pages(proposal.kmp_remuneration_printed, pages, (page,)):
            violations.append(Violation(
                "V4_value", "related_party",
                f"KMP remuneration {proposal.kmp_remuneration_printed!r} not found on p.{page}"))
        else:
            remuneration = parse_number(proposal.kmp_remuneration_printed)
    if violations:
        return None, violations
    m = re.match(r"(\d+)", proposal.note_label)
    return RelatedPartySummary(
        located=True,
        note_number=int(m.group(1)) if m else None,
        page=proposal.page,
        categories=frozenset(proposal.categories),
        remuneration_cr=remuneration,
    ), []


def notes_from_json(text: str) -> list[ProposedNote]:
    """Parse a proposer's notes answer: {"notes": [{"label", "title", "page"}, ...]}."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as err:
        raise ValueError(f"notes proposal is not valid JSON: {err}") from err
    if not isinstance(data, dict) or not isinstance(data.get("notes"), list):
        msg = "notes proposal must be an object with a 'notes' list"
        raise TypeError(msg)
    return [ProposedNote(label=str(n["label"]), title=str(n["title"]), page=int(n["page"]))
            for n in data["notes"]]


# --------------------------------------------------------------------------------------------------
# The reading packet — what any proposer receives (an API model, or a human/Claude answering by hand).
# --------------------------------------------------------------------------------------------------

#: Metric vocabulary handed to the proposer: canonical id -> what to look for on the statement. Rows the
#: filing prints that are not in this vocabulary are simply not transcribed; a missing row becomes an
#: honest UNAVAILABLE downstream, never a guess.
READING_VOCABULARY: Mapping[str, str] = {
    "pnl:Sales": "revenue from operations (exclude other income)",
    "pnl:Other Income": "other income",
    "pnl:Cost of Materials Consumed": "cost of materials consumed",
    "pnl:Purchases of Stock-in-Trade": "purchases of stock-in-trade / traded goods — material for an "
                                       "outsourced-manufacturing model, where most cost of goods is "
                                       "bought finished rather than made",
    "pnl:Changes in Inventories": "changes in inventories of finished goods / WIP / stock-in-trade",
    "pnl:Employee Benefits": "employee benefits expense",
    "pnl:Interest": "finance costs",
    "pnl:Depreciation": "depreciation and amortisation expense",
    "pnl:Other Expenses": "other expenses",
    "pnl:Total Expenses": "total expenses",
    "pnl:Profit before tax": "profit before tax",
    "pnl:Total Tax": "total tax expense",
    "pnl:Net Profit": "profit for the year (after tax; before OCI)",
    "pnl:EPS in Rs": "basic earnings per share, in rupees",
    "balance_sheet:Total Assets": "total assets",
    VERIFY_TOTAL_EQ_LIAB: "total equity and liabilities (verification only)",
    "balance_sheet:Equity Capital": "equity share capital",
    "balance_sheet:Reserves": "other equity / reserves and surplus",
    "balance_sheet:Non-Current Borrowings": "long-term / non-current borrowings",
    "balance_sheet:Current Borrowings": "short-term / current borrowings",
    # A lender's statements have a different shape: the loan book IS the asset base, credit cost is an
    # expense line, and borrowings come in three named kinds rather than a current/non-current split.
    "balance_sheet:Loans": "loans (a lender's loan book, net of impairment allowance) — the financial "
                           "asset, NOT loans given to employees or related parties",
    "balance_sheet:Debt Securities": "debt securities issued (lender)",
    "balance_sheet:Borrowings (Other than Debt Securities)": "borrowings other than debt securities "
                                                             "(lender)",
    "balance_sheet:Subordinated Liabilities": "subordinated liabilities (lender)",
    "pnl:Interest Income": "interest income (lender revenue line)",
    "pnl:Impairment on Financial Instruments": "impairment on financial instruments / provisions and "
                                               "write-offs / expected credit loss charge for the year — "
                                               "a lender's credit cost",
    "balance_sheet:Fixed Assets": "property, plant and equipment (tangible assets, net block)",
    "balance_sheet:CWIP": "capital work-in-progress",
    "balance_sheet:Inventories": "inventories",
    "balance_sheet:Trade Receivables": "trade receivables (current)",
    "balance_sheet:Cash Equivalents": "cash and cash equivalents",
    "balance_sheet:Other Bank Balances": "bank balances other than cash and cash equivalents",
    "balance_sheet:Trade Payables": "trade payables, when printed as ONE total row",
    "balance_sheet:Trade Payables (Micro)": "trade payables — dues of micro and small enterprises "
                                            "(when the filing splits the Schedule III rows)",
    "balance_sheet:Trade Payables (Other)": "trade payables — dues of creditors other than micro and "
                                            "small enterprises",
    "cashflow:Cash from Operating Activity": "net cash from operating activities",
    "cashflow:Cash from Investing Activity": "net cash used in / from investing activities",
    "cashflow:Cash from Financing Activity": "net cash from / used in financing activities",
    VERIFY_NET_CHANGE_IN_CASH: "net increase/(decrease) in cash and cash equivalents (verification only)",
}

READING_INSTRUCTIONS = """\
You are transcribing an audited Indian annual report. You NEVER compute, convert, net, or estimate a
number — you transcribe printed strings and quote printed labels, and a deterministic verifier will
check every claim against the page text, so any figure you author rather than transcribe will be
refused and logged.

For each audited statement present (balance sheet, statement of profit and loss, cash flow statement;
standalone AND consolidated where both exist), report:
- `statement`: balance_sheet | pnl | cashflow;  `basis`: standalone | consolidated
- `period`: the filing's own fiscal year (e.g. FY17 for the year ended 31 March 2017)
- `pages`: the 1-based page number(s) of the statement itself (not summaries, not transition notes,
  not "financial highlights")
- `heading_quote`: the statement's heading verbatim, including the date it names
- `unit_quote`: the printed unit declaration verbatim; `unit`: INR_cr | INR_lakh | INR (plain rupees)
- `columns`: every figure column, each with its `label_quote` verbatim and its `period` (FY label), or
  period null for a column that is NOT a reporting period (a GAAP-transition adjustment, a % column).
  For a profit-and-loss or cash-flow column also give `months` (12 for a full year, 9 for a transition
  stub — say what the filing says, never what you expect) and `ends` as the ISO date the period closes
  ("2015-06-30"). Indian companies do not all close in March, and a company that moves its year-end
  files a short period once; both are stated plainly in the filing and both must be read, not assumed
- `figures`: for each vocabulary metric printed, {metric, period, value_printed EXACTLY as printed
  (keep commas, parentheses, dashes), page, row_label as printed}

Beware: a note-reference number printed between the label and the figures is not a value; an Ind AS
transition table titled for an earlier date is not the year's balance sheet; transcribe non-current and
current borrowings as their own separate rows — never add them yourself.

Return ONLY a JSON object: {"statements": [ ... ]}.
"""


def build_reading_packet(doc_id: str, pages: Sequence[str]) -> str:
    """The complete prompt for a proposer: instructions + vocabulary + the filing's page text, each page
    numbered so page claims are checkable. Page text is what bronze extraction produced (Law 7: no raw
    HTML; the proposer sees exactly what the verifier will search)."""
    vocab = "\n".join(f"- {mid}: {desc}" for mid, desc in READING_VOCABULARY.items())
    body = "\n".join(f"===== page {i + 1} =====\n{text}" for i, text in enumerate(pages))
    return (f"{READING_INSTRUCTIONS}\n## Document\n{doc_id}\n\n## Metric vocabulary\n{vocab}\n\n"
            f"## Pages\n{body}\n")


# --------------------------------------------------------------------------------------------------
# The proposal as JSON — how an answer travels back from any proposer (ADR-0010 packet path included).
# --------------------------------------------------------------------------------------------------

def proposal_from_json(text: str) -> list[ProposedStatement]:
    """Parse a proposer's JSON answer. Schema errors raise ValueError with the path that failed —
    the retry loop needs the reason, and a silently-skipped statement would be a silent blank."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as err:
        raise ValueError(f"proposal is not valid JSON: {err}") from err
    if not isinstance(data, dict) or not isinstance(data.get("statements"), list):
        msg = "proposal must be an object with a 'statements' list"
        raise TypeError(msg)
    out: list[ProposedStatement] = []
    for i, s in enumerate(data["statements"]):
        try:
            out.append(ProposedStatement(
                statement=str(s["statement"]),
                basis=str(s["basis"]),
                period=str(s["period"]),
                pages=tuple(int(p) for p in s["pages"]),
                heading_quote=str(s["heading_quote"]),
                unit_quote=str(s["unit_quote"]),
                unit=str(s["unit"]),
                columns=tuple(ProposedColumn(
                    period=(None if c.get("period") in (None, "") else str(c["period"])),
                    label_quote=str(c["label_quote"]),
                    months=(None if c.get("months") is None else int(c["months"])),
                    ends=(None if c.get("ends") in (None, "") else str(c["ends"])),
                ) for c in s["columns"]),
                figures=tuple(ProposedFigure(
                    metric=str(f["metric"]), period=str(f["period"]),
                    value_printed=str(f["value_printed"]), page=int(f["page"]),
                    row_label=str(f["row_label"]),
                ) for f in s["figures"]),
            ))
        except (KeyError, TypeError, ValueError) as err:
            raise ValueError(f"statements[{i}] malformed: {err}") from err
    return out
