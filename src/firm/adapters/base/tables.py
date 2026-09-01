"""Provenance-locked numeric extraction from filing text (ADR-0015 remainder; prerequisite for the
notes-walker, ADR-0017 §4).

Purpose: turn extracted filing pages into (label, values, page, line) rows so every figure that enters
the fact store is bound to its exact location in the source document (Law 2). This is line-anchored
extraction, not table reconstruction — deliberately: PDF table geometry is unreliable (ADR-0011), but a
*line* with a label and its numbers survives text extraction intact in practice (verified on the
CreditAccess/Bajaj decks in docs/VALIDATION_TIER0.md).

Honesty rules:
- A line with no parseable number is never returned — nothing is guessed or imputed.
- Percent tokens are excluded from `values` (they are ratios printed beside figures) but stay visible in
  `raw_line` for audit.
- Indian formats handled: lakh/crore comma grouping ("1,08,314"), parenthesised negatives "(99.5)",
  currency/footnote clutter. FY/quarter tokens ("FY25", "Q4FY25") are masked so they never parse as
  numbers.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

# Period tokens are labels, not numbers (same convention as validators/citation.py).
_PERIOD = re.compile(r"\b(FY\s?\d{2,4}|Q[1-4]\s?FY\s?\d{2,4}|[12]\d{3}-\d{2})\b", re.IGNORECASE)
# A leading note reference ("Note 9:", "29.", "12)") is a cross-reference, NOT a figure. Indian AR line
# items are routinely prefixed this way; without masking it the note number parses as a value and the
# label collapses to "Note" (caught by the end-to-end test).
_LEADING_NOTE = re.compile(r"^\s*(?:note\s*)?\d{1,3}\s*[:.)]\s+", re.IGNORECASE)
# A numeric token: optional parens (negative), optional sign, comma-grouped digits, optional decimals,
# optional trailing %.
_NUMBER = re.compile(r"\(?[-+]?\d[\d,]*(?:\.\d+)?\)?%?")

#: Rupee, as it survives PDF text extraction. Verified on the Alkyl Amines annual reports: the ₹ glyph in
#: the FY22-FY26 filings comes out of the text layer as a BACKTICK ("` In Lakhs"), because the font maps it
#: to a codepoint pypdf resolves that way. Without the backtick here the unit goes undetected, the caller
#: falls back to its default of crore, and every figure read from the filing is stored 100x too large —
#: with a grade-A provenance stamp on it. This is the most dangerous silent failure in the extraction path.
_RUPEE = r"(?:₹|`|Rs\.?|INR)"
#: "(₹ in Lakhs)" and "` In Lakhs" and a bare "Amount in Lakhs" all mean the same thing. The `in <unit>`
#: alternative catches the last form; requiring the word "in" keeps it from firing on prose like
#: "lakhs of tonnes".
_UNIT_HINTS = [
    (re.compile(rf"{_RUPEE}[^\n]{{0,20}}?\bcr(?:ore)?s?\b|\bin\s+cr(?:ore)?s?\b", re.IGNORECASE),
     "INR_cr"),
    (re.compile(rf"{_RUPEE}[^\n]{{0,20}}?\blakhs?\b|\bin\s+lakhs?\b", re.IGNORECASE), "INR_lakh"),
    (re.compile(rf"(?:{_RUPEE}|\$)[^\n]{{0,20}}?\b(?:million|mn|MM)\b|\bin\s+millions?\b", re.IGNORECASE),
     "MM"),
]

#: Multiplier from a declared unit to the firm's canonical money scale, ₹ crore. `INR_lakh` -> 0.01.
#: "million" is deliberately absent: "$ MM" and "₹ million" differ by an exchange rate, so a caller that
#: meets one must resolve it explicitly rather than have this module guess.
_TO_CRORE: dict[str, float] = {"INR_cr": 1.0, "INR_lakh": 0.01}
#: A bare integer this size or smaller, sitting in the first numeric column of a Schedule III line, is a
#: note cross-reference rather than a figure (see `_strip_note_column`).
NOTE_REFERENCE_MAX = 99
#: A figure as printed in an Indian filing carries a comma group or a decimal. Used to tell a real column
#: apart from a note reference.
_LOOKS_FORMATTED = re.compile(r"[,.]")
#: A bare integer: no comma, no decimal, no parentheses, no sign.
_BARE_INTEGER = re.compile(r"^\d{1,3}$")

#: A nil marker standing alone in a column — a dash, or the word NIL, which the pre-Ind AS filings print
#: instead ("Dividend Paid (Including Dividend Distribution Tax)  NIL  (3,436.91)").
_NIL_CELL = re.compile(r"(?:(?<=\s\s)|^)(?:[-–—]|NIL)(?=\s\s|\s*$)")
#: Everything that may follow a nil marker and still leave it unambiguously part of the figure columns:
#: whitespace, further nil markers, and printed figures. A letter anywhere after it (other than another
#: NIL) means the dash was a bullet or a hyphen in a label ("- Secured Borrowings 13A 2,159.24"), and it
#: is left alone.
_NUMERIC_TAIL = re.compile(r"^(?:\s|[-–—]|NIL|\(?[-+]?\d[\d,]*(?:\.\d+)?\)?)*$")
#: What a nil dash is rewritten to. "0.0" rather than "0" deliberately: `_strip_note_column` requires
#: every figure column to LOOK like a printed figure (comma or decimal), and a bare "0" would fail that
#: test and leave the note-reference column in place — turning `Short Term Borrowings 23 - 360.45` into
#: borrowings of Rs 23 lakh, which is the note number.
_NIL_FILL = "0.0"


def to_canonical_crore(value: float, unit: str) -> float | None:
    """``value`` expressed in ₹ crore, or None when the unit is unknown or not an INR scale.

    None is the honest answer rather than an assumption: a figure whose scale cannot be established must
    not enter the fact store at all, because a wrong scale is indistinguishable from a wrong number once
    it is stored and far more likely to be believed (it carries the filing's grade).
    """
    factor = _TO_CRORE.get(unit)
    return None if factor is None else value * factor


@dataclass(frozen=True)
class ExtractedValue:
    """One labelled row of figures with its provenance locator (Law 2)."""

    label: str
    values: tuple[float, ...]   # column order as printed; % tokens excluded
    page: int                   # 1-based page in the source document
    line: int                   # 1-based line on that page
    unit_hint: str              # 'INR_cr' | 'INR_lakh' | 'MM' | '' (unknown — caller must resolve)
    raw_line: str               # verbatim, for audit / arithmetic re-checks

    @property
    def locator(self) -> str:
        return f"p.{self.page} l.{self.line}"


def parse_number(token: str) -> float | None:
    """'1,08,314' → 108314.0 · '(99.5)' → -99.5 · '2,452.1' → 2452.1 · '280.2%'/'-'/'FY25' → None."""
    t = token.strip()
    if not t or t.endswith("%"):
        return None
    negative = t.startswith("(") and t.endswith(")")
    if negative:
        t = t[1:-1]
    t = t.replace(",", "")
    try:
        value = float(t)
    except ValueError:
        return None
    return -value if negative else value


def _fill_nil_columns(line: str) -> str:
    """Rewrite a **nil dash** standing in a figure column as an explicit zero.

    "-" in an Indian statement column means nil, and reading it as *absent* is not a conservative choice —
    it silently shortens the row. `Short Term Borrowings 23 - 360.45` then parses as two values, the
    note-reference guard (which needs three) never fires, and borrowings for the year read as **23**: the
    note number, stored as money, at grade A. Alkyl Amines FY26 is exactly that line.

    A dash is only rewritten when everything after it on the line is itself a figure, a nil, or space. A
    dash followed by any letter is a bullet or a hyphenated label — `- Secured Borrowings 13A 2,159.24`
    in the FY21 filing — and is left untouched.
    """
    # Right to left, so an earlier match's offsets stay valid after a later one has been rewritten.
    out = line
    for match in reversed(list(_NIL_CELL.finditer(line))):
        if _NUMERIC_TAIL.match(out[match.end():]):
            out = out[:match.start()] + _NIL_FILL + out[match.end():]
    return out


def _mask_non_figures(line: str) -> str:
    """Blank out tokens that look numeric but are not figures (period tokens, leading note refs), and
    make nil dashes explicit.

    Offsets are preserved to the LEFT of the first figure — which is all `_label_of` slices — but not to
    its right, because `_fill_nil_columns` widens a one-character dash into "0.0".
    """
    masked = _PERIOD.sub(lambda m: " " * len(m.group(0)), line)
    prefix = _LEADING_NOTE.match(masked)
    if prefix:
        masked = " " * len(prefix.group(0)) + masked[prefix.end():]
    return _fill_nil_columns(masked)


def _strip_note_column(tokens: Sequence[str], values: Sequence[float]) -> tuple[float, ...]:
    """Drop a Schedule III **note-reference column** that sits between the label and the figures.

    Indian balance sheets print `label | note no. | current year | prior year`:

        (ii)  Trade Receivables 11  23,049.50  23,064.82
        (iii) Cash and Cash Equivalents 12  9,415.34  4,877.87

    The `11` and `12` are cross-references to notes 11 and 12, not money. `_LEADING_NOTE` only masks a note
    reference at the *start* of a line ("9. Inventories"), so before this the first value read off the FY26
    balance sheet was 11.0 — and receivables entered the fact store as ₹11 lakh instead of ₹23,049.50 lakh.

    Three conditions must all hold, so the rule cannot eat a real figure:
      1. the candidate is the FIRST numeric token and is a bare integer <= NOTE_REFERENCE_MAX
         (no comma, no decimal, no parentheses, no sign);
      2. at least two numeric tokens follow it — a note column is never the last column;
      3. every following token is formatted like a printed figure (comma or decimal), and none of them is
         itself a bare small integer. Ambiguity means leave it alone.

    Condition 3 is what makes this safe: a line of bare integers ("Number of meetings 4 4 4") keeps all of
    them, because nothing there distinguishes a reference from a count.
    """
    if len(values) < 3 or not _BARE_INTEGER.match(tokens[0].strip()):
        return tuple(values)
    if not 0 < values[0] <= NOTE_REFERENCE_MAX:
        return tuple(values)
    rest = [t.strip() for t in tokens[1:]]
    if not all(_LOOKS_FORMATTED.search(t) for t in rest):
        return tuple(values)
    return tuple(values[1:])


def numbers_on_line(line: str) -> tuple[float, ...]:
    """Every parseable figure on a line, in print order.

    Excludes percentages, FY/quarter tokens, a leading note cross-reference, and a Schedule III note
    column standing between the label and the figures (`_strip_note_column`).
    """
    tokens: list[str] = []
    out: list[float] = []
    for m in _NUMBER.finditer(_mask_non_figures(line)):
        v = parse_number(m.group(0))
        if v is not None:
            tokens.append(m.group(0))
            out.append(v)
    return _strip_note_column(tokens, out)


def page_unit_hint(page_text: str) -> str:
    """Detect the unit a page declares ('₹ in crore', 'Rs. in lakhs', '$ MM', ...); '' if undeclared."""
    for pattern, hint in _UNIT_HINTS:
        if pattern.search(page_text):
            return hint
    return ""


def _label_of(line: str) -> str:
    """The row's label: text up to the first real figure, minus any leading note cross-reference."""
    masked = _mask_non_figures(line)
    m = _NUMBER.search(masked)
    cut = m.start() if m else len(masked)
    return masked[:cut].strip(" .:‐-–|\t")


def extract_labeled_rows(pages: Sequence[str]) -> list[ExtractedValue]:
    """Every line across all pages that carries a textual label followed by ≥1 number.

    Nothing is inferred: rows without numbers are skipped, units are hints (page-level declaration),
    and each row carries its verbatim line for downstream arithmetic verification.
    """
    rows: list[ExtractedValue] = []
    for p_idx, page in enumerate(pages, start=1):
        hint = page_unit_hint(page)
        for l_idx, line in enumerate(page.splitlines(), start=1):
            values = numbers_on_line(line)
            if not values:
                continue
            label = _label_of(line)
            if not label or not re.search(r"[A-Za-z]", label):
                continue  # a bare number row has no label to anchor a fact to
            rows.append(ExtractedValue(label, values, p_idx, l_idx, hint, line.rstrip()))
    return rows


#: Markers that identify a page as the primary statement itself rather than a note, an audit opinion or a
#: cash-flow movement line. Verified against ten Alkyl Amines annual reports (FY17-FY26).
_STATEMENT_MARKERS: dict[str, tuple[tuple[str, ...], ...]] = {
    # A real balance sheet announces itself and totals both sides. The bare "total" alternative exists
    # for the pre-Ind AS Schedule III layout (Alkyl Amines FY17), which puts equity and liabilities
    # first and closes each side with an unadorned "TOTAL"; without it that filing has no balance sheet
    # at all, and `audited_statement_pages` then falls through to the LAST P&L in the document — which
    # is the CONSOLIDATED one, silently mixing two reporting bases into one series.
    "balance_sheet": (
        ("balance sheet as at", "balance sheet as of"),
        ("total assets", "total"),
        ("total equity and liabilities", "total equity & liabilities", "equity and liabilities"),
    ),
    # A real P&L reaches a profit line.
    "pnl": (
        ("revenue from operations", "total income"),
        ("profit before tax", "profit for the year", "total expenses"),
    ),
    # A cash-flow page names the statement and at least one of the three activity sections. Deliberately
    # looser than the other two, because the statement RUNS OVER A PAGE BREAK: the continuation page
    # carries only the financing section, and demanding all three would drop the half of the statement
    # that holds capex funding, borrowings movement and dividends. `audited_statement_pages` supplies the
    # discipline the loose marker gives up, by keeping only pages inside the audited block.
    "cashflow": (
        ("cash flow", "cash flows"),
        ("operating activities", "investing activities", "financing activities"),
    ),
}

#: How far past the balance sheet the cash-flow statement may start. The audited block is printed as
#: Balance Sheet → Statement of Profit and Loss → Statement of Changes in Equity → Cash Flows, and the
#: SOCIE runs to two or three pages in these filings, so the cash flow lands within a handful of pages.
#: Anything further away is the auditor's report, a note, or the consolidated set.
_CASHFLOW_WINDOW = 8


def statement_pages(pages: Sequence[str], statement: str) -> tuple[int, ...]:
    """0-based indices of the pages that ARE the named primary statement.

    Why this exists: `find_row` returns the first label match in the document, and in a real 180-page annual
    report the first mention of "Inventories" is not the balance sheet. On the Alkyl Amines filings it was,
    variously, a cash-flow movement line ("(Increase) / Decrease in Trade Receivables (6,376.60)" — hence a
    NEGATIVE receivables figure for FY21) and a sentence in the auditor's report ("verification of
    inventories as at March..."). Both parse to numbers and both are wrong.

    A page qualifies only if it carries a marker from EVERY group for that statement, which is what a
    genuine statement page does and a note or a narrative page does not.
    """
    groups = _STATEMENT_MARKERS.get(statement)
    if not groups:
        return ()
    out: list[int] = []
    for index, page in enumerate(pages):
        low = page.lower()
        if all(any(marker in low for marker in group) for group in groups):
            out.append(index)
    return tuple(out)


def find_row(
    pages: Sequence[str], label_keywords: Iterable[str], *, exclude: Iterable[str] = ()
) -> ExtractedValue | None:
    """First labelled row whose label contains any keyword (case-insensitive) and none of `exclude`.

    Returns None when absent — the caller reports UNAVAILABLE (owner directive: never guess a figure).
    """
    keys = [k.lower() for k in label_keywords]
    blocked = [x.lower() for x in exclude]
    for row in extract_labeled_rows(pages):
        low = row.label.lower()
        if any(k in low for k in keys) and not any(b in low for b in blocked):
            return row
    return None


def audited_statement_pages(pages: Sequence[str]) -> dict[str, tuple[int, ...]]:
    """The AUDITED statement pages, distinguished from the financial-highlights pages that mimic them.

    A ten-year-highlights box near the front of an annual report contains "Revenue from operations",
    "Profit before tax" and a column of numbers, so it satisfies `statement_pages` — and it is rounded to
    whole lakhs. Reading FY17 revenue off the FY18 highlights page gave 541.79 where the audited statement
    says 541.7853; small, but it is a *different number from a lower-quality table*, and grade A should mean
    the audited one.

    The discriminator is layout, and it holds across all ten Alkyl Amines filings: the audited statements are
    printed as a block — Balance Sheet, then Statement of Profit and Loss, then Cash Flows — deep in the
    document, whereas the highlights sit alone near the front. So the balance sheet anchors the block, and the
    P&L is taken as the qualifying page NEAREST that anchor rather than the first one in the file.
    """
    bs = statement_pages(pages, "balance_sheet")
    pnl = statement_pages(pages, "pnl")
    cashflow = statement_pages(pages, "cashflow")
    if not bs:
        # No anchor: fall back to the last qualifying P&L page, which is still after the highlights.
        return {"balance_sheet": (), "pnl": (pnl[-1],) if pnl else (), "cashflow": ()}
    anchor = bs[0]
    nearest = min(pnl, key=lambda i: abs(i - anchor)) if pnl else None
    return {
        "balance_sheet": (anchor,),
        "pnl": () if nearest is None else (nearest,),
        # EVERY page of the cash flow, not the first: the statement is read for `Net Cash Flows from
        # Financing Activities`, `Repayment of Borrowings` and `Dividend Paid` as much as for CFO, and
        # those sit on the continuation page.
        "cashflow": tuple(i for i in cashflow if anchor < i <= anchor + _CASHFLOW_WINDOW),
    }


def find_statement_row(
    pages: Sequence[str],
    statement: str,
    label_keywords: Iterable[str],
    *,
    exclude: Iterable[str] = (),
) -> ExtractedValue | None:
    """`find_row`, restricted to the pages that ARE the named primary statement.

    Returns None when the label is absent from those pages **even if it appears elsewhere in the document**.
    That is the point: falling back to a document-wide search is how a cash-flow movement line or an audit
    sentence becomes a balance-sheet fact. A gap the caller reports as UNAVAILABLE is strictly better than a
    figure read off the wrong table, because the gap is visible and the wrong figure is not.

    Page numbers in the returned locator stay absolute (1-based in the whole document), so provenance still
    points at the real page.
    """
    found = find_statement_rows(pages, statement, label_keywords, exclude=exclude)
    return found[0] if found else None


def rows_matching_first_value(
    pages: Sequence[str], statement: str, expected: float, *, tolerance: float = 0.01
) -> tuple[ExtractedValue, ...]:
    """Every row on the statement's pages whose FIRST figure is ``expected``.

    Used to repair a label/figure misalignment against an accounting identity — see
    `reconcile_to_identity`. Matching on the figure rather than the label is the point: the label is
    exactly what went wrong.
    """
    out: list[ExtractedValue] = []
    for index in audited_statement_pages(pages).get(statement, ()):
        for row in extract_labeled_rows([pages[index]]):
            if row.values and abs(row.values[0] - expected) <= tolerance:
                out.append(ExtractedValue(
                    label=row.label, values=row.values, page=index + 1, line=row.line,
                    unit_hint=row.unit_hint, raw_line=row.raw_line,
                ))
    return tuple(out)


def reconcile_to_identity(
    pages: Sequence[str],
    statement: str,
    candidate: ExtractedValue | None,
    anchor: ExtractedValue | None,
    *,
    tolerance: float = 0.01,
) -> tuple[ExtractedValue | None, str]:
    """Check ``candidate`` against an accounting identity it must satisfy, repairing or refusing it.

    THE FAILURE THIS EXISTS FOR. Layout extraction reconstructs a table row by horizontal position, and
    where a filing's subtotal sits on the same baseline as the next section's heading the label and the
    figures come apart. On the Alkyl Amines FY22 balance sheet the result is:

        TOTAL ASSETS               53,757.00   52,792.12     <- the CURRENT-ASSETS subtotal
        EQUITY AND LIABILITIES    137,132.67  114,533.46     <- the real total assets

    Every earlier defence in this module — statement scoping, the note-column guard, the unit check —
    passes that line, because nothing about "TOTAL ASSETS 53,757.00" is malformed. It is simply the
    wrong number, and it would enter the fact store at grade A with a correct-looking locator.

    A balance sheet balances, so the liabilities-side total is an independent statement of the same
    figure. When the two disagree, the candidate is not trusted:

    * a row on the same statement whose first figure DOES equal the anchor is taken instead, with its
      own locator (the FY22 case: the misplaced figures are recovered from the line they landed on);
    * failing that, nothing is returned and the caller reports the gap, because a total that does not
      balance is not a fact about the company.

    Returns ``(row_or_None, note)`` where ``note`` is empty when the candidate verified as printed.
    """
    if anchor is None or not anchor.values:
        return candidate, ""
    if candidate is not None and candidate.values and abs(
            candidate.values[0] - anchor.values[0]) <= tolerance:
        return candidate, ""
    printed = "absent" if candidate is None or not candidate.values else f"{candidate.values[0]:,.2f}"
    for repair in rows_matching_first_value(pages, statement, anchor.values[0], tolerance=tolerance):
        if repair.locator != (candidate.locator if candidate else None):
            return repair, (
                f"the row labelled for this metric read {printed} against {anchor.values[0]:,.2f} on the "
                f"balancing line at {anchor.locator}; the figures were recovered from {repair.locator} "
                f"({repair.label!r}), which satisfies the identity"
            )
    return None, (
        f"the row labelled for this metric read {printed} against {anchor.values[0]:,.2f} on the "
        f"balancing line at {anchor.locator}, and no row on the statement satisfies the identity — "
        f"not stored, because a total that does not balance is not a fact about the company"
    )


def find_statement_rows(
    pages: Sequence[str],
    statement: str,
    label_keywords: Iterable[str],
    *,
    exclude: Iterable[str] = (),
) -> tuple[ExtractedValue, ...]:
    """EVERY matching row on the named statement's pages, in print order, page-anchored.

    Some Schedule III lines are a total split across rows that no single line states. Trade payables is
    the standing example: the balance sheet prints "Total outstanding dues of Micro & Small Enterprises"
    and "…of creditors other than Micro Enterprises and Small Enterprises" as two rows and never their
    sum, so a caller that reads the first match reports a payables balance an order of magnitude too
    small. Borrowings is the same shape (secured / unsecured, long-term / short-term). The caller sums;
    this returns the parts, each with its own locator, so the sum can be audited back to the page.
    """
    keys = [k.lower() for k in label_keywords]
    blocked = [x.lower() for x in exclude]
    out: list[ExtractedValue] = []
    for index in audited_statement_pages(pages).get(statement, ()):
        for row in extract_labeled_rows([pages[index]]):
            low = row.label.lower()
            if any(k in low for k in keys) and not any(b in low for b in blocked):
                # `extract_labeled_rows` saw a one-page document; re-anchor to the real page number.
                out.append(ExtractedValue(
                    label=row.label, values=row.values, page=index + 1, line=row.line,
                    unit_hint=row.unit_hint, raw_line=row.raw_line,
                ))
    return tuple(out)
