"""Robust document extraction with an OCR fallback — market-agnostic (Law 6).

The problem this solves (proven live in `docs/VALIDATION_TIER0.md`): primary filings are often
image-only or dynamic-render PDFs whose text layer is empty or near-empty. A naive `extract_text` then
returns almost nothing — and an agent that trusts it silently falls back to a *secondary* source
(screener/media), which is exactly the failure mode the project owner flagged and ADR-0014 guards against.

The rule enforced here: if a document cannot be read from its text layer and no OCR is available, that is
a **signal** (`complete=False`), never a silent blank. Downstream, an incomplete read on a legally-public
filing feeds the `disclosure_gap` flag ("why can't we read what must be disclosed?").

Everything is injectable so the logic is 100% testable offline with zero PDF/OCR binaries: pass a fake
`text_layer_fn` and/or a stub `ocr_backend`. The real pypdf/tesseract wrappers are thin and guarded.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Protocol, runtime_checkable


@runtime_checkable
class OcrBackend(Protocol):
    """A pluggable OCR engine. Implementations render each PDF page to an image and OCR it."""

    name: str

    def pages_to_text(self, pdf_bytes: bytes) -> list[str]:
        """Return recognised text per page, in page order."""
        ...


@dataclass(frozen=True)
class ExtractionResult:
    pages: list[str]
    method: str          # 'text_layer' | 'ocr' | 'text_layer+ocr' | 'empty'
    complete: bool        # False => too sparse to trust => treat as a data/disclosure signal
    chars_per_page: float

    @property
    def text(self) -> str:
        return "\n".join(self.pages)


def _mean_chars(pages: list[str]) -> float:
    return (sum(len(p.strip()) for p in pages) / len(pages)) if pages else 0.0


#: Runs of whitespace inside a layout-extracted line. Collapsed to exactly two spaces, which keeps the
#: *column boundary* visible (`tables.py` needs it to tell a note-reference column from a figure column)
#: while keeping the line short enough to read in a locator audit.
_COLUMN_GAP = re.compile(r"[ \t]{2,}")

#: How much of the plain read a laid-out page must retain to be preferred. Layout mode silently drops
#: rotated text, so a page that comes back much shorter has lost content, not whitespace.
_LAYOUT_COMPLETENESS = 0.9


def _normalise_layout(text: str) -> str:
    """Collapse a layout-extracted page's whitespace padding without losing the column structure."""
    return "\n".join(_COLUMN_GAP.sub("  ", line).rstrip() for line in text.splitlines())


def _pages_from_text_layer(pdf_bytes: bytes) -> list[str]:  # pragma: no cover - thin pypdf wrapper
    """Page text in LAYOUT mode, falling back to reading order where layout yields nothing.

    Why layout rather than pypdf's default reading order: in the default mode a filing's text layer
    reorders and *splits* a table row, and the split is invisible downstream. On the FY21 Alkyl Amines
    balance sheet the default mode emits

        (a)
         P
        roperty, Plant and Equipment 3  42,764.60  39,224.45

    — so a search for "Property, Plant and Equipment" misses, "Cash and Cash Equivalents" arrives as the
    orphan line "and Cash Equivalents 10  9,614.41", and worst of all `Inventories 7` ends up on its own
    line with its two figures on the NEXT one. That last case is not a miss but a *wrong answer*: FY21
    inventories entered the fact store as Rs 0.07cr against a true Rs 121.90cr, carrying a grade-A stamp,
    and was caught only because the FY22 report's comparative column contradicted it (`Overlap.classify`
    → `extraction_error`).

    Layout mode reconstructs the row — label, note reference and both figures on one line — for every one
    of the ten Alkyl Amines filings. It is slower, which is the whole of its cost, and the ingest is
    cached in bronze anyway.
    """
    import io

    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(pdf_bytes))
    pages: list[str] = []
    for page in reader.pages:
        plain = page.extract_text() or ""
        try:
            laid_out = _normalise_layout(page.extract_text(extraction_mode="layout") or "")
        except Exception:  # noqa: BLE001 - a page pypdf cannot lay out is still worth reading plainly
            laid_out = ""
        # pypdf warns "Rotated text discovered. Output will be incomplete." and DROPS the rotated block
        # rather than failing, so a sideways-printed table (these filings set the Schedule III ageing
        # tables that way) comes back short. Losing content is worse than losing column alignment, so the
        # plain read wins whenever the laid-out one is materially thinner.
        keep_layout = len(laid_out.strip()) >= _LAYOUT_COMPLETENESS * len(plain.strip())
        pages.append(laid_out if laid_out.strip() and keep_layout else plain)
    return pages


def extract_document(
    pdf_bytes: bytes,
    *,
    ocr_backend: OcrBackend | None = None,
    min_chars_per_page: float = 200.0,
    text_layer_fn: Callable[[bytes], list[str]] = _pages_from_text_layer,
) -> ExtractionResult:
    """Extract page text, falling back to OCR when the text layer is too sparse to trust.

    - Text layer is sufficient (>= ``min_chars_per_page``) → use it, ``complete=True``.
    - Too sparse and an ``ocr_backend`` is given → OCR; merge page-by-page (keep the text-layer page
      where it already has content, else the OCR page). ``complete`` reflects the merged density.
    - Too sparse and no OCR backend → return the sparse pages with ``complete=False`` (the signal).
    """
    pages = text_layer_fn(pdf_bytes)
    cpp = _mean_chars(pages)
    if cpp >= min_chars_per_page:
        return ExtractionResult(pages, "text_layer", True, cpp)

    if ocr_backend is not None:
        ocr_pages = ocr_backend.pages_to_text(pdf_bytes)
        merged = _merge_pages(pages, ocr_pages, min_chars_per_page)
        merged_cpp = _mean_chars(merged)
        used_any_text_layer = any(len(p.strip()) >= min_chars_per_page for p in pages)
        method = "text_layer+ocr" if used_any_text_layer else "ocr"
        return ExtractionResult(merged, method, merged_cpp >= min_chars_per_page, merged_cpp)

    method = "empty" if cpp == 0.0 else "text_layer"
    return ExtractionResult(pages, method, False, cpp)


def _merge_pages(text_pages: list[str], ocr_pages: list[str], floor: float) -> list[str]:
    """Page-by-page: keep the text-layer page when it already carries content, else take the OCR page."""
    n = max(len(text_pages), len(ocr_pages))
    out: list[str] = []
    for i in range(n):
        tl = text_pages[i] if i < len(text_pages) else ""
        oc = ocr_pages[i] if i < len(ocr_pages) else ""
        out.append(tl if len(tl.strip()) >= floor else oc)
    return out
