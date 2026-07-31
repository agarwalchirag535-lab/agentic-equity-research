"""Read a concall transcript into dated, attributed, page-bound turns (Phase 3, ADR-0037).

WHY A PARSER AND NOT A BLOB OF TEXT
`transcript_analyst`'s mandate is a *time series* over 12+ quarters: "the number quietly moving down over
four quarters", "which analysts stopped attending", "when the CFO stops giving forward numbers". None of
those questions can be asked of an undifferentiated wall of text. They need to know who spoke, in what
role, on what date, and whether the words were a question or an answer. That structure is what this module
recovers, and it is the difference between an agent that can do its job and one that can only bluff.

WHY THIS PRODUCES QUOTES AND NOT FACTS
A shareholding pattern states a number the company filed; a transcript states what a person said. Turning
"we expect margins to normalise" into a margin forecast would be the firm inventing a figure and
attributing it to management — Law 1 in its most tempting form, because the sentence *feels* quantitative.
So nothing here mints a `pnl:`-style fact. Every output is a verbatim quote bound to `(source, page,
speaker, date)`, and any judgment about it belongs to the agent, on the record, as an inference.

WHAT A MANAGEMENT CLAIM IS EVIDENCE OF
House rule: a management claim is data about *management*, not about the *business*. A guidance statement
extracted here is therefore evidence for a promise-vs-delivery scorecard, not an input to a forecast.

THE FORMAT THIS RELIES ON
Indian concall transcripts are near-uniformly produced to the same house style: a cover page naming
MANAGEMENT and MODERATOR with roles, then `Speaker Name: text` turns, with the moderator introducing each
analyst by name and firm. Parsing keys off that structure rather than off any one company's wording.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import date

#: `Kirat Patel: There are two aspects...` — a turn label. Deliberately strict about what a name looks
#: like: at most five words, letters/dots/hyphens only, no digits. A loose pattern turns every colon in
#: the body ("the reason is this: capacity") into a speaker change and shreds the turn structure.
_TURN = re.compile(r"^(?P<name>[A-Z][A-Za-z.'\-]*(?:\s+[A-Za-z.'\-]+){0,4}):\s+(?P<text>\S.*)$")

#: The cover-page roster: `MANAGEMENT: MR. KIRAT PATEL — EXECUTIVE DIRECTOR, ALKYL AMINES...`
_ROSTER_HEADING = re.compile(r"^\s*(MANAGEMENT|MODERATOR)\s*:\s*(.*)$", re.I)
#: `MR. KIRAT PATEL — EXECUTIVE DIRECTOR` / `MS. KANCHAN SHINDE - CHIEF FINANCIAL OFFICER`
_ROSTER_ENTRY = re.compile(
    r"\b(?:MR|MS|MRS|DR)\.?\s+(?P<name>[A-Z][A-Za-z.\s'\-]{2,40}?)\s*[—–\-]\s*(?P<role>[A-Za-z][^,\n]*)",
    re.M)

#: The words that make a phrase an OFFICE rather than an employer. Used by the fallback roster scan below,
#: where the separator is a comma and `Mr. Kumar Saumya, Ambit Capital` (an analyst and his broker) has to
#: be told apart from `Mr. Kirat Patel, Executive Director` (management and his office). Without the
#: keyword test a comma-separated scan recruits every analyst on the call onto the board.
_OFFICE_WORDS = (
    "director", "officer", "chairman", "chairperson", "managing", "president", "secretary",
    "treasurer", "ceo", "cfo", "coo", "cto", "founder", "promoter", "manager", "whole-time",
    "whole time", "head of", "vice chairman",
)
#: `Mr. Kirat Patel, Executive Director` — the roster as the HOST reads it out, which is where it lives on
#: the transcripts that carry no cover-page roster block at all. Five of Alkyl Amines' 14 transcripts are
#: that shape, and on those every management turn was being classified as an analyst question, so the call
#: produced no exchanges and no guidance quotes: the agent saw a 150-turn conversation with no management
#: in it.
_INTRODUCED = re.compile(
    r"\b(?:Mr|Ms|Mrs|Dr)s?\.?\s+(?P<name>[A-Z][A-Za-z.'\-]*(?:\s+[A-Z][A-Za-z.'\-]+){0,3})\s*[,—–-]\s*"
    r"(?P<role>[A-Za-z][A-Za-z ()&/'-]{2,60})")

#: The call date, as the cover page writes it: `November 08, 2023`.
_MONTHS = {m: i for i, m in enumerate(
    ("january", "february", "march", "april", "may", "june", "july", "august", "september",
     "october", "november", "december"), start=1)}
_CALL_DATE = re.compile(
    r"\b(" + "|".join(_MONTHS) + r")\s+(\d{1,2})\s*,?\s+(20\d{2})\b", re.I)
_CALL_DATE_DMY = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(" + "|".join(_MONTHS) + r")\s*,?\s+(20\d{2})\b", re.I)

#: `2QFY26 Earnings Call`, `Q3 FY2023 Earnings Call`, and — the form Alkyl Amines actually uses —
#: `2Q and 1HFY24 Earnings Conference Call`, where the quarter and the fiscal year are separated by the
#: half-year label. The third alternative allows that gap; without it the title says which quarter this is
#: and the parser answers "unknown".
_PERIOD = re.compile(
    r"\b([1-4])\s*Q\s*(?:FY)?['\s]*(\d{2,4})\b"
    r"|\bQ([1-4])\s*(?:FY)?['\s]*(\d{2,4})\b"
    r"|\b([1-4])\s*Q\b[^.\n]{0,24}?FY['\s]*(\d{2,4})\b",
    re.I,
)

#: The moderator's handover line names the analyst and their firm — the attendance register the
#: "which analysts stopped attending" question is answered from. The trailing `from <firm>` is required,
#: not optional: it is what separates "the line of Nirav Jamduia from Anvil Research" (a questioner) from
#: "hand over to you, sir" (the management opening remarks).
_ANALYST_INTRO = re.compile(
    r"(?:from the line of|hand(?:ing)?\s+(?:it\s+|the\s+)?(?:conference|floor|call)?\s*over to)\s+"
    r"(?:Mr|Ms|Mrs|Dr)?s?\.?\s*(?P<name>[A-Z][A-Za-z.'\-]*(?:\s+[A-Za-z.'\-]+){0,3})\s+from\s+"
    r"(?P<firm>[A-Z][^.]{2,60}?)\s*\.",
    re.I,
)

#: Forward-looking cues. A management turn carrying one of these is a PROMISE — the raw material for a
#: promise-vs-delivery scorecard. Kept as a published list rather than a model's judgment so the same
#: sentence is classified the same way in every quarter, which is the only way drift is measurable.
_FORWARD_CUES: tuple[str, ...] = (
    "we expect", "we anticipate", "we believe we will", "going forward", "we plan to", "we intend to",
    "we should be able", "we are targeting", "our target", "guidance", "we hope to", "likely to",
    "we aim to", "on track", "in the coming", "over the next", "by the end of", "we will be able",
    "we are confident", "we project", "should improve", "should be able to",
)

#: Cues that a question was answered with a refusal rather than an answer. Not a verdict — the agent
#: decides whether a deflection was reasonable — but the candidate set it has to look at.
_DEFLECTION_CUES: tuple[str, ...] = (
    "cannot share", "can't share", "not able to share", "we do not disclose", "we don't disclose",
    "not in a position to", "cannot comment", "can't comment", "difficult to say",
    "we would not like to", "wouldn't like to comment", "offline", "take that offline",
    "not something we disclose", "cannot quantify", "can't quantify", "no specific guidance",
)

_MODERATOR_NAMES = ("moderator", "operator")
#: Cover-page labels that look exactly like a turn (`MANAGEMENT: MR. KIRAT PATEL — ...`) and are not one.
#: Without this the roster block enrols "Management" as an analyst and the first real speaker's words are
#: attributed to a heading.
_NOT_SPEAKERS = frozenset({"management", "moderator team", "participants", "analysts", "company"})
#: A turn shorter than this is procedural ("Thank you.", "Yes."), not a statement worth quoting.
_MIN_QUOTE_CHARS = 40


@dataclass(frozen=True)
class Speaker:
    """A named participant and the role the cover page gave them."""

    name: str
    role: str

    @property
    def is_cfo(self) -> bool:
        return "financial officer" in self.role.lower() or self.role.strip().upper() == "CFO"


@dataclass(frozen=True)
class Turn:
    """One person speaking once, bound to the page it was said on."""

    speaker: str
    side: str            # 'management' | 'analyst' | 'moderator'
    text: str
    page: int

    @property
    def locator(self) -> str:
        return f"p.{self.page}"


@dataclass(frozen=True)
class Quote:
    """A verbatim extract with everything needed to cite it and nothing inferred from it."""

    speaker: str
    text: str
    page: int
    kind: str            # 'guidance' | 'deflection'


@dataclass(frozen=True)
class Exchange:
    """An analyst question and the answer it received — the unit a 'dodged question' is judged on."""

    analyst: str
    question: str
    answered_by: str | None
    answer: str
    page: int

    @property
    def deflected(self) -> bool:
        """Whether the answer carries an explicit refusal cue. A candidate, not a conclusion."""
        low = self.answer.lower()
        return any(cue in low for cue in _DEFLECTION_CUES)


@dataclass(frozen=True)
class TranscriptRead:
    """One earnings call, structured. `complete=False` means the PDF did not yield usable turns."""

    source: str
    held_on: date | None = None
    period: str | None = None
    management: tuple[Speaker, ...] = ()
    moderator: str | None = None
    analysts: tuple[str, ...] = ()
    turns: tuple[Turn, ...] = ()
    exchanges: tuple[Exchange, ...] = ()
    quotes: tuple[Quote, ...] = ()
    complete: bool = False
    rejected_because: str | None = None

    @property
    def guidance(self) -> tuple[Quote, ...]:
        return tuple(q for q in self.quotes if q.kind == "guidance")

    @property
    def deflections(self) -> tuple[Quote, ...]:
        return tuple(q for q in self.quotes if q.kind == "deflection")

    @property
    def label(self) -> str:
        """How this call is named in a report: `FY24Q2 (2023-11-08)`, or the filename if undated."""
        parts = [p for p in (self.period, self.held_on.isoformat() if self.held_on else None) if p]
        return " ".join(parts) if parts else self.source


def _call_date(text: str) -> date | None:
    named = _CALL_DATE.search(text)
    if named is not None:
        return date(int(named.group(3)), _MONTHS[named.group(1).lower()], int(named.group(2)))
    dmy = _CALL_DATE_DMY.search(text)
    if dmy is not None:
        return date(int(dmy.group(3)), _MONTHS[dmy.group(2).lower()], int(dmy.group(1)))
    return None


def _fiscal_period(text: str) -> str | None:
    """`2Q ... FY24` -> `FY24Q2`. Returns None rather than guessing when the header does not say."""
    found = _PERIOD.search(text)
    if found is None:
        return None
    quarter = found.group(1) or found.group(3) or found.group(5)
    year = found.group(2) or found.group(4) or found.group(6)
    if not quarter or not year:
        return None
    return f"FY{int(year) % 100:02d}Q{int(quarter)}"


def _is_office(role: str) -> bool:
    low = role.lower()
    return any(word in low for word in _OFFICE_WORDS)


def _reported_quarter(held_on: date) -> str:
    """The quarter an earnings call held on this date is reporting: the last one that had ENDED.

    Preferred over scraping the title, which produced a *wrong* label rather than a missing one — the
    16 May 2024 call came back `FY23Q4` because the title's comparative mention of the prior year matched
    first. A wrong period silently misfiles a call in the sequence, and the sequence is the entire value of
    this parser, so it is derived from the date instead. SEBI requires results within 45 days of a quarter
    end (60 for Q4), so a call always lands after its own quarter closed and before the next one does.
    """
    year, month = held_on.year, held_on.month
    end_month = ((month - 1) // 3) * 3          # last completed calendar quarter-end month
    if end_month == 0:
        year, end_month = year - 1, 12
    fiscal_year = year + 1 if end_month >= 4 else year
    quarter = ((end_month - 4) % 12) // 3 + 1
    return f"FY{fiscal_year % 100:02d}Q{quarter}"


def _roster(cover: str) -> tuple[tuple[Speaker, ...], str | None]:
    """Management and moderator, from the cover page's own roster block."""
    management: list[Speaker] = []
    moderator: str | None = None
    current: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        nonlocal moderator
        if current is None:
            return
        block = " ".join(buffer)
        for entry in _ROSTER_ENTRY.finditer(block):
            name = " ".join(w.title() for w in entry.group("name").split())
            role = entry.group("role").strip().title()
            if current.upper() == "MANAGEMENT":
                management.append(Speaker(name, role))
            elif moderator is None:
                moderator = name

    for line in cover.splitlines():
        heading = _ROSTER_HEADING.match(line)
        if heading is not None:
            flush()
            current, buffer = heading.group(1), [heading.group(2)]
            continue
        if current is not None:
            buffer.append(line)
    flush()
    return tuple(management), moderator


