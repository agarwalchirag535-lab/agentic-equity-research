"""OCR via Apple's Vision framework — the backend that actually runs on this host (ADR-0041).

WHY THIS EXISTS WHEN A TESSERACT BACKEND ALREADY DID
`TesseractOcrBackend` was written and never runnable: it needs the tesseract and poppler *binaries*, and
neither is installed. So the firm had an OCR architecture, an `OcrBackend` protocol, an `extract_document`
that merges OCR pages and honestly marks `complete=False` — and no engine behind any of it. A scanned
filing therefore came back empty and was correctly reported as unreadable, forever.

That is not a corner case. Of 128 primary-source PDFs pulled from three companies, **20 are pure scans
with no text layer at all** — every one of City Union Bank's quarterly shareholding patterns. A listed
company is free to file a scan, so an equity-research firm that cannot read one has a permanent hole in
its coverage that no amount of parser work closes.

WHY VISION RATHER THAN TESSERACT
It ships with macOS. No brew, no system binaries, no admin rights — two pip packages into the project's
own venv. Apple's recogniser is also markedly better than tesseract on the exact thing these documents
are: photographed or faxed tables of figures. Tesseract remains available and the protocol is unchanged,
so a Linux host can inject the other backend without anything else moving.

WHAT IT DOES NOT DO
It does not make a scan as good as a text layer, and the pipeline must not pretend otherwise. OCR output
goes through the same `complete` test as any other extraction, and the SEBI category identity
(promoter % + public % = 100) still has to reconcile before a holding is reported — an OCR misread of
`71.96` as `7196` fails that test exactly as a text-layer misread does. OCR widens what can be attempted;
it does not lower the bar for what can be believed.
"""

from __future__ import annotations

import re

#: Vision's accurate recogniser is slower and materially better on dense numeric tables, which is what a
#: shareholding pattern is. Speed is irrelevant here — this runs once per document, into an immutable
#: bronze archive.
_ACCURATE = 1
#: Render scale, MEASURED not guessed. On City Union Bank's scanned shareholding patterns 2x yields 207
#: recognised characters per page and the category rows are unreadable; 3x yields ~1,880 and the table
#: parses. The scan is roughly 150dpi at source, so 3x is what puts the digits far enough apart for the
#: recogniser to separate them. Below this the failure is silent — Vision returns confident nonsense
#: rather than an error — which is why the number is pinned to an observation and not to intuition.
_RENDER_SCALE = 3.0
#: A page must yield at least this much text before its winning rotation is trusted for the whole
#: document. Below it the page is probably a cover or a divider and the four scores are noise.
_ORIENTATION_MIN_CHARS = 400

#: Words a regulatory filing in English cannot avoid. Used to SCORE an orientation, because character
#: count cannot: text recognised upside down comes back the same length and just as confidently — City
#: Union Bank's shareholding table read at 180 degrees produced 1,283 characters of "?Iiqnd" for "Public"
#: and "JaiowoJd" for "Promoter". Counting real words separates the two decisively, where counting
#: characters scores them equal and picks whichever came first.
_LEXICON = frozenset("""
the of and as at in to for a an is are no not total shares share held holding shareholding
promoter public category number percentage securities equity company statement table pattern
class voting rights capital outstanding form paid up nos name listed entity scrip code date
year quarter bank limited india
""".split())
#: A word has to be this long to count; "a"/"of" match too easily inside OCR noise.
_LEXICON_MIN_LEN = 3


def _english_score(text: str) -> float:
    """How much of this text is real English — the orientation test that character count cannot do.

    Returns recognised dictionary words. Upside-down or sideways recognition yields plenty of characters
    and almost no words, so the gap between the right orientation and the wrong one is large and does not
    need calibrating.
    """
    words = re.findall(r"[A-Za-z]{%d,}" % _LEXICON_MIN_LEN, text.lower())
    return float(sum(1 for w in words if w in _LEXICON))


