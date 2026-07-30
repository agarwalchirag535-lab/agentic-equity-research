"""A real OCR backend (Tesseract) implementing the `OcrBackend` protocol — optional, pluggable.

Kept out of the import path of the core so the compute/adapter logic stays dependency-free and
offline-testable (the extraction *logic* is tested with a stub backend). Install the extras to use it:
``pip install pdf2image pytesseract`` and have the Tesseract binary + poppler available on the host.

Whole module is pragma-no-cover: it shells out to native OCR that is intentionally absent from CI.
"""

from __future__ import annotations


class TesseractOcrBackend:  # pragma: no cover - requires native tesseract/poppler, not present in CI
    name = "tesseract"

    def __init__(self, dpi: int = 300, lang: str = "eng") -> None:
        self._dpi = dpi
        self._lang = lang

    def pages_to_text(self, pdf_bytes: bytes) -> list[str]:
        try:
            import pytesseract
            from pdf2image import convert_from_bytes
        except ImportError as exc:
            raise RuntimeError(
                "TesseractOcrBackend needs `pdf2image` and `pytesseract` (plus the tesseract and "
                "poppler binaries). Install the OCR extras or inject a different OcrBackend."
            ) from exc

        images = convert_from_bytes(pdf_bytes, dpi=self._dpi)
        return [pytesseract.image_to_string(img, lang=self._lang) for img in images]
