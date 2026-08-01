"""Parse an earnings-call transcript into dated, quoted guidance statements (Phase 3).

WHY THIS GENERALISES
Reg. 30 + Schedule III Part A Para A(15A) of the SEBI LODR obliges every listed company to publish the
transcript of each earnings call within five working days. So, as with the shareholding pattern, the
document is market-wide: a Reg-30 submission letter, a title page naming the call and its date, and a
speaker-labelled dialogue. A parser for one company's transcript is a parser for the market.

WHAT A "GUIDANCE STATEMENT" IS HERE
A sentence in which someone on the call attaches a number to the future — "around Rs. 150 crores we
forecast for next year", "we expect double digit growth around 10% to 15%". The parser records the
sentence VERBATIM with its page, so an agent can quote it and a reader can verify it. It classifies each
sentence as a statement or a question, because an analyst asking "do we expect 21%?" is not management
guiding 21% — collapsing the two would put words in management's mouth.

WHAT IT REFUSES TO DO
It does not attribute quotes to named speakers. The text layer of these PDFs routinely detaches the
speaker column from the dialogue (every name first, then every utterance), and a mis-attributed quote is
worse than an unattributed one — "the CFO said" is a claim about a person. Attribution is left to a
reader with the page number in hand.

It does not treat every number as a guidance value. Only figures anchored to a unit the sentence states
(a percentage, a rupee-crore amount) are extracted; bare numbers, calendar years and quarter labels stay
in the quote but never become a value — an unanchored number has no meaning an agent could safely cite.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

#: The title every transcript carries — the evidence this document IS an earnings-call transcript.
#: A concall *announcement* or an audio-recording letter must be refused, not skimmed for numbers.
_CALL_TITLE = re.compile(r"earnings\s+(?:conference\s+)?call|conference\s+call\s+transcript", re.I)
#: The title alone is not enough: the *announcement* of a call also says "earnings conference call".
#: What an announcement never carries is the transcript itself — the word "transcript" (every Reg-30
#: submission letter states it) or the moderator's dialogue. Found the hard way: the May-2022 intimation
#: letter, one page of dial-in numbers, parsed as a transcript with zero guidance instead of refusing.
_TRANSCRIPT_EVIDENCE = re.compile(r"\btranscript\b|^\s*moderator\s*:", re.I | re.M)

#: "May 12, 2025" — the form Indian transcripts print. Month names, never digits-only, so a share count
#: can never be misread as a date.
_MONTH = ("January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December")
_DATE = re.compile(r"\b(" + "|".join(_MONTH) + r")\s+(\d{1,2}),?\s+(20\d{2})\b", re.I)
#: The cover letter's own statement of when the call happened. Real letters write it with a weekday —
#: "held on Thursday, November 7, 2019" — and a pattern requiring the month immediately after "held on"
#: matched none of them, silently downgrading every call date to the title-page fallback.
_HELD_ON = re.compile(
    r"held\s+on\s+(?:[A-Za-z]+day,?\s+)?(" + "|".join(_MONTH) + r")\s+(\d{1,2}),?\s+(20\d{2})", re.I
)

#: "4QFY2025", "Q4 FY25", "Q4 FY23-24", "FY '24". The range form names the fiscal year twice — start and
#: end — and the Indian FY is named for the year it ENDS in, so the second token wins when present.
#: Without the range branch, "Q4 FY23-24" read as FY23: a whole year off, on a stated label.
_PERIOD = re.compile(
    r"(?:Q\s*([1-4])|([1-4])\s*Q)\s*FY\s*'?\s*(20\d{2}|\d{2})(?:\s*[-/]\s*'?(20\d{2}|\d{2}))?", re.I
)

#: A sentence is forward-looking when it carries one of these cues. Deliberately verbs-of-intent plus
#: horizon words: "was 20% last year" must not match, "we forecast Rs. 150 crores for next year" must.
_FORWARD_CUE = re.compile(
    r"\b(expect(?:ing|ed)?|guidance|guided?|forecast(?:ing)?|target(?:ing)?|aim(?:ing)?|"
    r"plan(?:ning)?|envisag\w*|outlook|going\s+forward|next\s+(?:year|quarter|fiscal)|"
    r"coming\s+(?:year|years|quarters?))\b",
    re.I,
)

#: Values are extracted ONLY with a stated unit. "15%" and "Rs. 150 crores" carry meaning; a bare "150"
#: carries none an agent could cite.
_PCT_VALUE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_CRORE_VALUE = re.compile(r"(?:Rs\.?|INR|₹)\s*(\d+(?:,\d{2,3})*(?:\.\d+)?)\s*crores?", re.I)

#: Topic, by the vocabulary of the sentence itself. First match wins; 'general' is the honest residue,
#: never a guess. These drive the fact METRIC LABEL only — the quote and value are what carry weight.
#: Prefix matches on purpose: "debottleneck" must catch "debottlenecking", "grow" must catch "growth".
_TOPICS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("capex", re.compile(r"\b(?:capex|capital\s+expenditure)", re.I)),
    ("margin", re.compile(r"\b(?:margin|ebitda)", re.I)),
    ("volume_growth", re.compile(r"\b(?:volume|tonn|grow)", re.I)),
    ("capacity", re.compile(r"\b(?:capacity|plant|commission|debottleneck)", re.I)),
    ("exports", re.compile(r"\bexport", re.I)),
    ("pricing", re.compile(r"\b(?:price|pricing|realisation|realization)", re.I)),
)

#: An analyst's ask does not always end in "?" — "Sir, just wanted to ask, any guidance regarding this
#: FY." reads as a statement by punctuation alone, and counting it as guidance puts the analyst's number
#: in management's mouth. These phrasings mark a sentence as a question regardless of its final mark.
_QUESTION_CUE = re.compile(
    r"\b(?:wanted\s+to\s+ask|can\s+you|could\s+you|would\s+you|any\s+guidance\s+(?:on|regarding|for))\b",
    re.I,
)

#: Page furniture to drop before sentences are assembled: a bare speaker label ("Kanchan Shinde:"),
#: a page footer, or the company-name running header.
_SPEAKER_LABEL = re.compile(r"^[A-Z][\w.'\- ]{0,40}:$")
_PAGE_FOOTER = re.compile(r"^page\s+\d+\s+of\s+\d+$", re.I)


@dataclass(frozen=True)
class GuidanceValue:
    """One unit-anchored figure inside a quoted sentence."""

    value: float
    unit: str  # 'pct' | 'inr_cr'


@dataclass(frozen=True)
class GuidanceStatement:
    """One forward-looking sentence, verbatim, with its page and its unit-anchored figures."""

    page: int
    quote: str
    kind: str  # 'statement' | 'question' — an analyst asking for a number is not management giving one
    topic: str
    values: tuple[GuidanceValue, ...] = ()


@dataclass(frozen=True)
class TranscriptSummary:
    """One call's parse, or an explicit refusal.

    `period_basis` mirrors `published_at_basis` in ir_pages.py: 'stated' when the title names the
    quarter, 'derived-from-call-date' when it was inferred from when the call happened — labelled so a
    reader never mistakes an inference for an observation.
    """

    located: bool
    call_date: str | None = None   # ISO — when the call happened
    cover_date: str | None = None  # ISO — the Reg-30 submission letter's date, when page 1 carries one
    period: str | None = None      # 'Q4FY25'
    period_basis: str | None = None
    guidance: tuple[GuidanceStatement, ...] = field(default=())
    rejected_because: str | None = None


def _iso(month_name: str, day: str, year: str) -> str:
    month = [m.lower() for m in _MONTH].index(month_name.lower()) + 1
    return f"{year}-{month:02d}-{int(day):02d}"


def _period_from_date(call_iso: str) -> str | None:
    """The quarter a call most plausibly discusses: the one that ended most recently before it.

    Results are due 45 days after quarter end (60 for Q4), and the call follows the results — so a call
    in May 2025 is about the quarter ended 31 March 2025. This is an inference, and it is labelled as one.
    """
    year, month = int(call_iso[:4]), int(call_iso[5:7])
    # Walk back to the most recent quarter end (Mar/Jun/Sep/Dec) strictly before the call month.
    quarter_ends = (3, 6, 9, 12)
    candidates = [(year, m) for m in quarter_ends if m < month] or [(year - 1, 12)]
    end_year, end_month = candidates[-1]
    fiscal_year = end_year + 1 if end_month >= 4 else end_year
    quarter = ((end_month - 4) % 12) // 3 + 1
    return f"Q{quarter}FY{fiscal_year % 100:02d}"


#: Abbreviations whose trailing dot must not end a sentence. "around Rs. 150 crores" split at "Rs."
#: strands the figure from its currency anchor, and every rupee value in the document goes unextracted.
_ABBREVIATION_TAIL = re.compile(r"\b(?:Rs|Mr|Mrs|Ms|Dr|No|vs|St)\.$")


def _sentences(page: str) -> list[str]:
    """The page's dialogue as sentences, with furniture and detached speaker labels removed."""
    kept = [
        line.strip() for line in page.splitlines()
        if line.strip() and not _SPEAKER_LABEL.match(line.strip())
        and not _PAGE_FOOTER.match(line.strip())
    ]
    text = re.sub(r"\s+", " ", " ".join(kept))
    out: list[str] = []
    start = 0
    for gap in re.finditer(r"(?<=[.?!])\s+", text):
        if _ABBREVIATION_TAIL.search(text[max(0, gap.start() - 6):gap.start()]):
            continue
        if text[start:gap.start()].strip():
            out.append(text[start:gap.start()].strip())
        start = gap.end()
    if text[start:].strip():
        out.append(text[start:].strip())
    return out


