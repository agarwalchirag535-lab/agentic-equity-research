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

_UNIT_HINTS = [
    (re.compile(r"(?:₹|Rs\.?|INR)[^\n]{0,20}?\bcr(?:ore)?s?\b", re.IGNORECASE), "INR_cr"),
    (re.compile(r"(?:₹|Rs\.?|INR)[^\n]{0,20}?\blakhs?\b", re.IGNORECASE), "INR_lakh"),
    (re.compile(r"(?:₹|Rs\.?|INR|\$)[^\n]{0,20}?\b(?:million|mn|MM)\b", re.IGNORECASE), "MM"),
]


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


def numbers_on_line(line: str) -> tuple[float, ...]:
    """Every parseable figure on a line, in print order.

    Excludes percentages, FY/quarter tokens, and a leading note cross-reference.
    """
    out = []
    for m in _NUMBER.finditer(_mask_non_figures(line)):
        v = parse_number(m.group(0))
        if v is not None:
            out.append(v)
    return tuple(out)


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
