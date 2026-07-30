"""Read INSIDE a note, not just its heading (ADR-0027).

THE GAP THIS CLOSES
`notes.py` enumerates the notes and `filing.py` dispositions them from whichever deterministic check touches
their category. After ADR-0024 the FY26 Alkyl Amines filing reached 100% note coverage and **0% substantive**
— every note enumerated, not one read. So the questions that matter most stayed unanswered: what the
related-party transactions actually were, whether the promoter borrowed from the company, what the directors
were paid. Those live in the note *body*, and nothing read the body.

WHAT MAKES THIS SAFE RATHER THAN A GUESS
The failure mode here is not a wrong number, it is a **false clean**. "I read the related-party note and found
no loans to promoters" and "I could not find the related-party note" produce the same empty result and mean
opposite things — the first is evidence of good governance, the second is evidence of nothing. Every function
below therefore returns a result that distinguishes them explicitly: `located=False` means the note was never
found and no conclusion may be drawn; `located=True` with an empty category set means the note was read and
those transaction types genuinely are not in it.

That distinction is the whole reason this module can make a note *substantive* (ADR-0017) instead of merely
covered.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from firm.adapters.base.tables import numbers_on_line, page_unit_hint, to_canonical_crore

#: A numbered note heading: "41 RELATED PARTY DISCLOSURES", "40 List of Related Parties and their ...".
_NOTE_HEADING = re.compile(r"^\s*(\d{1,2})\s+([A-Za-z][A-Za-z ,&/'\-()]{5,70})\s*$")

#: Transaction categories an Ind AS 24 related-party note discloses. Each is a DIFFERENT governance question,
#: so they are tracked separately rather than collapsed into "has related-party transactions".
_RP_CATEGORIES: dict[str, re.Pattern[str]] = {
    # The channel that matters most: value moved at a price nobody negotiated.
    "sales": re.compile(r"\bsale[s]?\s+of\s+(goods|products|materials)|\brevenue\s+from\s+related", re.I),
    "purchases": re.compile(r"\bpurchase[s]?\s+of\s+(goods|materials|raw)", re.I),
    # Money out of the listed company and into a promoter vehicle.
    "loans_given": re.compile(r"\bloans?\s+(given|granted|advanced)|\badvances?\s+(given|to)\b", re.I),
    "loans_taken": re.compile(r"\bloans?\s+(taken|received|accepted)|\bdeposits?\s+accepted\b", re.I),
    "guarantees": re.compile(r"\bguarantee[s]?\b", re.I),
    "investments": re.compile(r"\binvestment[s]?\s+(in|made)\b", re.I),
    # Legitimate but must be sized: this is what the Alkyl Amines note contains, and only this.
    "remuneration": re.compile(
        r"remuneration|sitting\s*fee|commission\b|managerial\s+remuneration", re.I),
}

#: Running headers, footers, page numbers, column captions and footnotes. Every PDF page carries them and
#: they all parse as numbers: the FY26 note summed "120" (a page number), "26" (from "Report
#: 2025-2026Website:") and "40" (from "[with Note 40 (I) and (II) above]") into directors' pay, inflating
#: ₹27.7cr to ₹52.3cr. A note body is page furniture plus content, and only the content is data.
_PAGE_FURNITURE = re.compile(
    r"annual\s+report|website|www\.|^\s*\d{1,3}\s*$|particulars|with\s+note|in\s+lakhs|"
    r"figures\s+in\s+brackets|pertain\s+to|^\s*\(|includes\s+the\s+contribution|"
    r"key\s+management\s+personnel|and\s+their\s+relatives",
    re.I,
)
#: A party row: a name or sub-label, then its figure. Anchors the label to the START of the line so a
#: sentence that merely happens to contain digits cannot qualify.
_PARTY_ROW = re.compile(r"^[A-Za-z][A-Za-z.\s*'&,\-()]{1,44}?\s+[`\d(]")

#: Lines that mean "we looked and there was nothing", which is a finding in its own right.
_EXPLICIT_NIL = re.compile(
    r"no\s+amount\s+(was\s+)?(written\s+off|written\s+back)|"
    r"there\s+(was|were)\s+no\s+(such\s+)?transaction|\bnil\b",
    re.I,
)


@dataclass(frozen=True)
class NoteBody:
    """One note's text, with the page it starts on. `located=False` means it was never found."""

    number: int | None
    title: str
    text: str
    page: int
    located: bool

    @property
    def locator(self) -> str:
        return f"p.{self.page}" if self.located else "not found"


