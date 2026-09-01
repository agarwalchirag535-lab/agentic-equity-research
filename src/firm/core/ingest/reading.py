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

#: A note figure and the face-of-statement metric it must agree with (ADR-0038: "a note is read when it
#: reconciles to the face of the statements"). This is what replaces V1's year test for a note: the note
#: is trusted because it ties to a figure verified independently from a different page, which is a
#: stronger claim than any property of the note's own typography.
NOTE_RECONCILES_TO: Mapping[str, str] = {
    "notes:Net Loans": "balance_sheet:Loans",
}

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


#: How a filing states a period's CLOSE in its own words (ADR-0049). The `FY{yy}` label silently
#: assumes a 31-March close for every company; Symphony's FY13–FY15 close on 30 June, which corrupts
#: CAGRs, `resolve_by` dates and peer comparisons the moment label arithmetic is used as time
#: arithmetic. The close is read from the same verbatim quotes V1/V3 already pin to the page.
_MONTH_NAMES: Mapping[str, int] = {
    name: i + 1 for i, name in enumerate((
        "january", "february", "march", "april", "may", "june", "july",
        "august", "september", "october", "november", "december"))
}
_DATE_NUMERIC = re.compile(r"\b(\d{1,2})[/.\-](\d{1,2})[/.\-]((?:20|19)\d{2})\b")
_DATE_DAY_FIRST = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)[,.]?\s+((?:20|19)\d{2})\b")
_DATE_MONTH_FIRST = re.compile(
    r"\b([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?\s*,?\s+((?:20|19)\d{2})\b")


def _month_number(word: str) -> int | None:
    w = word.lower()
    if w in _MONTH_NAMES:
        return _MONTH_NAMES[w]
    # Text extraction glues words ("As atMarch 31, 2026" is how a real two-up header survives), and the
    # word-boundary then hands us the whole glued token. A FULL month name as the token's suffix is
    # unambiguous; abbreviations are not extended this courtesy.
    for name, n in _MONTH_NAMES.items():
        if w.endswith(name):
            return n
    if len(w) >= 3:  # 'Mar', 'Sept' — filings abbreviate; three letters are unambiguous
        return next((n for name, n in _MONTH_NAMES.items() if name.startswith(w[:3])), None)
    return None


def dates_stated(text: str) -> frozenset[date]:
    """Every full calendar date the text states, in any of the forms Indian filings print:
    '31/03/2016' · '31-03-2016' · '31 March 2017' · '31st March, 2017' · 'March 31, 2017'."""
    text = re.sub(r"\s+", " ", text)
    found: set[date] = set()
    for m in _DATE_NUMERIC.finditer(text):
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= month <= 12 and 1 <= day <= 31:
            try:
                found.add(date(year, month, day))
            except ValueError:  # '31/04/2016' printed by a typo stays unparsed, not guessed at
                pass
    for pattern, month_group, day_group in ((_DATE_DAY_FIRST, 2, 1), (_DATE_MONTH_FIRST, 1, 2)):
        for m in pattern.finditer(text):
            month = _month_number(m.group(month_group))
            if month is None:
                continue
            try:
                found.add(date(int(m.group(3)), month, int(m.group(day_group))))
            except ValueError:
                pass
    return frozenset(found)


