"""Tests for robust extraction + OCR fallback (adapters/base/extract.py). Offline — no PDF/OCR binaries."""

from firm.adapters.base.extract import ExtractionResult, extract_document


class _StubOcr:
    """A fake OCR backend: returns fixed dense text per page, so tests need no tesseract binary."""

    name = "stub"

    def __init__(self, pages: list[str]) -> None:
        self._pages = pages

    def pages_to_text(self, pdf_bytes: bytes) -> list[str]:
        return self._pages


_DENSE = "x" * 500   # a page with plenty of text-layer content
_SPARSE = "x" * 10   # a near-empty page (image-only render)


def test_text_layer_sufficient_no_ocr_needed():
    r = extract_document(b"", text_layer_fn=lambda _: [_DENSE, _DENSE], min_chars_per_page=200)
    assert r.method == "text_layer" and r.complete is True and r.chars_per_page >= 200


def test_sparse_without_ocr_marks_incomplete_signal():
    # image-only PDF, no OCR available -> NOT a silent blank; complete=False is the signal
    r = extract_document(b"", text_layer_fn=lambda _: [_SPARSE, _SPARSE], min_chars_per_page=200)
    assert r.complete is False and r.method == "text_layer"


def test_empty_text_layer_reports_empty_method():
    r = extract_document(b"", text_layer_fn=lambda _: ["", ""], min_chars_per_page=200)
    assert r.complete is False and r.method == "empty" and r.chars_per_page == 0.0


def test_ocr_fallback_recovers_image_pdf():
    # text layer empty, OCR returns dense pages -> recovered and complete
    r = extract_document(
        b"", text_layer_fn=lambda _: ["", ""], ocr_backend=_StubOcr([_DENSE, _DENSE]),
        min_chars_per_page=200,
    )
    assert r.complete is True and r.method == "ocr" and _DENSE in r.text


def test_ocr_merge_keeps_good_text_layer_pages():
    # doc is broadly unreadable (mean 155 < 200 -> OCR triggers), but page 0 has a usable text layer;
    # merge must KEEP page 0's text and OCR only the image-only page 1.
    good_p0 = "z" * 300  # >= floor, must be kept
    r = extract_document(
        b"", text_layer_fn=lambda _: [good_p0, _SPARSE], ocr_backend=_StubOcr(["OCR0", "y" * 500]),
        min_chars_per_page=200,
    )
    assert r.method == "text_layer+ocr"
    assert r.pages[0] == good_p0          # good text-layer page kept, not overwritten by OCR
    assert r.pages[1] == "y" * 500        # sparse page replaced by OCR


def test_ocr_still_incomplete_when_ocr_also_sparse():
    r = extract_document(
        b"", text_layer_fn=lambda _: ["", ""], ocr_backend=_StubOcr([_SPARSE, _SPARSE]),
        min_chars_per_page=200,
    )
    assert r.complete is False


def test_extraction_result_text_join():
    res = ExtractionResult(pages=["a", "b"], method="text_layer", complete=True, chars_per_page=1.0)
    assert res.text == "a\nb"