def _introduced_roster(text: str) -> tuple[Speaker, ...]:
    """Management as the HOST introduces them, for transcripts with no cover-page roster block.

    "From the management, we have with us Mr. Kirat Patel, Executive Director, and Mrs. Kanchan Shinde,
    Chief Financial Officer." Every Indian concall opens this way whether or not the PDF has a roster page,
    so it is the more reliable of the two sources — but only with `_is_office` guarding it, or the analyst
    introduced two sentences earlier as "Mr. Kumar Saumya, Ambit Capital" joins the board.
    """
    found: dict[str, Speaker] = {}
    for entry in _INTRODUCED.finditer(text):
        role = entry.group("role").strip()
        if not _is_office(role):
            continue
        name = " ".join(w.title() for w in entry.group("name").split())
        found.setdefault(name, Speaker(name, role.title()))
    return tuple(found.values())


def _side(name: str, management: set[str], moderator: str | None) -> str:
    low = name.lower()
    if low in _MODERATOR_NAMES or (moderator and low == moderator.lower()):
        return "moderator"
    surname = low.split()[-1] if low.split() else low
    for member in management:
        if low == member or surname and surname in member.split():
            return "management"
    return "analyst"


def parse_transcript(pages: tuple[str, ...], *, source: str = "") -> TranscriptRead:
    """Structure a concall transcript. An unreadable PDF returns `complete=False` with a reason.

    Never raises on a badly formed document: an unreadable transcript is a coverage gap to report, and a
    parser that throws would take the whole run down with it (ADR-0014 — an unreadable filing is a signal).
    """
    if not pages or not any(p.strip() for p in pages):
        return TranscriptRead(source=source, rejected_because="the PDF yielded no text layer")
    whole = "\n".join(pages)

    # The header block can sit on page 1, 2 or 3 depending on whether the PDF leads with the covering
    # letter to the exchanges. Read the first few pages as "the cover" rather than betting on one.
    cover = "\n".join(pages[:3])
    management, moderator = _roster(cover)
    # UNION, not fallback-if-empty. A cover-page roster lists who was scheduled to attend; the host's
    # introduction names who actually turned up, and the two disagree often enough that taking either alone
    # leaves real speakers unclassified.
    for speaker in _introduced_roster("\n".join(pages[:4])):
        if speaker.name.lower() not in {m.name.lower() for m in management}:
            management = management + (speaker,)
    management_keys = {m.name.lower() for m in management}

    # The date is on the cover AND repeated in every page header, so a cover that failed to yield one is
    # not a document without a date. Widen the search rather than report an undated call. The period is
    # then DERIVED from that date; the title is consulted only when the call is undated.
    held_on = _call_date(cover) or _call_date(whole)
    period = _reported_quarter(held_on) if held_on else (
        _fiscal_period(cover) or _fiscal_period(whole))

    turns: list[Turn] = []
    for page_number, page in enumerate(pages, start=1):
        speaker = side = None
        collected: list[str] = []
        for line in page.splitlines():
            match = _TURN.match(line.strip())
            if match is not None and match.group("name").strip().lower() in _NOT_SPEAKERS:
                match = None
            if match is not None:
                if speaker is not None and collected:
                    turns.append(Turn(speaker, side or "analyst",
                                      " ".join(collected).strip(), page_number))
                speaker = " ".join(w for w in match.group("name").split())
                side = _side(speaker, management_keys, moderator)
                collected = [match.group("text").strip()]
            elif speaker is not None and line.strip():
                collected.append(line.strip())
        if speaker is not None and collected:
            turns.append(Turn(speaker, side or "analyst", " ".join(collected).strip(), page_number))

    if not turns:
        return TranscriptRead(
            source=source, held_on=held_on, period=period,
            management=management, moderator=moderator,
            rejected_because="no `Speaker:` turns were found — the text layer may be image-only",
        )

    # The attendance register, from the moderator's own handovers plus anyone who spoke as an analyst.
    analysts: list[str] = []
    for turn in turns:
        if turn.side == "moderator":
            for intro in _ANALYST_INTRO.finditer(turn.text):
                name = " ".join(w.title() for w in intro.group("name").split())
                if name not in analysts:
                    analysts.append(name)
        elif turn.side == "analyst" and turn.speaker not in analysts:
            analysts.append(turn.speaker)

    # Pair each analyst turn with the management turn that answered it. The moderator's handovers sit
    # between exchanges, so a moderator turn closes the current question rather than answering it.
    exchanges: list[Exchange] = []
    pending: Turn | None = None
    for turn in turns:
        if turn.side == "analyst":
            pending = turn
        elif turn.side == "management" and pending is not None:
            exchanges.append(Exchange(
                analyst=pending.speaker, question=pending.text, answered_by=turn.speaker,
                answer=turn.text, page=turn.page,
            ))
            pending = None
        elif turn.side == "moderator":
            pending = None

    quotes: list[Quote] = []
    for turn in turns:
        if turn.side != "management" or len(turn.text) < _MIN_QUOTE_CHARS:
            continue
        low = turn.text.lower()
        if any(cue in low for cue in _FORWARD_CUES):
            quotes.append(Quote(turn.speaker, turn.text, turn.page, "guidance"))
        if any(cue in low for cue in _DEFLECTION_CUES):
            quotes.append(Quote(turn.speaker, turn.text, turn.page, "deflection"))

    return TranscriptRead(
        source=source, held_on=held_on, period=period,
        management=management, moderator=moderator, analysts=tuple(analysts),
        turns=tuple(turns), exchanges=tuple(exchanges), quotes=tuple(quotes), complete=True,
    )


