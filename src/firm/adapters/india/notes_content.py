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
from typing import Mapping, Sequence

from firm.adapters.base.tables import numbers_on_line, page_unit_hint, to_canonical_crore
from firm.adapters.india.notes import Note, enumerate_notes, notes_section_start

#: Note headings come from `notes.enumerate_notes` (ADR-0040). This module used to carry its OWN, weaker
#: heading pattern — a bare one-or-two-digit number followed by a title — and the duplication was not
#: harmless. It matched the related-party note by luck and matched nothing else: `find_note_body` could
#: not locate the inventories, borrowings or contingent-liabilities notes in a real filing, because those
#: headings carry a trailing unit marker ("9 INVENTORIES ` In Lakhs") that ADR-0037 had already taught the
#: enumerator to strip, and some carry a letter suffix ("36a") that ADR-0040 taught it to accept. Two
#: patterns for one concept means the second one is always the stale one.

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
    suffix: str = ""

    @property
    def label(self) -> str:
        return f"{self.number}{self.suffix}" if self.number is not None else ""

    @property
    def locator(self) -> str:
        return f"note {self.label} p.{self.page}" if self.located else "not found"


#: How far a note body may run past its own heading when the next enumerated note is distant. Two pages
#: covers every real multi-page note seen (the related-party note spans p.121-122); beyond that, sparse
#: enumeration is the likelier explanation than a genuinely enormous note.
_MAX_NOTE_PAGES = 2


def _body_between(pages: tuple[str, ...], note: Note, nxt: Note | None) -> str:
    """The text from just after ``note``'s heading up to ``nxt``'s heading.

    The end boundary is load-bearing and has been got wrong twice. A body that runs to the end of its page
    sweeps the NEXT note's figures in, and the neighbour of a related-party note is Earnings Per Share,
    whose first row is net profit — ₹17,999.91 lakh landing in directors' remuneration (ADR-0027).

    And the LAST enumerated note has no next heading to stop at, so it must stop at the end of its own
    page. Running on into the following pages walks straight out of the notes and into the auditor's
    report, where "corporate guarantees given on behalf of related parties" is a sentence about risk — and
    reading it as a related-party category fires `promoter_lending`, which is a SEVERE flag and an
    automatic hard fail. Under-reading a note loses a figure; over-reading one invents an accusation.
    """
    # ...and a note may not run more than `_MAX_NOTE_PAGES` beyond its own heading even when the next
    # enumerated note is further away than that. Enumeration is sparse wherever a heading style defeats
    # the matcher, so "the next note" can be four pages on — and the body then swallows the auditor's
    # report in between. That is not hypothetical: it turned the sentence "Loans or advances to
    # promoters: NIL" into a related-party `loans_given` category and fired `promoter_lending`, a SEVERE
    # flag and an automatic hard fail, against a company whose filing says the opposite of what was read.
    last_page = min(nxt.page if nxt is not None else note.page, note.page + _MAX_NOTE_PAGES)
    out: list[str] = []
    for page_no in range(note.page, last_page + 1):
        if page_no > len(pages):
            break
        lines = pages[page_no - 1].splitlines()
        start = note.line if page_no == note.page else 0
        end = (nxt.line - 1) if (nxt is not None and page_no == nxt.page) else len(lines)
        out.extend(lines[start:end])
    return "\n".join(out)


def find_note_bodies(pages: tuple[str, ...], title_pattern: str) -> tuple[NoteBody, ...]:
    """Every enumerated note whose TITLE matches ``title_pattern``, in document order.

    Some subjects are split across notes the filing numbers separately — borrowings are routinely a
    non-current note and a current one — so a reader that can see only one of them reports half a balance
    as the whole. Returns an empty tuple when nothing matches, which the caller must distinguish from a
    note that was found and had nothing in it.
    """
    notes = enumerate_notes(pages, first_page=notes_section_start(pages))
    pattern = re.compile(title_pattern, re.I)
    out: list[NoteBody] = []
    for i, note in enumerate(notes):
        if not pattern.search(note.title):
            continue
        nxt = notes[i + 1] if i + 1 < len(notes) else None
        out.append(NoteBody(
            number=note.number, title=note.title, text=_body_between(pages, note, nxt),
            page=note.page, located=True, suffix=note.suffix,
        ))
    return tuple(out)


