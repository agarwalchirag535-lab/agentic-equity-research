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


def _pages_from_text_layer(pdf_bytes: bytes) -> list[str]:  # pragma: no cover - thin pypdf wrapper
    import io

    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(pdf_bytes))
    return [(page.extract_text() or "") for page in reader.pages]


#: Two fragments are on the same visual line if their baselines are within this many PDF units. Concall
#: transcripts set the speaker label and the first line of speech on exactly the same baseline, but
#: sub/superscripts and font changes shift it by a point or two, so an exact match is too strict.
_LINE_TOLERANCE = 2.5


def _pages_from_layout(pdf_bytes: bytes) -> list[str]:  # pragma: no cover - thin pypdf wrapper
    """Page text with the COLUMNS PRESERVED, reconstructed from glyph positions.

    WHY THIS EXISTS
    `extract_text()` returns a document in stream order, which for a two-column layout means the whole
    left column and then the whole right column. Concall transcripts are exactly that shape — speaker
    names down the left, speech down the right — so the default extraction produces

        Moderator:
        Nilesh Ghuge:
        Yogesh Kothari:
        <every paragraph, unattributed>

    and every turn loses its speaker. On Alkyl Amines' 14 transcripts that cost 11 of them: the parser
    saw 3-10 turns on a 19-page call and could pair no questions with answers at all.

    pypdf's `extraction_mode="layout"` returns an empty string on these files, so the fix is the visitor
    API: collect each fragment's baseline `(y, x)` from the text matrix, group fragments by baseline, and
    emit them left-to-right, top-to-bottom. That restores `Moderator: Ladies and gentlemen, ...` as one
    line, which is what the transcript grammar expects and what a human sees on the page.
    """
    import io

    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(pdf_bytes))
    pages: list[str] = []
    for page in reader.pages:
        fragments: list[tuple[float, float, str]] = []

        def visit(text: str, cm: object, tm: list[float], font: object, size: object,
                  into: list[tuple[float, float, str]] = fragments) -> None:
            # `into` is bound as a default rather than closed over: the visitor is redefined every
            # iteration and a late-binding closure would append every page's glyphs to the last page's list.
            if text.strip():
                into.append((tm[5], tm[4], text.strip()))

        page.extract_text(visitor_text=visit)
        if not fragments:
            pages.append("")
            continue

        lines: list[str] = []
        current_y: float | None = None
        row: list[tuple[float, str]] = []
        for y, x, text in sorted(fragments, key=lambda f: (-f[0], f[1])):
            if current_y is None or abs(y - current_y) > _LINE_TOLERANCE:
                if row:
                    lines.append(" ".join(t for _, t in sorted(row)))
                current_y, row = y, [(x, text)]
            else:
                row.append((x, text))
        if row:
            lines.append(" ".join(t for _, t in sorted(row)))
        pages.append("\n".join(lines))
    return pages


def extract_layout(pdf_bytes: bytes, **kwargs: object) -> ExtractionResult:
    """`extract_document` with column-preserving extraction — for documents whose LAYOUT carries meaning.

    Use it where position is part of the content (a transcript's speaker column, a two-column filing) and
    the plain reader where it is not. Everything else — the OCR fallback, the `complete=False` signal — is
    unchanged, because an unreadable document is a signal whichever reader was asked to read it.
    """
    return extract_document(pdf_bytes, text_layer_fn=_pages_from_layout, **kwargs)  # type: ignore[arg-type]


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