def read_transcript(pdf_bytes: bytes, *, source: str = "") -> TranscriptRead:
    """Parse a transcript PDF, choosing the extraction that actually recovers the conversation.

    NEITHER READER WINS EVERY TIME, SO THE DOCUMENT DECIDES.
    These PDFs come from several transcription houses and are not one format. Some place the speaker
    column and the speech column such that stream-order extraction interleaves them correctly; on those the
    plain reader is clean and the layout reader mangles words, because reconstructing glyph runs from
    coordinates inserts spaces inside small-caps and kerned text. Others are genuinely two-column, and
    stream order returns every speaker name in a block followed by every paragraph in a block — on those
    the plain reader loses the attribution completely and the layout reader is the only one that works.

    Picking by *file* would be guessing. Picking by *result* is checkable: run both and keep the read that
    recovered more question-and-answer exchanges, falling back to turn count when neither found any. That
    is a measurement of the thing we actually need — an attributed conversation — rather than a proxy for
    it.
    """
    from firm.adapters.base.extract import extract_document, extract_layout

    reads = [
        parse_transcript(tuple(extract_document(pdf_bytes).pages), source=source),
        parse_transcript(tuple(extract_layout(pdf_bytes).pages), source=source),
    ]
    best = max(reads, key=lambda r: (len(r.exchanges), len(r.quotes), len(r.turns)))
    other = reads[0] if best is reads[1] else reads[1]

    # BACKFILL THE DATE FROM THE LOSING READ. Both reads are the same document, so a date either one
    # recovered is a date this call has — and the reader that wins on conversation structure is not always
    # the one that renders the cover-page date legibly (layout reconstruction can split `November 08` mid
    # token). Losing the date would be the expensive failure of the two: an undated call cannot be placed
    # in the quarter sequence, and the whole point of this parser is the sequence.
    if best.held_on is None and other.held_on is not None:
        best = replace(best, held_on=other.held_on)
    if best.period is None and other.period is not None:
        best = replace(best, period=other.period)
    return best


__all__ = [
    "Exchange",
    "Quote",
    "Speaker",
    "TranscriptRead",
    "Turn",
    "parse_transcript",
    "read_transcript",
]