def find_note_body(pages: tuple[str, ...], title_pattern: str) -> NoteBody:
    """The LAST enumerated note whose heading matches ``title_pattern``.

    Last rather than first, deliberately: an annual report names "Related Party" in the directors' report,
    the corporate-governance report and the BRSR, and where two audited notes match ("40 List of Related
    Parties", "41 Related Party Disclosures") the later one is the one carrying the figures. Returns
    `located=False` rather than an empty string when nothing matches, so a caller can never mistake
    "not found" for "found and empty" — the distinction this whole module exists to preserve.
    """
    found = find_note_bodies(pages, title_pattern)
    return found[-1] if found else NoteBody(number=None, title="", text="", page=0, located=False)


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


# --------------------------------------------------------------------------------------------------
# Reading a note's TABLE, not just its prose (ADR-0040).
#
# The related-party reader above answers a categorical question ("did any value move to a promoter?").
# The three readers below answer quantitative ones — what inventory is made of, what the company owes
# and on what terms, what it is being sued for — and they share one problem, so they share one solution.
# --------------------------------------------------------------------------------------------------

#: A note row: everything up to the figures is the label, and the LAST two figures are the two columns.
#:
#: Last two, not first two, and this is the rule that makes these tables readable at all. Indian notes
#: routinely print an amount INSIDE the label — "Raw materials (includes materials in transit of
#: `2,857.50 lakh; P.Y. `3,322.22 lakh) 13,816.62 13,223.01" carries four figures, of which the first two
#: are parenthetical asides and only the last two are the columns. Taking the first two reads a
#: ₹28.6cr in-transit disclosure as the whole ₹138cr raw-material balance.
_MIN_LABEL = re.compile(r"^[^\d]*[A-Za-z]")

#: Everything on a note page that is not a row of the table. Deliberately NOT `_PAGE_FURNITURE`, which is
#: tuned for the related-party note and excludes any line starting with "(" — the bracketed prior-year
#: comparatives there, but "(a) Raw Materials" here. Reusing it drops every component row of an Indian
#: inventory note, which is exactly the lettered-list style these tables use.
#:
#: Two things must go. The running footer ("Annual Report 2025-2026Website: www.alkylamines.com 120")
#: parses as a ₹20.25cr row. And the two-line column caption — "Particulars As at / March 31, 2026 / As at
#: / March 31, 2025" — puts a day-of-month and a year on one line, so "March 31, 2026" reads as the row
#: ("March", 31.0, 2026.0). Neither is data; both land between the printed total and the next note, where
#: a component-versus-total reconciliation would blame the company for our own footer.
_TABLE_FURNITURE = re.compile(
    r"annual\s+report|website|www\.|^\s*\d{1,3}\s*$|"
    r"^\s*\(?\s*all\s+amounts\s+are\s+in|^\s*\(?\s*(?:`|₹|Rs\.?|H)?\s*in\s+(?:lakhs?|crores?)\s*\)?\s*$|"
    r"^\s*(?:particulars|as\s+at\b|as\s+on\b|for\s+the\s+year\b)|"
    r"^\s*(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d",
    re.I,
)

#: Rows that are sums rather than components. Kept apart because a component set that includes its own
#: total double-counts, and because the printed total is what the components are checked against.
_SUB_TOTAL_ROW = re.compile(r"^\s*(sub\s*-?\s*total|gross\s+total)", re.I)
_TOTAL_ROW = re.compile(r"^\s*total\b", re.I)
_LESS_ROW = re.compile(r"^\s*less\s*:", re.I)


#: A figure OR a lone dash standing for nil. The dash must hold its column, and this is not a nicety:
#: "Total  -    360.45" is a company that repaid its borrowings — nil this year, ₹3.60cr last year.
#: Dropping the dash leaves ONE number, which is then read as the current column, and the report states
#: that a debt-free company owes ₹3.60cr, sourced grade A to the audited balance sheet. `ageing.py` learned
#: this on the bucket columns (ADR-0038); a note table has exactly the same shape and the same trap.
_FIGURE_OR_NIL = re.compile(r"\(?-?\d[\d,]*(?:\.\d+)?\)?|(?<![\w.])-(?![\w.])")