def end_stated(text: str, year: int) -> date | None:
    """The period close the text states UNAMBIGUOUSLY for calendar ``year``, else None.

    Filtering to the period's own calendar year is what makes the statement heading safe as a
    fallback: 'for the year ended March 31, 2026' dates the FY26 column and can never leak onto the
    FY25 column beside it. Two different dates in the same year (a restatement table's 'as at' pair)
    are ambiguous, and contradicting nothing beats guessing — same discipline as `months_stated`."""
    in_year = {d for d in dates_stated(text) if d.year == year}
    return in_year.pop() if len(in_year) == 1 else None


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
    #: The period's closing date, when the proposer states it. None means "read it from the words"
    #: (V3c): the single date of the period's own calendar year in the column label, then in the
    #: heading. A column whose close cannot be established either way is refused rather than assumed
    #: to be 31 March — the June-year-end half of ADR-0048's root cause.
    end: date | None = None


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
    #: For `statement="note"`: the note's own label as the filing numbers it ("7", "36a", "46"). A note
    #: heading names a NOTE, not a period — "7 Loans" carries no year — so V1's year test cannot apply to
    #: one, and this is what identifies it instead.
    note_label: str = ""


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
    #: The period's closing date as the filing states it (ADR-0049) — 2015-06-30 for a June closer's
    #: FY15. Established by V3c for every period column, so it is present on every verified figure.
    period_end: date | None = None


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
    is_note = stmt.statement == "note"
    if not _find_letters_on_pages(stmt.heading_quote, pages, stmt.pages[:1] or stmt.pages):
        violations.append(Violation("V1_heading", name,
                                    f"heading {stmt.heading_quote!r} not found on p.{stmt.pages[:1]}"))
    year = _fy_year(stmt.period)
    if is_note:
        # A note heading names a note, not a period ("7 Loans", "46 Contingent liability"), so the year
        # test is meaningless here — the note's LABEL is its identity, and its periods come from the
        # column headers like any other table. What replaces the year check is stronger: a note figure
        # mapped to a face metric must RECONCILE to it at registration (ADR-0038's standard).
        if not stmt.note_label.strip():
            violations.append(Violation("V1_heading", name,
                                        "a note must declare the label the filing numbers it by"))
        elif _letters(stmt.note_label) not in _letters(stmt.heading_quote):
            violations.append(Violation(
                "V1_heading", name,
                f"note label {stmt.note_label!r} does not appear in its own heading "
                f"{stmt.heading_quote!r}"))
    elif year and year not in _letters(stmt.heading_quote):
        violations.append(Violation(
            "V1_heading", name,
            f"heading {stmt.heading_quote!r} does not name {year} — wrong year's statement, or a "
            "transition/restatement table"))
    heading_letters = _letters(stmt.heading_quote)
    if stmt.basis == "standalone" and "consolidated" in heading_letters:
        violations.append(Violation("V1_heading", name, "claimed standalone but heading says consolidated"))
    # A note's heading never states its basis — "7 Loans" belongs to whichever set of statements its
    # section sits in, and the filing prints the same note twice under both. Demanding the word here
    # would make every note unreadable. Basis is instead PROVEN by the reconciliation gate, and proven
    # better: a standalone note does not tie to the consolidated face figure, so a note that reconciles
    # has demonstrated which statements it belongs to rather than merely asserting it.
    if not is_note and stmt.basis == "consolidated" and "consolidated" not in heading_letters:
        violations.append(Violation("V1_heading", name, "claimed consolidated but heading does not say so"))

    # V2 — the unit declaration exists and is in the vocabulary.
    if stmt.unit not in UNIT_TO_CRORE:
        violations.append(Violation("V2_unit", name, f"unknown unit {stmt.unit!r}"))
    if not _find_on_pages(stmt.unit_quote, pages, stmt.pages):
        violations.append(Violation("V2_unit", name,
                                    f"unit declaration {stmt.unit_quote!r} not found on pages {stmt.pages}"))

    # V3 — every period column's label exists on the page and names that period's calendar year.
    # V3b — and, for a FLOW statement, its length is established and agrees with the filing's own words.
    # V3c — and its CLOSING DATE is established the same way (ADR-0049): a `FY{yy}` label is not a
    # date, and assuming 31 March misdates every June closer.
    is_flow = stmt.statement in ("pnl", "cashflow")   # a note carries whatever its parent line carries
    heading_months = months_stated(stmt.heading_quote)
    declared_periods: set[str] = set()
    months_by_period: dict[str, int] = {}
    end_by_period: dict[str, date] = {}
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
        # V3c — same precedence as V3b: declared, then the column's own words, then the heading's.
        # Both text sources are filtered to the period's own calendar year, so the heading fallback is
        # safe — 'year ended March 31, 2026' can date the FY26 column but never the FY25 one beside it.
        stated_end = end_stated(col.label_quote, int(col_year))
        effective_end = col.end if col.end is not None else (
            stated_end if stated_end is not None else end_stated(stmt.heading_quote, int(col_year)))
        if effective_end is None:
            violations.append(Violation(
                "V3c_period_close", name,
                f"column {col.label_quote!r} ({col.period}): neither the column nor the heading states "
                f"a closing date in {col_year}, so the close cannot be assumed to be 31 March — "
                "declare `end`"))
        elif col.end is not None and stated_end is not None and stated_end != col.end:
            violations.append(Violation(
                "V3c_period_close", name,
                f"column {col.label_quote!r} declares the close as {col.end} but its own words say "
                f"{stated_end}"))
        elif col.end is not None and str(col.end.year) != col_year:
            violations.append(Violation(
                "V3c_period_close", name,
                f"column {col.period} declares the close as {col.end}, which is not in {col_year} — "
                "the Indian FY label names the calendar year the period ends in"))
        else:
            end_by_period[col.period] = effective_end
        if col_year not in _letters(col.label_quote):
            violations.append(Violation(
                "V3_column", name,
                f"column {col.label_quote!r} claimed as {col.period} does not name {col_year} — "
                "a column that names no year is not a reporting period"))
        if not _find_letters_on_pages(col.label_quote, pages, stmt.pages):
            violations.append(Violation("V3_column", name,
                                        f"column label {col.label_quote!r} not found on pages {stmt.pages}"))

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
                                       end_by_period.get(fig.period)))

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
    def reconcile(stmt) -> list[str]:
        """A note must agree with the face of the statements, or none of it is stored (ADR-0038/0052).

        Read from the STORE rather than from this reading, so the comparison is against a figure already
        verified and registered from a different page of the filing — an independent check, not a
        restatement of the same transcription."""
        problems: list[str] = []
        for fig in stmt.figures:
            face = NOTE_RECONCILES_TO.get(fig.metric)
            if face is None:
                continue
            stored = store.query_fact(ticker, face, fig.period, as_of=published_at)
            if stored is None:
                problems.append(
                    f"{fig.metric} {fig.period} must reconcile to {face}, which is not in the store — "
                    "read the statements before the notes that explain them")
            elif abs(stored.value - fig.value_crore) > max(0.01, 0.001 * abs(stored.value)):
                problems.append(
                    f"{fig.metric} {fig.period} is {fig.value_crore:,.2f} but the face of the "
                    f"statements says {face} = {stored.value:,.2f}")
        return problems

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

    def write(metric: str, period: str, value: float, locator: str,
              period_end: date | None = None) -> None:
        fact_id = f"{reading.doc_id}:{metric}:{period}"
        unit = "INR" if metric in PER_SHARE_METRICS else "INR_cr"
        store.add_fact(fact_id=fact_id, doc_id=reading.doc_id, ticker=ticker, metric=metric,
                       period=period, value=value, unit=unit, locator=locator,
                       period_end=period_end)
        fact_ids.append(fact_id)

    for stmt in chosen:
        if stmt.statement == "note" and (problems := reconcile(stmt)):
            skipped.extend(f"note {stmt.heading_quote!r}: {p}" for p in problems)
            continue
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
                  f"{stmt.basis}; {stmt.heading_quote})",
                  fig.period_end)
        # Composed in trusted code, never by the proposer (ADR-0037 practice): a total the filing
        # prints only as parts is the sum of the printed rows, its locator naming both so a reader can
        # redo the addition. Borrowings (non-current + current) and trade payables (the Schedule III
        # micro/other split every modern filing uses) are the two such totals.
        if stmt.statement in ("balance_sheet", "note"):
            parts = {(f.metric, f.period): f for f in stmt.figures}
            periods = {f.period for f in stmt.figures}
            # The lender rule is a THREE-part sum and is tried first: a lender that also printed a
            # current/non-current split would otherwise compose the wrong total from the wrong two rows.
            composed = (
                ("balance_sheet:Borrowings",
                 ("balance_sheet:Debt Securities",
                  "balance_sheet:Borrowings (Other than Debt Securities)",
                  "balance_sheet:Subordinated Liabilities")),
                # A lender with no subordinated debt prints only the first two of the three kinds
                # (Five-Star's whole balance sheet has no such row), so the two-part sum is tried after
                # the three-part one. The accepted risk is the same one the current/non-current rule
                # already carries: a proposer who omits a row the filing DOES print composes a short
                # total — bounded by the cross-filing quarantine, not by this module.
                ("balance_sheet:Borrowings",
                 ("balance_sheet:Debt Securities",
                  "balance_sheet:Borrowings (Other than Debt Securities)")),
                ("balance_sheet:Borrowings",
                 ("balance_sheet:Non-Current Borrowings", "balance_sheet:Current Borrowings")),
                ("balance_sheet:Trade Payables",
                 ("balance_sheet:Trade Payables (Micro)", "balance_sheet:Trade Payables (Other)")),
                # A lender that stages each lending book separately prints no combined Stage-3 row; the
                # asset-quality checks need the whole book, so it is summed here in trusted code with
                # both source rows named in the locator.
                ("notes:Stage 3 Gross",
                 ("notes:Stage 3 Gross (Group)", "notes:Stage 3 Gross (Individual)")),
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
                            f"{found[0].unit}; {stmt.basis})",
                          found[0].period_end)
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
    # --- read from the NOTES rather than the face of the statements -------------------------------
    "notes:Gross Loans": "gross loan book before impairment allowance (loans note, 'Total - Gross')",
    "notes:Impairment Allowance": "impairment loss allowance / ECL allowance carried on the loan book "
                                  "(loans note, 'Less: Impairment loss allowance')",
    "notes:Stage 3 Gross": "gross carrying value of Stage 3 (credit-impaired) loans — the Ind AS 109 "
                           "equivalent of gross NPA (ECL staging note). Transcribe the per-book rows "
                           "below instead when the filing stages each lending book separately",
    "notes:Stage 3 Gross (Group)": "Stage 3 gross carrying value, group / joint-liability lending book",
    "notes:Stage 3 Gross (Individual)": "Stage 3 gross carrying value, individual lending book",
    "notes:Stage 3 Allowance": "impairment loss allowance held against Stage 3 loans alone — the "
                               "stage-3 column of the ECL allowance reconciliation's closing row, NOT "
                               "the whole-book allowance",
    "notes:Secured Loans": "gross loans secured by tangible assets (loans note, 'Based on security')",
    "notes:Unsecured Loans": "gross unsecured loans (loans note, 'Based on security')",
    "notes:Net Loans": "net loans after impairment allowance (loans note, 'Total - Net') — transcribed "
                       "so the note can be reconciled against the balance sheet",
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
    "cashflow:Interest Income": "interest received — the INVESTING section's positive cash row, "
                                "not the negative add-back in the operating section. The 'is the cash "
                                "real' test divides this by the cash balance: real deposits earn real "
                                "interest",
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
  A column may also declare `months` (integer) and `end` (ISO date, the period's closing date) when
  the printed words are ambiguous — both are verified against the page and refused on contradiction.
  Say what the filing says, never what you expect: Indian companies do not all close in March, and a
  company that moves its year-end files a short period once — both are stated plainly in the filing
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
                note_label=str(s.get("note_label", "")),
                columns=tuple(ProposedColumn(
                    period=(None if c.get("period") in (None, "") else str(c["period"])),
                    label_quote=str(c["label_quote"]),
                    months=(None if c.get("months") in (None, "") else int(c["months"])),
                    end=(None if c.get("end") in (None, "")
                         else date.fromisoformat(str(c["end"]))),
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


# --------------------------------------------------------------------------------------------------
# Manifest-driven ingest — the CLI path (ADR-0055). Everything above existed only as hand-driven
# Python; this is what lets `firm` go from a filings manifest to verified, dated, grade-A facts.
# --------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class ReadingIngestResult:
    """What one manifest filing contributed through the reading path — or exactly why it could not.

    `status` is one of:
    - `registered`   — verified against the page text and written to the store
    - `refused`      — the reading exists but the verifier rejected it (violations attached)
    - `no_reading`   — no `{file}.reading.json` yet; `firm read-packets` writes the packet to answer
    - `pdf_mismatch` — the local/downloaded bytes do not hash to the manifest's sha256; NOTHING was
                       read from them — a document that is not the pinned document is not the document
    - `not_yet_published` — Law 3: the filing postdates `as_of` and was not opened at all
    """

    file: str
    period: str
    status: str
    fact_ids: tuple[str, ...] = ()
    skipped_stub_flows: tuple[str, ...] = ()
    violations: tuple[Violation, ...] = ()
    detail: str = ""


def _pinned_pdf(
    entry: Mapping[str, object], bronze, fetcher=None
) -> tuple[bytes | None, str]:
    """The manifest filing's bytes, integrity-checked; `(None, why)` when they cannot be had.

    Order: the bronze copy at `{bronze}/{file}` if present, else `fetcher(source_url)` (written to
    bronze on success so the fetch happens once). Either way, when the manifest pins a sha256 the
    bytes must hash to it — a silent substitution (a portal re-uploading a corrected PDF, a truncated
    download) must fail loudly, not flow into grade-A facts.
    """
    import hashlib
    from pathlib import Path

    path = Path(bronze) / str(entry["file"])
    pinned = str(entry.get("sha256", "") or "")
    if path.exists():
        payload = path.read_bytes()
    elif fetcher is not None:
        try:
            payload = fetcher(str(entry["source_url"]))
        except Exception as err:  # noqa: BLE001 — injected fetcher; the error is recorded and the
            #                       manifest row is reported failed rather than the run dying
            return None, f"fetch failed: {err}"
    else:
        return None, f"no PDF at {path} and no fetcher supplied"
    if pinned and hashlib.sha256(payload).hexdigest() != pinned:
        return None, (f"bytes do not hash to the manifest's sha256 {pinned[:12]}… — refusing to read "
                      "a document that is not the pinned document")
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    return payload, ""


def ingest_readings_manifest(
    store: FactStore,
    manifest: Mapping[str, object],
    *,
    readings_dir,
    bronze,
    as_of,
    fetcher=None,
    extract=None,
) -> list[ReadingIngestResult]:
    """Register every manifest filing's verified reading, oldest first. Nothing is guessed:

    a filing with no reading, a reading the verifier refuses, and a PDF that fails its hash all come
    back as explicit statuses for the caller to print — never a silent skip (owner directive 2).
    Law 3 applies at ingest: a filing disseminated after ``as_of`` is not even opened, because
    extracting it would leak its statements into the run before they existed.
    """
    from pathlib import Path

    if extract is None:
        from firm.adapters.base.extract import extract_document

        def extract(payload):
            return extract_document(payload).pages

    ticker = str(manifest["ticker"])
    out: list[ReadingIngestResult] = []
    for entry in sorted(manifest["filings"], key=lambda e: str(e["period"])):
        file, period = str(entry["file"]), str(entry["period"])
        published = date.fromisoformat(str(entry["published_at"]))
        if as_of is not None and published > as_of:
            out.append(ReadingIngestResult(file, period, "not_yet_published"))
            continue
        reading_path = Path(readings_dir) / f"{Path(file).stem}.reading.json"
        if not reading_path.exists():
            out.append(ReadingIngestResult(
                file, period, "no_reading",
                detail=f"no {reading_path.name} — run `firm read-packets` and answer the packet"))
            continue
        payload, why = _pinned_pdf(entry, bronze, fetcher)
        if payload is None:
            out.append(ReadingIngestResult(file, period, "pdf_mismatch", detail=why))
            continue
        pages = extract(payload)
        reading = verify_proposal(file, proposal_from_json(reading_path.read_text()), pages)
        if reading.violations:
            out.append(ReadingIngestResult(
                file, period, "refused", violations=reading.violations))
            continue
        fact_ids, skipped = register_reading(
            store, ticker, reading,
            source_url=str(entry["source_url"]), published_at=published,
            sha256=str(entry.get("sha256", "") or ""), grade=str(entry.get("grade", "A")))
        out.append(ReadingIngestResult(
            file, period, "registered", fact_ids=fact_ids, skipped_stub_flows=skipped))
    return out


def write_reading_packets(
    manifest: Mapping[str, object],
    *,
    bronze,
    out_dir,
    readings_dir,
    as_of=None,
    fetcher=None,
    extract=None,
) -> list[str]:
    """Write one reading packet per manifest filing that has no answered reading yet.

    Returns the paths written. The packet is the complete proposer prompt (instructions + vocabulary +
    numbered page text); the answer goes to `{readings_dir}/{file stem}.reading.json` and
    `ingest_readings_manifest` picks it up. Law 3 applies here too — a packet must not be written for
    a filing the run date could not have seen.
    """
    from pathlib import Path

    if extract is None:
        from firm.adapters.base.extract import extract_document

        def extract(payload):
            return extract_document(payload).pages

    out = Path(out_dir)
    written: list[str] = []
    for entry in sorted(manifest["filings"], key=lambda e: str(e["period"])):
        file = str(entry["file"])
        published = date.fromisoformat(str(entry["published_at"]))
        if as_of is not None and published > as_of:
            continue
        if (Path(readings_dir) / f"{Path(file).stem}.reading.json").exists():
            continue
        payload, why = _pinned_pdf(entry, bronze, fetcher)
        if payload is None:
            raise FileNotFoundError(f"{file}: {why}")
        out.mkdir(parents=True, exist_ok=True)
        packet = out / f"{Path(file).stem}.reading-packet.md"
        packet.write_text(build_reading_packet(file, extract(payload)))
        written.append(str(packet))
    return written


def fetch_pdf(url: str) -> bytes:  # pragma: no cover - thin network wrapper
    """Default `BytesFetcher` for the CLI: browser headers (NSE/BSE refuse bare clients), cert bundle."""
    import ssl
    import urllib.request

    try:
        import certifi

        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = ssl.create_default_context()
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
               "Referer": "https://www.bseindia.com/"}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=60, context=ctx) as resp:
        return resp.read()
