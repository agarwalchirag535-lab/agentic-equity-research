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
from dataclasses import dataclass
from typing import Iterable, Sequence

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
#: A unit DECLARATION ("₹ In Lakhs" above a table) has no digits between the rupee sign and the unit word.
#: An inline prose AMOUNT ("Rs. 1.26 crores") does. Excluding digits is what separates them, and it is not a
#: nicety: on the FY22 Alkyl Amines filing, page 91 declares "` In Lakhs" twice above its tables and
#: mentions "Rs. 1.26 crores" once in a sentence about an EPCG licence. Crore is tested first, so the prose
#: mention won and every figure on the page was read as crore — a silent 100x on grade-A facts, which is
#: indistinguishable from a fabricated number once it carries a filing locator (ADR-0038).
#: A SUBSTITUTED RUPEE GLYPH (ADR-0040). Several Indian annual reports set ₹ in a custom-encoded font, and
#: text extraction renders every one of them as a bare capital "H": Balaji Amines' FY25 report declares
#: "(All amounts are in H lakh)" and prints "H2,857.50 lakh" inline. The declaration therefore matched no
#: rupee pattern, `page_unit_hint` returned '', and — because ADR-0024 makes an unresolvable scale a refusal
#: rather than an assumption — **not one figure in the entire filing could be read**. Silent and total.
#:
#: It is admitted only in the `in <glyph> <scale>` position, never as a general rupee alternative: an
#: unanchored "H" would match a capital letter anywhere within twenty characters of the word "lakh".
_SUBSTITUTED_RUPEE = r"[`₹H]"
_UNIT_HINTS = [
    (re.compile(rf"{_RUPEE}[^\n\d]{{0,20}}?\bcr(?:ore)?s?\b|"
                rf"\bin\s+(?:{_SUBSTITUTED_RUPEE}\s*)?cr(?:ore)?s?\b", re.IGNORECASE),
     "INR_cr"),
    (re.compile(rf"{_RUPEE}[^\n\d]{{0,20}}?\blakhs?\b|"
                rf"\bin\s+(?:{_SUBSTITUTED_RUPEE}\s*)?lakhs?\b", re.IGNORECASE), "INR_lakh"),
    (re.compile(rf"(?:{_RUPEE}|\$)[^\n\d]{{0,20}}?\b(?:million|mn|MM)\b|\bin\s+millions?\b",
                re.IGNORECASE),
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

#: The start of the NEXT enumerated statement row — "(iv) Other Financial Liabilities", "(b) Provisions",
#: "II Other Income". Used to bound a multi-line row so a component sum cannot absorb its neighbour.
_NEXT_ROW = re.compile(r"^\s*(?:\(\s*(?:[ivxIVX]{1,4}|[a-zA-Z])\s*\)|[IVX]{1,4}\s+[A-Z])")


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


def _mask_non_figures(line: str) -> str:
    """Blank out tokens that look numeric but are not figures (period tokens, leading note refs),
    preserving character offsets so callers can still slice the original line."""
    masked = _PERIOD.sub(lambda m: " " * len(m.group(0)), line)
    prefix = _LEADING_NOTE.match(masked)
    if prefix:
        masked = " " * len(prefix.group(0)) + masked[prefix.end():]
    return masked


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
    """Detect the unit a page declares ('₹ in crore', 'Rs. in lakhs', '$ MM', ...); '' if undeclared.

    When a page declares more than one unit — a lakh table followed by a note quoting a crore figure — the
    MOST DECLARED wins rather than the first pattern in the list. Order-of-testing is not evidence, and a
    page that says "In Lakhs" above each of its two tables is telling you its unit twice.
    """
    counts = [(len(pattern.findall(page_text)), hint) for pattern, hint in _UNIT_HINTS]
    best = max(counts, key=lambda c: c[0])
    return best[1] if best[0] else ""


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
    # A real balance sheet totals both sides.
    "balance_sheet": (
        ("total assets",),
        ("total equity and liabilities", "total equity & liabilities", "equity and liabilities"),
    ),
    # A real P&L reaches a profit line.
    "pnl": (
        ("revenue from operations", "total income"),
        ("profit before tax", "profit for the year", "total expenses"),
    ),
}


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
    if not bs:
        # No anchor: fall back to the last qualifying P&L page, which is still after the highlights.
        return {"balance_sheet": (), "pnl": (pnl[-1],) if pnl else ()}
    anchor = bs[0]
    nearest = min(pnl, key=lambda i: abs(i - anchor)) if pnl else None
    return {
        "balance_sheet": (anchor,),
        "pnl": () if nearest is None else (nearest,),
    }


def find_statement_row_sum(
    pages: Sequence[str],
    statement: str,
    anchor_keywords: Iterable[str],
    component_keywords: Iterable[str],
    *,
    max_lines: int = 8,
) -> ExtractedValue | None:
    """A statement line whose total is printed only as its COMPONENTS, summed (ADR-0038).

    Trade payables is the canonical case and it is a trap for a single-row reader. Schedule III requires the
    balance sheet to split the line, so what is printed is::

        (iii) Trade Payables
        Total outstanding dues of  Micro & Small Enterprises 24  1,550.29  1,426.79
        Total outstanding dues of creditors other than Micro
        & Small Enterprises  13,570.47  16,296.57

    The header carries no figure, and a keyword search that settles for the first matching row returns
    ₹1,550.29 as "trade payables" when the real figure is ₹15,120.76 — an order of magnitude out, sourced
    from the audited balance sheet, and therefore grade A. A wrong number with strong provenance is the
    worst thing this pipeline can produce, so components are summed and the label records that they were.

    The second component's label WRAPS, leaving its figures on the following line, so a component match
    that yields no figures carries forward and takes the next numeric line. Returns None when the anchor is
    absent or no component carries a figure — never a partial sum.
    """
    indices = audited_statement_pages(pages).get(statement, ())
    anchors = tuple(k.lower() for k in anchor_keywords)
    components = tuple(k.lower() for k in component_keywords)
    for index in indices:
        page = pages[index]
        lines = page.splitlines()
        start = next(
            (i for i, ln in enumerate(lines) if any(a in ln.lower() for a in anchors)), None
        )
        if start is None:
            continue
        total = 0.0
        found: list[str] = []
        first_line = None
        pending = False
        for offset, line in enumerate(lines[start + 1:start + max_lines], start=1):
            low = line.lower()
            is_component = any(c in low for c in components)
            # A new enumerated row ("(iv) Other Financial Liabilities …") ends the block. Without this the
            # carry-forward below would walk off the end of trade payables and add the next line's figures.
            if _NEXT_ROW.match(line) and not is_component:
                break
            if not (is_component or pending):
                continue
            values = numbers_on_line(line)
            if not values:
                # The label is still wrapping — it can take two lines before its figures appear, so a
                # pending carry must SURVIVE an intermediate blank-of-figures line rather than reset.
                pending = True
                continue
            total += values[0]
            found.append(line.strip())
            pending = False
            if first_line is None:
                first_line = start + offset + 1
        if found:
            return ExtractedValue(
                label=f"{lines[start].strip()} (sum of {len(found)} component rows)",
                values=(total,), page=index + 1, line=first_line or start + 1,
                unit_hint=page_unit_hint(page), raw_line=" | ".join(found)[:400],
            )
    return None


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
    indices = audited_statement_pages(pages).get(statement, ())
    if not indices:
        return None
    for index in indices:
        row = find_row([pages[index]], label_keywords, exclude=exclude)
        if row is not None:
            # `find_row` saw a one-page document, so re-anchor the page number to the real document.
            return ExtractedValue(
                label=row.label, values=row.values, page=index + 1, line=row.line,
                unit_hint=row.unit_hint, raw_line=row.raw_line,
            )
    return None