def _values_with_nil_dashes(line: str) -> tuple[float, ...]:
    """Figures on a row with '-' read as 0.0, falling back to the shared reader when no dash is present.

    `numbers_on_line` carries the note-cross-reference and percentage handling this module also needs, so
    it stays the default; the dash-aware path only takes over on rows that actually print one.
    """
    if not re.search(r"(?<![\w.])-(?![\w.\d])", line):
        return numbers_on_line(line)
    out: list[float] = []
    for match in _FIGURE_OR_NIL.finditer(line):
        token = match.group(0)
        if token == "-":
            out.append(0.0)
            continue
        cleaned = token.strip("()").replace(",", "")
        try:
            out.append(float(cleaned))
        except ValueError:                                  # pragma: no cover - guarded by the pattern
            continue
    return tuple(out)


@dataclass(frozen=True)
class NoteLine:
    """One row of a note table, in canonical ₹ crore."""

    label: str
    current: float
    prior: float | None = None


def note_lines(body: NoteBody, pages: tuple[str, ...]) -> tuple[NoteLine, ...]:
    """Every figure-bearing row of a note, converted to ₹ crore, in print order.

    A row whose page declares no resolvable unit is DROPPED rather than assumed to be crore — the
    ADR-0024 rule. A wrong scale is indistinguishable from a wrong number once it carries a grade-A
    provenance, and these figures are destined for the fact store.
    """
    unit = page_unit_hint(pages[body.page - 1]) if 0 < body.page <= len(pages) else ""
    if not unit:
        return ()
    out: list[NoteLine] = []
    for raw in body.text.splitlines():
        line = raw.strip()
        if not line or not _MIN_LABEL.match(line):
            continue
        # Page furniture parses as data. The running footer "Annual Report 2025-2026Website:
        # www.alkylamines.com 120" yields (2025, 2026, 120) and lands in the table as a ₹20.25cr row
        # between the printed total and the next note — the same defect ADR-0027 fixed for the
        # related-party reader, and the reason that filter is shared rather than re-invented here.
        if _TABLE_FURNITURE.search(line):
            continue
        values = _values_with_nil_dashes(line)
        if not values:
            continue
        columns = values[-2:] if len(values) >= 2 else values
        # The label is everything before the trailing figure block. Located by scanning back from the end
        # rather than forward from the first digit, because the first digit is often inside the label.
        cut = re.search(r"[\d(][\d,.\s()`-]*$", line)
        label = (line[:cut.start()] if cut else line).strip(" .:-–")
        converted = [to_canonical_crore(abs(v), unit) for v in columns]
        if any(c is None for c in converted):
            continue
        out.append(NoteLine(
            label=label, current=converted[0],                        # type: ignore[arg-type]
            prior=converted[1] if len(converted) > 1 else None,       # type: ignore[arg-type]
        ))
        # THE TABLE ENDS AT ITS OWN TOTAL. What follows is footnote prose, and it carries amounts:
        # "* Includes ` 21.07 lakhs deposited with CESTAT", "H546.54 lakh was paid under protest". Read
        # as rows those become ₹0.21cr and ₹5.47cr line items sitting after the total — which is both a
        # phantom balance and a guaranteed failure of the components-versus-total reconciliation, i.e. a
        # finding against the company caused entirely by our reading past the end of the table.
        if _TOTAL_ROW.match(label):
            break
    return tuple(out)


def _bucket(lines: Sequence[NoteLine], patterns: Mapping[str, re.Pattern[str]]) -> dict[str, float]:
    """Sum component rows into named buckets. First matching bucket wins, so order the map specifically."""
    out: dict[str, float] = {}
    for line in lines:
        if _TOTAL_ROW.match(line.label) or _SUB_TOTAL_ROW.match(line.label) or _LESS_ROW.match(line.label):
            continue
        for name, pattern in patterns.items():
            if pattern.search(line.label):
                out[name] = out.get(name, 0.0) + line.current
                break
    return out


def _printed_total(lines: Sequence[NoteLine]) -> float | None:
    """The note's own 'Total' row — what the components are checked against, never a sum we invented."""
    totals = [ln.current for ln in lines if _TOTAL_ROW.match(ln.label)]
    return totals[-1] if totals else None