class VisionOcrBackend:  # pragma: no cover - requires macOS frameworks, absent from CI
    """`OcrBackend` implemented on macOS Vision. Renders each page with Quartz, then recognises text."""

    name = "apple-vision"

    def __init__(self, scale: float = _RENDER_SCALE, languages: tuple[str, ...] = ("en-US",)) -> None:
        self._scale = scale
        self._languages = list(languages)

    def pages_to_text(self, pdf_bytes: bytes) -> list[str]:
        try:
            import Quartz
            import Vision
            from CoreFoundation import CFDataCreate
        except ImportError as exc:
            raise RuntimeError(
                "VisionOcrBackend needs `pyobjc-framework-Vision` and `pyobjc-framework-Quartz` "
                "(macOS only). Install them, or inject a different OcrBackend."
            ) from exc

        provider = Quartz.CGDataProviderCreateWithCFData(CFDataCreate(None, pdf_bytes, len(pdf_bytes)))
        document = Quartz.CGPDFDocumentCreateWithProvider(provider)
        if document is None:
            return []

        out: list[str] = []
        turns: int | None = None
        for index in range(1, Quartz.CGPDFDocumentGetNumberOfPages(document) + 1):
            page = Quartz.CGPDFDocumentGetPage(document, index)
            if page is None:
                out.append("")
                continue
            image = self._render(Quartz, page)
            # ORIENTATION IS REMEMBERED BUT NEVER ASSUMED. Trying four rotations on every page of a
            # 228-page filing would quadruple the slowest step in the pipeline, so the last winning
            # rotation is tried first and kept when it reads well.
            #
            # It cannot simply be locked, though, and this document is why: page 1 is an upright portrait
            # cover and pages 2-8 are landscape tables fed through the scanner sideways. Locking page 1's
            # answer gave 1,237 characters on the cover and almost nothing on the seven pages carrying the
            # actual table — a silent 8x loss, because Vision returns confident nonsense rather than an
            # error when it reads sideways text. "A scanner feeds every sheet the same way round" is a
            # reasonable belief and simply not true of these filings.
            text = "" if turns is None else self._recognise(
                Quartz, Vision, self._rotate(Quartz, image, turns))
            if len(text.strip()) < _ORIENTATION_MIN_CHARS:
                candidate, retry = self._best_orientation(Quartz, Vision, image)
                if len(retry.strip()) > len(text.strip()):
                    turns, text = candidate, retry
            out.append(text)
        return out

    def _best_orientation(
        self, Quartz: object, Vision: object, image: object
    ) -> tuple[int, str]:  # noqa: N803
        """Recognise the page at each 90-degree rotation and keep the reading that yields the most text.

        A SCAN HAS NO RELIABLE UP. City Union Bank's shareholding patterns are landscape tables fed
        through a portrait scanner, so the page is stored rotated a quarter turn and every line of it runs
        bottom-to-top. Vision read that as `lliii .` / `Iiiiiiw` / `111111` — not a failure it reports,
        just confident nonsense, which is the dangerous kind. The PDF `/Rotate` attribute says 0 because
        the rotation is baked into the scanned pixels, so it cannot be trusted either.

        Trying all four and scoring by recognised character count is crude and completely reliable: text
        read at the wrong orientation produces almost nothing, so the margin between right and wrong is
        an order of magnitude rather than a judgment call.
        """
        best_turns, best_text, best_score = 0, "", -1.0
        for quarter_turns in range(4):
            text = self._recognise(Quartz, Vision, self._rotate(Quartz, image, quarter_turns))
            score = _english_score(text)
            if score > best_score:
                best_turns, best_text, best_score = quarter_turns, text, score
        return best_turns, best_text

    def _rotate(self, Quartz: object, image: object, quarter_turns: int) -> object:  # noqa: N803
        """The image turned `quarter_turns` * 90 degrees anticlockwise."""
        if image is None or quarter_turns % 4 == 0:
            return image
        width = Quartz.CGImageGetWidth(image)
        height = Quartz.CGImageGetHeight(image)
        swapped = quarter_turns % 2 == 1
        out_w, out_h = (height, width) if swapped else (width, height)
        context = Quartz.CGBitmapContextCreate(
            None, out_w, out_h, 8, 0, Quartz.CGColorSpaceCreateDeviceRGB(),
            Quartz.kCGImageAlphaNoneSkipLast)
        Quartz.CGContextTranslateCTM(context, out_w / 2.0, out_h / 2.0)
        Quartz.CGContextRotateCTM(context, quarter_turns * 3.141592653589793 / 2.0)
        Quartz.CGContextDrawImage(
            context, Quartz.CGRectMake(-width / 2.0, -height / 2.0, width, height), image)
        return Quartz.CGBitmapContextCreateImage(context)

    def _render(self, Quartz: object, page: object) -> object:  # noqa: N803 - module handle, not a class
        """One PDF page as a CGImage at `self._scale`."""
        box = Quartz.CGPDFPageGetBoxRect(page, Quartz.kCGPDFMediaBox)
        width = max(int(box.size.width * self._scale), 1)
        height = max(int(box.size.height * self._scale), 1)
        colour_space = Quartz.CGColorSpaceCreateDeviceRGB()
        context = Quartz.CGBitmapContextCreate(
            None, width, height, 8, 0, colour_space, Quartz.kCGImageAlphaNoneSkipLast)
        # A scan is usually black on white; fill white first so a page with transparency does not OCR as
        # black-on-black.
        Quartz.CGContextSetRGBFillColor(context, 1.0, 1.0, 1.0, 1.0)
        Quartz.CGContextFillRect(context, Quartz.CGRectMake(0, 0, width, height))
        Quartz.CGContextScaleCTM(context, self._scale, self._scale)
        Quartz.CGContextTranslateCTM(context, -box.origin.x, -box.origin.y)
        Quartz.CGContextDrawPDFPage(context, page)
        return Quartz.CGBitmapContextCreateImage(context)

    def _recognise(self, Quartz: object, Vision: object, image: object) -> str:  # noqa: N803
        """Vision's recognised text for one rendered page, in reading order.

        Observations come back with a bounding box, so lines are re-sorted top-to-bottom then
        left-to-right. Vision's own ordering is confidence-driven and would scramble a table.
        """
        if image is None:
            return ""
        request = Vision.VNRecognizeTextRequest.alloc().init()
        request.setRecognitionLevel_(_ACCURATE)
        request.setUsesLanguageCorrection_(False)  # figures, not prose: autocorrect corrupts digits
        request.setRecognitionLanguages_(self._languages)

        handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(image, None)
        if not handler.performRequests_error_([request], None)[0]:
            return ""

        observations = request.results() or []
        placed: list[tuple[float, float, str]] = []
        for observation in observations:
            candidate = observation.topCandidates_(1)
            if not candidate:
                continue
            box = observation.boundingBox()
            # Vision's origin is bottom-left; negate y so a plain sort reads top-down.
            placed.append((-box.origin.y, box.origin.x, candidate[0].string()))

        lines: list[str] = []
        row: list[tuple[float, str]] = []
        current: float | None = None
        for y, x, text in sorted(placed):
            if current is None or abs(y - current) > 0.008:   # ~1 line height in normalised units
                if row:
                    lines.append(" ".join(t for _, t in sorted(row)))
                current, row = y, [(x, text)]
            else:
                row.append((x, text))
        if row:
            lines.append(" ".join(t for _, t in sorted(row)))
        return "\n".join(lines)


__all__ = ["VisionOcrBackend"]