def find_note_body(pages: tuple[str, ...], title_pattern: str) -> NoteBody:
    """The body of the numbered note whose heading matches ``title_pattern``, to the next note heading.

    Searched from the BACK of the document forward: an annual report mentions "Related Party" in the
    directors' report, the corporate-governance report and the BRSR long before the audited note appears, and
    the audited note is the one with the figures. Returns `located=False` rather than an empty string when no
    heading matches, so a caller can never mistake "not found" for "found and empty".
    """
    pattern = re.compile(title_pattern, re.I)
    for index in range(len(pages) - 1, -1, -1):
        lines = pages[index].splitlines()
        for line_no, line in enumerate(lines):
            heading = _NOTE_HEADING.match(line)
            if heading is None or not pattern.search(heading.group(2)):
                continue
            # Body runs to the next numbered heading — which may be further down THIS page. Scanning only
            # the following pages was wrong and hid behind a coincidence: on the FY26 filing note 41 ends on
            # p.121 and note 42 starts on p.122, so it worked. Where two notes share a page it swept the
            # next note's figures in, and the neighbour of a related-party note is Earnings Per Share, whose
            # first row is net profit — ₹17,999.91 lakh landing in directors' remuneration.
            body: list[str] = []
            for rest in lines[line_no + 1:]:
                nxt = _NOTE_HEADING.match(rest)
                if nxt is not None and int(nxt.group(1)) != int(heading.group(1)):
                    return NoteBody(
                        number=int(heading.group(1)), title=heading.group(2).strip(),
                        text="\n".join(body), page=index + 1, located=True,
                    )
                body.append(rest)
            for following in pages[index + 1:index + 4]:
                stop = False
                for next_line in following.splitlines():
                    nxt = _NOTE_HEADING.match(next_line)
                    if nxt is not None and int(nxt.group(1)) != int(heading.group(1)):
                        stop = True
                        break
                    body.append(next_line)
                if stop:
                    break
            return NoteBody(
                number=int(heading.group(1)), title=heading.group(2).strip(),
                text="\n".join(body), page=index + 1, located=True,
            )
    return NoteBody(number=None, title="", text="", page=0, located=False)


@dataclass(frozen=True)
class RelatedPartySummary:
    """What the Ind AS 24 note actually discloses — the governance question, answered or refused."""

    located: bool
    note_number: int | None = None
    page: int = 0
    categories: frozenset[str] = field(default_factory=frozenset)
    remuneration_cr: float | None = None
    explicit_nil_statement: bool = False
    lines_sampled: tuple[str, ...] = ()

    @property
    def locator(self) -> str:
        return f"note {self.note_number} p.{self.page}" if self.located else "related-party note not found"

    @property
    def has_promoter_lending(self) -> bool | None:
        """True/False only when the note was read; None when it was not.

        The tri-state is the point. `False` here is a real, publishable governance finding — the company did
        not lend to its promoters. `None` means we cannot say, and must not imply otherwise.
        """
        if not self.located:
            return None
        return bool({"loans_given", "guarantees"} & self.categories)

    @property
    def only_remuneration(self) -> bool:
        """The note discloses director pay and nothing else — Alkyl Amines FY26.

        Worth naming as its own condition: it means the related-party channel carries no goods, no money and
        no guarantees, which is the strongest thing an Ind AS 24 note can say about a promoter group.
        """
        return self.located and self.categories == frozenset({"remuneration"})


def related_party_summary(pages: tuple[str, ...]) -> RelatedPartySummary:
    """Parse the related-party disclosures note into categories present and total remuneration.

    Remuneration is summed from the lines that name a category and carry figures. Indian notes print the
    prior year in brackets beneath the current one, and `numbers_on_line` already reads "(1,398.06)" as a
    NEGATIVE — so only the first (current-year) figure on each line is taken, and bracketed comparatives are
    skipped rather than subtracted.
    """
    note = find_note_body(pages, r"related\s+part")
    if not note.located:
        return RelatedPartySummary(located=False)

    unit = page_unit_hint(pages[note.page - 1]) or "INR_lakh"
    present: set[str] = set()
    remuneration_total = 0.0
    sampled: list[str] = []

    # These notes are BLOCK-structured, not row-structured. A category heading is followed by one line per
    # party, each carrying that party's figure:
    #
    #     Directors' Remuneration/ Commission & Sitting Fees:      <- the category
    #     Yogesh Kothari *  1,360.50                               <- a party and its figure
    #      (1,398.06)                                              <- last year, in brackets
    #     Kirat Patel *  609.04
    #
    # Summing only the lines that themselves name the category therefore missed every actual payment and
    # returned ₹2.86cr against a real ₹27.6cr — it caught the "Sitting Fees" sub-labels and nothing else. So
    # the category is carried forward as state and each following figure is attributed to it.
    current: str | None = None
    for raw in note.text.splitlines():
        line = raw.strip()
        if not line:
            continue
        values = [v for v in numbers_on_line(line) if v > 0]
        matched = [name for name, pattern in _RP_CATEGORIES.items() if pattern.search(line)]
        if matched:
            present.update(matched)
            # A line naming a category opens a block; if it also carries its own figure it is a row, and
            # both readings are handled by attributing the figure below.
            current = matched[0] if "remuneration" not in matched else "remuneration"
        if not values or current is None:
            continue
        # Only a genuine party row contributes. Without this the sum absorbs page numbers and headers.
        if _PAGE_FURNITURE.search(line) or not _PARTY_ROW.match(line):
            continue
        # Bracketed comparatives are the prior year and `numbers_on_line` reads them as negative, so the
        # positive filter above already drops them. Only the first figure on a line is the current year:
        # anything further along is a second column (a different party grouping).
        if current == "remuneration":
            remuneration_total += values[0]
            sampled.append(line[:90])

    converted = to_canonical_crore(remuneration_total, unit) if remuneration_total else None
    return RelatedPartySummary(
        located=True, note_number=note.number, page=note.page,
        categories=frozenset(present), remuneration_cr=converted,
        explicit_nil_statement=bool(_EXPLICIT_NIL.search(note.text)),
        lines_sampled=tuple(sampled[:12]),
    )