def _reconciles(components: Mapping[str, float], total: float | None, tolerance: float) -> bool:
    """Do the component rows add up to the note's own printed total?

    The ageing schedules' alignment contract (ADR-0038), applied to note tables. A split that does not
    reconcile is not merely imprecise — it means a row was missed, misread, or picked up from outside the
    table, and any share computed from it is wrong in an unknown direction. Callers keep the total and
    withhold the split.
    """
    if total is None or total <= 0 or not components:
        return False
    return abs(sum(components.values()) - total) <= max(tolerance * total, 0.05)


#: Inventory components, ordered most specific first — "raw materials" must not be eaten by a generic
#: "materials", and packing materials are a consumable rather than an input to the product.
_INVENTORY_BUCKETS: dict[str, re.Pattern[str]] = {
    "finished_goods": re.compile(r"finished\s+goods|stock[\s-]*in[\s-]*trade", re.I),
    "work_in_progress": re.compile(r"work[\s-]*in[\s-]*progress|semi[\s-]*finished", re.I),
    "raw_materials": re.compile(r"raw\s+material", re.I),
    "packing_materials": re.compile(r"packing\s+material|packaging", re.I),
    "stores_and_spares": re.compile(r"stores?\s+(and|&)\s+spares?|consumables?", re.I),
    "other": re.compile(r"\bother|fuel|food|beverage|housekeeping|by[\s-]*product|scrap", re.I),
}

#: The write-down line. Its ABSENCE on a large book is the forensic point, so it is read separately from
#: the components rather than netted into them.
_INVENTORY_PROVISION = re.compile(
    r"provision|write[\s-]*down|write[\s-]*off|obsolescence|obsolete|diminution|impairment", re.I)


@dataclass(frozen=True)
class InventorySummary:
    """What the inventory is actually MADE OF, and what the company has written off it.

    The balance-sheet line says how much inventory there is. Only the note says what it is, and the
    composition is the finding: a rising finished-goods share is stock the channel did not absorb, while a
    rising raw-material share is a company buying ahead. Both move the same total in the same direction.
    """

    located: bool
    note_label: str = ""
    page: int = 0
    total_cr: float | None = None
    gross_cr: float | None = None
    provision_cr: float | None = None
    prior_gross_cr: float | None = None
    components: Mapping[str, float] = field(default_factory=dict)
    prior_components: Mapping[str, float] = field(default_factory=dict)
    reconciled: bool = False
    reason: str = ""

    @property
    def locator(self) -> str:
        return f"note {self.note_label} p.{self.page}" if self.located else "inventory note not found"

    @property
    def finished_goods_share(self) -> float | None:
        """Share of the book that is finished goods — None unless the split reconciled to the total."""
        if not self.reconciled or not self.gross_cr:
            return None
        return self.components.get("finished_goods", 0.0) / self.gross_cr

    @property
    def provision_share(self) -> float | None:
        """Write-down as a share of gross inventory. 0.0 is a real reading, not an absence."""
        if not self.located or not self.gross_cr:
            return None
        return (self.provision_cr or 0.0) / self.gross_cr


