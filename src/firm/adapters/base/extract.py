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