def _values(sentence: str) -> tuple[GuidanceValue, ...]:
    out = [GuidanceValue(float(m.group(1)), "pct") for m in _PCT_VALUE.finditer(sentence)]
    out += [
        GuidanceValue(float(m.group(1).replace(",", "")), "inr_cr")
        for m in _CRORE_VALUE.finditer(sentence)
    ]
    return tuple(out)


def _topic(sentence: str) -> str:
    for name, pattern in _TOPICS:
        if pattern.search(sentence):
            return name
    return "general"


def parse_transcript(pages: tuple[str, ...]) -> TranscriptSummary:
    """Call date, period and every forward-looking quoted sentence from a transcript's pages.

    Returns `located=False` with the reason when the document does not carry an earnings-call title —
    a concall announcement or a recording-availability letter must never be skimmed for numbers as if
    management had guided them.
    """
    text = "\n".join(pages)
    if not _CALL_TITLE.search(text):
        return TranscriptSummary(
            located=False,
            rejected_because="no earnings-call transcript title located — this document is not a "
                             "transcript and is not read as one",
        )
    if not _TRANSCRIPT_EVIDENCE.search(text):
        return TranscriptSummary(
            located=False,
            rejected_because="the document names an earnings call but carries no transcript — a call "
                             "announcement or recording letter is not read for guidance",
        )

    held = next((m for page in pages for m in [_HELD_ON.search(page)] if m), None)
    call_date: str | None = _iso(held.group(1), held.group(2), held.group(3)) if held else None
    if call_date is None:
        # The title page prints the call's date directly beneath the call's name.
        for page in pages:
            if _CALL_TITLE.search(page):
                dated = _DATE.search(page)
                if dated:
                    call_date = _iso(dated.group(1), dated.group(2), dated.group(3))
                    break

    # The Reg-30 letter is page 1 and opens with its own date — the earliest evidence of dissemination.
    # Only a date on or after the call can be a submission date (the letter cites earlier correspondence,
    # "with reference to our letter dated May 6"), and among the eligible dates the FIRST in print order
    # is the letter's own: taking the minimum instead collapsed cover date onto the call date, because
    # "held on May 12" is itself a date on the page.
    cover_date = None
    if pages:
        dates = [_iso(*m.groups()) for m in _DATE.finditer(pages[0])]
        cover_date = next((d for d in dates if call_date is None or d >= call_date), None)

    stated = next((m for page in pages for m in [_PERIOD.search(page)] if m), None)
    if stated is not None:
        quarter = stated.group(1) or stated.group(2)
        year_token = stated.group(4) or stated.group(3)  # the END year of a range names the FY
        year = int(year_token) % 100 if len(year_token) == 4 else int(year_token)
        period, period_basis = f"Q{quarter}FY{year:02d}", "stated"
    elif call_date is not None:
        period, period_basis = _period_from_date(call_date), "derived-from-call-date"
    else:
        period, period_basis = None, None

    seen: set[str] = set()
    guidance: list[GuidanceStatement] = []
    for index, page in enumerate(pages, start=1):
        for sentence in _sentences(page):
            if not (_FORWARD_CUE.search(sentence) and re.search(r"\d", sentence)):
                continue
            if sentence in seen:  # running headers repeat; a quote is recorded once
                continue
            seen.add(sentence)
            guidance.append(GuidanceStatement(
                page=index, quote=sentence,
                kind=("question" if sentence.rstrip().endswith("?") or _QUESTION_CUE.search(sentence)
                      else "statement"),
                topic=_topic(sentence), values=_values(sentence),
            ))

    return TranscriptSummary(
        located=True, call_date=call_date, cover_date=cover_date,
        period=period, period_basis=period_basis, guidance=tuple(guidance),
    )