def inventory_summary(pages: tuple[str, ...]) -> InventorySummary:
    """Parse the inventories note into its components and its write-down.

    Anchored on the note TITLED exactly "Inventories": a filing also carries "Changes in Inventories of
    Finished Goods and Work-in-Progress", which is a P&L movement and not a balance. Matching loosely
    reads the movement as the stock.
    """
    found = find_note_bodies(pages, r"^\s*inventor(?:y|ies)\s*$")
    if not found:
        return InventorySummary(located=False, reason="no note titled 'Inventories' was found in the filing")
    note = found[0]
    lines = note_lines(note, pages)
    if not lines:
        return InventorySummary(
            located=True, note_label=note.label, page=note.page,
            reason="the inventories note was located but no figure rows could be read from it "
                   "(its page declares no unit this pipeline can resolve)",
        )

    provision = next((ln.current for ln in lines if _INVENTORY_PROVISION.search(ln.label)), None)
    total = _printed_total(lines)
    sub_total = next((ln.current for ln in lines if _SUB_TOTAL_ROW.match(ln.label)), None)
    # Gross is the sub-total where one is printed (components before the write-down), otherwise the total
    # plus the write-down back. A share struck on the NET book flatters itself as the provision grows.
    gross = sub_total if sub_total is not None else (
        (total + provision) if total is not None and provision is not None else total)
    components = _bucket(lines, _INVENTORY_BUCKETS)
    prior = _bucket(
        tuple(NoteLine(ln.label, ln.prior) for ln in lines if ln.prior is not None), _INVENTORY_BUCKETS)
    prior_sub = next((ln.prior for ln in lines if _SUB_TOTAL_ROW.match(ln.label)), None)
    prior_total = next((ln.prior for ln in lines if _TOTAL_ROW.match(ln.label)), None)
    prior_prov = next((ln.prior for ln in lines if _INVENTORY_PROVISION.search(ln.label)), None)
    prior_gross = prior_sub if prior_sub is not None else (
        (prior_total + prior_prov) if prior_total is not None and prior_prov is not None else prior_total)
    reconciled = _reconciles(components, gross, 0.02)
    return InventorySummary(
        located=True, note_label=note.label, page=note.page, total_cr=total, gross_cr=gross,
        prior_gross_cr=prior_gross,
        provision_cr=provision, components=components, prior_components=prior, reconciled=reconciled,
        reason="" if reconciled else (
            "the component rows do not add up to the note's own total, so the composition split is "
            "withheld and only the totals are reported"),
    )


#: What a company is being asked to pay but has not provided for. Ordered so the specific tax heads win
#: over the generic "claims against the company".
#:
#: The tax heads come BEFORE guarantees deliberately. Balaji Amines prints one row reading "GST on
#: technical know-how paid to foreign entity and corporate guarantee extended on behalf of the subsidiary
#: company" — a single ₹14.05cr claim whose primary head is GST. With guarantees first, that entire tax
#: demand is reported as an off-balance-sheet guarantee and sized against net worth as one.
_CONTINGENT_BUCKETS: dict[str, re.Pattern[str]] = {
    "income_tax": re.compile(r"income[\s-]*tax", re.I),
    "indirect_tax": re.compile(r"excise|custom|\bgst\b|service\s+tax|\bvat\b|sales\s+tax|entry\s+tax", re.I),
    "guarantees": re.compile(
        r"(?:corporate|bank|performance)\s+guarantee|guarantee[s]?\s+(?:given|issued|provided)", re.I),
    "labour": re.compile(r"labour|employee|workmen|provident|esic|gratuity", re.I),
    "legal": re.compile(r"legal|litigation|arbitration|court|suit\b|penalt", re.I),
    "other": re.compile(r"claim|dispute|demand|other", re.I),
}

#: A guarantee GIVEN, as opposed to the word appearing in an accounting-policy sentence. Requires the
#: giving verb, because "the Company recognises financial guarantee contracts at fair value" is policy
#: boilerplate present in every filing and is not evidence that any guarantee exists.
#: "financial guarantee" is deliberately absent: EVERY Ind AS filing carries the policy sentence "the
#: Company recognises financial guarantee contracts initially at fair value", and matching it reports an
#: off-balance-sheet exposure against every company ever read. A guarantee must be named as a KIND
#: (corporate, bank, performance) or be GIVEN by a verb — and "contract" right after it is the policy
#: wording, never a disclosure that one exists.
_GUARANTEE_GIVEN = re.compile(
    r"(?:corporate|bank|performance)\s+guarantee[s]?(?!\s+contract)|"
    r"guarantee[s]?\s+(?:given|issued|provided|furnished|extended)|"
    r"(?:given|issued|provided|extended)\s+(?:corporate|bank)?\s*guarantee",
    re.I,
)
#: A guarantee given for someone else's borrowing — the off-balance-sheet channel that matters most.
_GUARANTEE_FOR_RELATED = re.compile(
    r"guarantee[^.\n]{0,80}(?:subsidiar|associate|joint\s+ventur|related\s+part|promoter|director)|"
    r"(?:on\s+behalf\s+of|in\s+favour\s+of)[^.\n]{0,60}(?:subsidiar|associate|related\s+part|promoter)",
    re.I,
)
#: Capital commitments: contracted capex not yet executed. Not a liability, but it is money already
#: promised, and it belongs beside the feasibility gate rather than in a footnote nobody reads.
_CAPITAL_COMMITMENT = re.compile(
    r"estimated\s+amount\s+of\s+contracts|capital\s+commitment|commitments?\s+(?:remaining|not\s+provided)",
    re.I,
)
#: A note that is ONLY about commitments, matched on the whole title rather than as a substring.
_COMMITMENTS_ONLY_TITLE = re.compile(r"^\s*(?:capital\s+)?commitments?\s*$", re.I)


@dataclass(frozen=True)
class ContingentLiabilitySummary:
    """What the company might owe but has not provided for, and what it has guaranteed for others.

    `guarantees_heavy` (ADR-0020) has existed in the check library with no data behind it since it was
    written. This is that data. The tri-state matters as much as the number: `guarantees_given=False` on a
    located note is a real governance finding — the company has put nothing off its balance sheet.
    """

    located: bool
    note_label: str = ""
    page: int = 0
    total_cr: float | None = None
    buckets: Mapping[str, float] = field(default_factory=dict)
    guarantees_cr: float | None = None
    guarantees_given: bool | None = None
    guarantees_for_related_party: bool | None = None
    capital_commitments_cr: float | None = None
    reconciled: bool = False
    reason: str = ""

    @property
    def locator(self) -> str:
        return (f"note {self.note_label} p.{self.page}" if self.located
                else "contingent-liabilities note not found")


def contingent_liabilities_summary(pages: tuple[str, ...]) -> ContingentLiabilitySummary:
    """Parse the contingent-liabilities and commitments note(s).

    Filings split this two ways — one note with lettered sections, or two separately numbered sub-notes
    ("36a Contingent Liabilities and Commitments", "36b Commitments") — so every matching note is read and
    their tables are merged. Guarantees are found by scanning the note TEXT rather than only its table,
    because a guarantee is as often disclosed in a sentence as in a row.
    """
    found = find_note_bodies(pages, r"contingent\s+liabilit|^\s*commitments\s*$")
    if not found:
        return ContingentLiabilitySummary(
            located=False,
            reason="no contingent-liabilities or commitments note was found in the filing — for a listed "
                   "company this is itself a disclosure question, since Ind AS 37 requires the note",
        )

    buckets: dict[str, float] = {}
    total: float | None = None
    commitments: float | None = None
    # The note that actually CARRIED the figures, which is not always the first one matched: a filing may
    # print a heading-only cross-reference ("29 Contingent Liabilities and Commitments") pages before the
    # table itself ("36a"). Law 2 wants the locator to point at the page a reader can check the number on.
    source = found[0]
    text = "\n".join(b.text for b in found)
    for body in found:
        lines = note_lines(body, pages)
        if not lines:
            continue
        printed = _printed_total(lines)
        # A note titled ONLY "Commitments" is the capital-commitments table (Alkyl Amines splits it out as
        # 36b). A note titled "Contingent liabilities and commitments" is the contingent table with a
        # commitments section inside it, and treating it as commitments-only — which an unanchored
        # substring test does — discards the contingent liabilities entirely. Balaji Amines' ₹11.41cr of
        # tax and customs claims vanished exactly this way.
        if _COMMITMENTS_ONLY_TITLE.match(body.title):
            commitments = printed if printed is not None else commitments
            continue
        for name, amount in _bucket(lines, _CONTINGENT_BUCKETS).items():
            buckets[name] = buckets.get(name, 0.0) + amount
        if printed is not None:
            total = (total or 0.0) + printed
            source = body

    given = bool(_GUARANTEE_GIVEN.search(text))
    return ContingentLiabilitySummary(
        located=True, note_label=source.label, page=source.page, total_cr=total, buckets=buckets,
        guarantees_cr=buckets.get("guarantees"),
        guarantees_given=given,
        guarantees_for_related_party=bool(_GUARANTEE_FOR_RELATED.search(text)) if given else False,
        capital_commitments_cr=commitments,
        reconciled=_reconciles(buckets, total, 0.02),
        reason="" if _reconciles(buckets, total, 0.02) else (
            "the note's rows do not add up to its printed total, so the breakdown by claim type is "
            "withheld and only the total is reported"),
    )


#: The interest rate a borrowings note discloses per tranche: "ROI 7.97% p.a.", "@ 9.25% per annum".
#: This is the figure that makes a cost of debt a MEASUREMENT instead of Interest ÷ Borrowings, which
#: ADR-0025 showed becomes an artefact the moment borrowings are small (ALKYLAMINE's "100%").
_DISCLOSED_RATE = re.compile(
    r"(?:ROI|rate\s+of\s+interest|interest\s+rate|@)\D{0,20}?(\d{1,2}(?:\.\d{1,2})?)\s*%|"
    r"(\d{1,2}(?:\.\d{1,2})?)\s*%\s*(?:p\.?\s?a\.?|per\s+annum)",
    re.I,
)
_SECURED_ROW = re.compile(r"^\s*secured\b", re.I)
_UNSECURED_ROW = re.compile(r"^\s*unsecured\b", re.I)
#: What the lender has taken a charge over. A company that has hypothecated its receivables AND its
#: inventory AND mortgaged its plant has no unencumbered assets left to raise against.
_SECURITY_GIVEN = re.compile(
    r"secured\s+by|hypothecat|mortgage|charge\s+(?:on|over)|pledge[d]?\s+", re.I)
_REPAYABLE_ON_DEMAND = re.compile(r"repayable\s+on\s+demand|cash\s+credit|overdraft", re.I)


@dataclass(frozen=True)
class BorrowingsSummary:
    """What the company owes, on what terms, and against what security.

    Deliberately reports `located=False` rather than zero when no borrowings note exists. Those are
    different companies: one has no debt, the other has a note we failed to read — and only the first
    deserves the credit.
    """

    located: bool
    note_labels: tuple[str, ...] = ()
    page: int = 0
    total_cr: float | None = None
    secured_cr: float | None = None
    disclosed_rates: tuple[float, ...] = ()
    security_given: bool = False
    security_text: str = ""
    repayable_on_demand: bool = False
    reason: str = ""

    @property
    def locator(self) -> str:
        return (f"note(s) {', '.join(self.note_labels)} p.{self.page}" if self.located
                else "borrowings note not found")

    @property
    def highest_disclosed_rate(self) -> float | None:
        """The dearest rate the company discloses paying, as a fraction. The one that matters."""
        return max(self.disclosed_rates) / 100.0 if self.disclosed_rates else None


def borrowings_summary(pages: tuple[str, ...]) -> BorrowingsSummary:
    """Parse the borrowings note(s) — current and non-current are separately numbered notes."""
    found = find_note_bodies(pages, r"borrowing")
    if not found:
        return BorrowingsSummary(
            located=False,
            reason="no note titled 'Borrowings' was found in the filing; a debt-free company has none to "
                   "publish, so this is not by itself evidence either way",
        )
    total = 0.0
    secured = 0.0
    saw_total = False
    text = "\n".join(b.text for b in found)
    for body in found:
        lines = note_lines(body, pages)
        printed = _printed_total(lines)
        if printed is not None:
            total += printed
            saw_total = True
        in_secured = False
        for line in lines:
            if _SECURED_ROW.match(line.label):
                in_secured = True
            elif _UNSECURED_ROW.match(line.label) or _TOTAL_ROW.match(line.label):
                in_secured = False
            elif in_secured:
                secured += line.current

    rates = sorted({float(m.group(1) or m.group(2)) for m in _DISCLOSED_RATE.finditer(text)})
    security = _SECURITY_GIVEN.search(text)
    return BorrowingsSummary(
        located=True, note_labels=tuple(b.label for b in found), page=found[0].page,
        total_cr=total if saw_total else None,
        secured_cr=secured if saw_total else None,
        disclosed_rates=tuple(rates),
        security_given=bool(security),
        security_text=(text[security.start():security.start() + 220].replace("\n", " ")
                       if security else ""),
        repayable_on_demand=bool(_REPAYABLE_ON_DEMAND.search(text)),
        reason="" if saw_total else "the borrowings note was located but carries no readable total row",
    )
