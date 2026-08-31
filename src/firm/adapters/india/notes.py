"""Notes-walker: enumerate notes-to-accounts and force a disposition on every one (ADR-0017 §3).

"Line by line" (owner directive) made enforceable: keyword-spotting reads what it expects to find;
the walker instead ENUMERATES every numbered note in the statements and requires each to be
dispositioned `{clean | flag | unknown}` before a report can publish. Un-dispositioned notes are listed,
never skipped — the coverage number is the proof of reading.

Also parses CARO 2020 (the Companies (Auditor's Report) Order annexure): the auditor must answer ~21
specific clauses — fixed-asset records, inventory verification, loans to related parties, defaults,
fraud noticed/reported, ... Clause TEXT extraction is deterministic; the adversity heuristic below is a
TRIAGE aid (routes a clause to REVIEW with the clause quoted) — it is never an auto-veto, because
judging auditor language is narrative work that belongs to the forensic agent (Law 1 boundary).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Sequence

# "Note 29: Contingent Liabilities" / "NOTE 12 - Related Party" / "29. CONTINGENT LIABILITIES"
#: Three heading forms, because Indian filings use all three and the first two alone missed almost every
#: real note. "Note 9: Inventories" and "9. Inventories" were handled; the FY17-FY26 Alkyl Amines filings
#: write the audited notes as a BARE number then the title — "41 RELATED PARTY DISCLOSURES", "38 EMPLOYEE
#: BENEFITS", "39 Segment Reporting" — with no punctuation at all. Scoped enumeration found 3 notes where
#: there were ~49, so `substantive_share` sat at 0% and the verdict was INSUFFICIENT_DISCLOSURE for a
#: formatting reason rather than a disclosure one (ADR-0028).
#:
#: The bare form is the loosest, so it is anchored hard: the line must END after the title, which keeps it
#: off balance-sheet rows ("9 Inventories 12,213.07 16,478.08" carries figures and is rejected). Combined
#: with `notes_section_start` scoping, it does not reach the numbered paragraphs in the AGM notice or BRSR.
#: A note heading: a number, then a title, then — crucially — whatever else the typesetter put on that
#: line. The `$`-anchored version of this pattern found 11 of the 63 notes in the FY26 Alkyl Amines
#: filing, because a real heading is followed by the table's unit declaration:
#:
#:     3. Property, Plant and Equipment  ` In Lakhs
#:     4.  RIGHT OF USE ASSETS  ` In Lakhs
#:
#: and the anchor rejected every one of them. Coverage read 100% with `substantive_share` at 9%: the
#: pipeline was dispositioning the handful of notes whose headings happened to end cleanly and calling
#: that a full reading of the accounts. A trailing column gap (two or more spaces) now ends the title.
#:
#: Sub-numbered continuations ("3.3a. Ageing of Capital Work in progress", "4.1 -Lease period of land")
#: are excluded by requiring whitespace after the number's terminator, which a sub-number does not have.
#: A note number may carry a SINGLE-LETTER SUFFIX — "36a", "45b". Indian filings use it for the
#: sub-notes of a disclosure, and the most important note in the whole document is one of them: Alkyl
#: Amines prints contingent liabilities as "36a  CONTINGENT LIABILITIES AND COMMITMENTS". A pattern
#: demanding digits-then-whitespace matched none of them, so the filing's hidden-liability disclosure was
#: never enumerated — while `coverage` still reported 100%, because it measures the notes we FOUND.
#:
#: Titles also carry dots ("44  VALUE OF IMPORTS CALCULATED ON C.I.F. BASIS"), which the character class
#: excluded, and a trailing unit annotation ("` in Lakhs") already handled by the `\s{2,}` tail.
_NOTE_HEADING = re.compile(
    r"^\s*(?:NOTE|Note)\s+(\d{1,3}[a-zA-Z]?)\s*[:.\-–)]\s*(\S.{2,90}?)(?:\s{2,}.*)?$|"
    r"^\s*(\d{1,3}[a-zA-Z]?)\s*[.)]\s+([A-Za-z][A-Za-z .&,/()'\-]{3,70}?)(?:\s{2,}.*)?$|"
    r"^\s*(\d{1,3}[a-zA-Z]?)\s{1,}([A-Z][A-Za-z .&,/()'\-]{4,70}?)(?:\s{2,}.*)?$"
)
#: Splits "36a" into (36, "a"). The number orders the notes; the suffix distinguishes siblings.
_NOTE_NUMBER = re.compile(r"^(\d{1,3})([a-zA-Z]?)$")

# CARO clause markers: (i) ... (xxi), at line starts.
_CARO_CLAUSE = re.compile(r"^\s*\(\s*([ivxl]{1,5})\s*\)", re.IGNORECASE | re.MULTILINE)
_CARO_SECTION_HINTS = ["Companies (Auditor's Report) Order", "CARO", "Annexure"]

# Triage markers for possibly-adverse CARO language, with clean-formulation exceptions.
# PROVISIONAL until golden-set calibration; a hit routes to REVIEW, never to a veto.
ADVERSE_MARKERS: tuple[str, ...] = (
    "material discrepanc", "not been maintained", "unable to comment", "unable to determine",
    "default in repayment", "delays in depositing", "has been noticed", "irregular",
    "not commensurate", "adverse",
)
CLEAN_PHRASES: tuple[str, ...] = (
    "no fraud", "no material discrepanc", "not been noticed", "has not been noticed",
    "no such", "does not have any",
)


# Fixed note taxonomy (ADR-0017 §3). Order matters: the FIRST matching category wins, so more specific
# categories are listed before generic ones ("related_party" before "loans_advances", etc.).
NOTE_TAXONOMY: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("accounting_policies", ("accounting polic", "basis of preparation", "material accounting")),
    ("related_party", ("related party",)),
    ("contingent_liabilities", ("contingent liabilit", "commitments", "contingencies")),
    ("receivables", ("trade receivable", "sundry debtor", "debtors")),
    ("payables", ("trade payable", "sundry creditor", "creditors")),
    # Depreciation is the P&L side of the same asset base, and a note titled only "DEPRECIATION &
    # AMORTIZATION EXPENSES" was landing in `uncategorised` — so the CWIP-ageing check that reads the
    # asset base could not disposition it.
    ("ppe_cwip", ("property, plant", "capital work", "fixed asset", "tangible asset",
                  "depreciation", "amortization", "amortisation")),
    ("intangibles", ("intangible asset", "goodwill")),
    ("inventory", ("inventor", "stock-in-trade")),
    ("cash", ("cash and cash equivalent", "bank balance")),
    # Finance costs are what the borrowings cost, so the same cash-vs-debt checks read both.
    ("borrowings", ("borrowing", "long-term debt", "short-term debt", "finance cost")),
    ("provisions", ("provision",)),
    ("revenue", ("revenue from operation", "revenue recognition")),
    ("other_income", ("other income",)),
    ("employee_benefits", ("employee benefit", "gratuity", "esop", "share-based")),
    ("tax", ("income tax", "deferred tax", "current tax", "taxation")),
    ("segment", ("segment",)),
    ("ecl_impairment", ("expected credit loss", "impairment of financial")),
    ("fair_value", ("fair value", "financial instrument", "risk management")),
    ("investments", ("investment",)),
    # An Ind AS balance sheet titles these "Non Current Financial Assets - Loans" / "CURRENT FINANCIAL
    # ASSETS - LOANS", which the old "loans and advance" spelling never matched — so the notes carrying
    # money lent out, the single most important governance line after related-party, were uncategorised
    # and could not reach `promoter_lending`.
    ("loans_advances", ("loans and advance", "loans given", "financial assets - loan",
                        "financial assets- loan", "advances")),
    ("equity", ("equity share capital", "other equity", "reserves and surplus")),
    ("leases", ("lease",)),
    ("going_concern", ("going concern",)),
    ("subsequent_events", ("subsequent event", "events after the reporting")),
    ("schedule_iii_disclosures", ("struck off", "benami", "wilful defaulter", "crypto",
                                  "undisclosed income", "ratio", "ageing")),
)

# Schedule III (Companies Act, 2021 amendments) mandatory disclosures — a forensic gift because the law
# forces the company to answer each one. Absence in a filing that must contain them = `disclosure_gap`
# (ADR-0014), never a silent skip.
#: MATCH WHAT THE COMPANY WRITES, NOT WHAT THE RULE IS CALLED. Schedule III names each disclosure in its
#: own heading, and companies caption them in their own words: Alkyl Amines heads its receivables and
#: payables ageing tables "Outstanding for following periods from due date of payment", its CWIP table
#: "Ageing of Capital Work in progress", and answers the promoter-lending row as "advances in the nature
#: of loans". On the FY26 filing the narrower list below missed six disclosures that are all present, and
#: the pipeline fired a MEDIUM `disclosure_gap` — "unexplained opacity" — at a company that had disclosed
#: every one of them. That is the firm's extraction charged to the company, which ADR-0022 rules out
#: explicitly, and it is worse than a miss because it reads as a finding.
#: The Schedule III rows scanned below are the MCA amendment of 24 March 2021, effective for financial
#: years beginning 1 April 2021 — i.e. the FY22 annual report is the first that can lawfully carry them.
#: Charging an earlier filing with their absence is a false disclosure gap (found live on PC Jeweller
#: FY17, which was about to be cited for missing benami/crypto/ageing rows four years before they
#: existed). `schedule_iii_gaps` takes the filing's fiscal year for exactly this reason.
SCHEDULE_III_EFFECTIVE_FY = 2022

SCHEDULE_III_ROWS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("struck_off_companies", ("struck off", "struck-off")),
    ("benami_property", ("benami",)),
    ("wilful_defaulter", ("wilful defaulter", "willful defaulter")),
    ("undisclosed_income", ("undisclosed income", "surrendered or disclosed as income")),
    ("crypto_currency", ("crypto currency", "cryptocurrency", "virtual currency")),
    ("cwip_ageing", ("capital work-in-progress ageing", "cwip ageing", "ageing schedule of capital",
                     "ageing of capital work")),
    ("receivables_ageing", ("trade receivables ageing", "ageing schedule of trade receivable",
                            "trade receivable ageing", "undisputed trade receivable")),
    ("payables_ageing", ("trade payables ageing", "ageing schedule of trade payable",
                         "trade payable ageing", "micro enterprises and small\nenterprises- undisputed",
                         "enterprises- undisputed", "others-undisputed")),
    ("loans_to_promoters", ("loans or advances to promoters", "loans and advances to promoters",
                            "advances to directors", "advances in the nature of loans")),
    ("ratios_disclosure", ("current ratio", "debt-equity ratio", "debt equity ratio")),
    ("title_deeds", ("title deeds of immovable propert", "title deeds")),
)


@dataclass(frozen=True)
class Note:
    number: int
    title: str
    page: int    # 1-based
    line: int    # 1-based
    #: "a" in "36a". Sibling sub-notes share a number and differ only here, so `label` — never `number`
    #: — is what identifies a note. Keying on the number alone silently merged 45a and 45b into one.
    suffix: str = ""

    @property
    def label(self) -> str:
        """How the filing itself names this note: '36', '36a'. The identity used everywhere."""
        return f"{self.number}{self.suffix}"

    @property
    def category(self) -> str:
        """Taxonomy category from the note title; 'uncategorised' when nothing matches (visible, not
        silently dropped — an uncategorised note still requires a disposition)."""
        low = self.title.lower()
        for name, keywords in NOTE_TAXONOMY:
            if any(k in low for k in keywords):
                return name
        return "uncategorised"


@dataclass(frozen=True)
class NoteDisposition:
    """Exactly one per enumerated note. `figure_locators` bind extracted numbers to (page,line)."""

    #: The note's own label ("36", "36a"), not its number — sub-notes share a number (ADR-0045).
    note_label: str
    status: str                      # 'clean' | 'flag' | 'unknown'
    rationale: str
    figure_locators: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.status not in {"clean", "flag", "unknown"}:
            raise ValueError(f"invalid disposition status {self.status!r}")


def notes_section_start(pages: Sequence[str]) -> int:
    """1-based page where the NOTES TO THE FINANCIAL STATEMENTS begin, or 1 if it cannot be located.

    Scoping matters as much here as it did for the statement rows (ADR-0024), and for the same reason. An
    annual report numbers paragraphs everywhere: the AGM notice, the directors' report, the
    corporate-governance report and the BRSR all have numbered items that match a note heading exactly. On
    the FY26 Alkyl Amines filing an unscoped pass enumerated 17 "notes" from pages 5-44 — e-voting
    instructions, ACKNOWLEDGEMENTS, a list of the chairman's other directorships — and not one of the 49
    real notes on pages 87-133. Coverage read 100% and every disposition was `unknown`, which is exactly the
    "coverage without reading" that `substantive_share` exists to catch.

    The audited notes always follow the audited statements, so the balance sheet anchors the section.
    """
    from firm.adapters.base.tables import audited_statement_pages

    anchor = audited_statement_pages(pages).get("balance_sheet", ())
    return (anchor[0] + 1) if anchor else 1


def enumerate_notes(pages: Sequence[str], *, first_page: int | None = None) -> list[Note]:
    """Every numbered note heading across the pages, with (page, line) anchors.

    Duplicate note numbers keep the FIRST occurrence (continuation pages repeat headings). ``first_page``
    (1-based) restricts the scan to the notes-to-accounts section; pass `notes_section_start(pages)` for it.
    Page numbers stay absolute so provenance still points at the real page.
    """
    seen: set[str] = set()
    candidates: list[Note] = []
    floor = first_page or 1
    for p_idx, page in enumerate(pages, start=1):
        if p_idx < floor:
            continue
        for l_idx, line in enumerate(page.splitlines(), start=1):
            m = _NOTE_HEADING.match(line)
            if not m:
                continue
            token = m.group(1) or m.group(3) or m.group(5)
            parsed = _NOTE_NUMBER.match(token)
            if parsed is None:  # pragma: no cover - the heading pattern cannot produce another shape
                continue
            number, suffix = int(parsed.group(1)), parsed.group(2).lower()
            title = (m.group(2) or m.group(4) or m.group(6) or "").strip(" .:-–")
            label = f"{number}{suffix}"
            # De-duplicate on the LABEL: continuation pages repeat a heading, but 45a and 45b are two
            # different notes and de-duplicating on the number would have discarded the second.
            if label in seen:
                continue
            seen.add(label)
            candidates.append(Note(number, title, p_idx, l_idx, suffix))
    return _in_filed_order(candidates)


def _in_filed_order(candidates: Sequence[Note]) -> list[Note]:
    """Keep the longest run of candidates whose numbers ASCEND in document order.

    Notes to the accounts are numbered in sequence and printed in that sequence, so a "note 5" appearing
    between note 39 and note 40 is not a note. On the FY26 Alkyl Amines filing that exact case occurs: an
    actuarial-assumptions table inside the employee-benefits note opens with

        5  Withdrawal Rate  Indian Assured  Indian Assured

    which is indistinguishable from a heading by shape alone and only distinguishable by position. Any
    text-shape rule loose enough to catch the real headings will catch some of these; the filing's own
    ordering is the check that costs nothing and cannot be fooled by typography.

    The longest increasing subsequence rather than a greedy scan, so one spurious high number early in
    the section cannot suppress every real note after it.
    """
    if not candidates:
        return []
    best = [1] * len(candidates)
    previous = [-1] * len(candidates)
    for i in range(len(candidates)):
        for j in range(i):
            # Ordered on (number, suffix): sibling sub-notes share a number, so a strict `<` on the
            # number alone treats 45a and 45b as non-ascending and discards the second.
            if ((candidates[j].number, candidates[j].suffix)
                    < (candidates[i].number, candidates[i].suffix)) and best[j] + 1 > best[i]:
                best[i], previous[i] = best[j] + 1, j
    index = max(range(len(candidates)), key=lambda i: best[i])
    chain: list[Note] = []
    while index >= 0:
        chain.append(candidates[index])
        index = previous[index]
    return list(reversed(chain))


def note_body(pages: Sequence[str], notes: Sequence[Note], note: Note) -> list[str]:
    """The lines belonging to ``note``: from its heading to the next note's heading.

    The body may end on the SAME page it started (several of these notes share a page), so the boundary
    is the next enumerated heading rather than the page break. Getting that wrong sweeps the neighbouring
    note's figures in — and the neighbour of the related-party note is Earnings Per Share, whose first
    row is net profit (`notes_content.related_party_summary` learned this the hard way).
    """
    later = [n for n in notes if (n.page, n.line) > (note.page, note.line)]
    end = min(later, key=lambda n: (n.page, n.line)) if later else None
    out: list[str] = []
    for page_number in range(note.page, (end.page if end else len(pages)) + 1):
        if page_number > len(pages):
            break
        for line_number, line in enumerate(pages[page_number - 1].splitlines(), start=1):
            if page_number == note.page and line_number <= note.line:
                continue
            if end is not None and page_number == end.page and line_number >= end.line:
                break
            out.append(line)
    return out


def coverage(notes: Sequence[Note], dispositions: Sequence[NoteDisposition]) -> tuple[float, list[str]]:
    """(fraction of notes dispositioned, note labels still missing). Publish gate requires (1.0, []).

    A disposition for a note that was never enumerated raises — you cannot claim to have read a note
    that does not exist (that is how fake coverage would sneak in).

    Keyed on `label`, not `number`: sibling sub-notes (45a, 45b) share a number, and a number-keyed set
    silently merged them into one — inflating the denominator's honesty and the numerator's alike.
    """
    have = {n.label for n in notes}
    got = {d.note_label for d in dispositions}
    phantom = sorted(got - have)
    if phantom:
        raise ValueError(f"dispositions reference non-existent notes: {phantom}")
    if not have:
        return 0.0, []
    missing = sorted(have - got)
    return (len(have) - len(missing)) / len(have), missing


def sequence_gaps(notes: Sequence[Note]) -> list[int]:
    """Note numbers missing from the filed sequence — notes that exist and were NOT enumerated.

    `coverage` measures dispositions against the notes we FOUND, so it reports 100% while the enumerator
    is blind to a whole note. That is exactly how Alkyl Amines' contingent-liabilities note ("36a") went
    unread behind a 100% coverage figure. Notes to the accounts are numbered consecutively, so a hole in
    the run is direct evidence of a note the parser could not see.

    This is a CAPABILITY gap, never a disclosure gap: the company numbered its notes correctly and we
    failed to read one. It must lower our confidence, never the company's verdict (ADR-0022).
    """
    if not notes:
        return []
    numbers = {n.number for n in notes}
    return [n for n in range(min(numbers), max(numbers) + 1) if n not in numbers]


def categorise_notes(notes: Sequence[Note]) -> dict[str, list[int]]:
    """{taxonomy category → note numbers}. Lets the caller see which categories the filing covers and,
    by difference, which expected categories are absent."""
    out: dict[str, list[int]] = {}
    for note in notes:
        out.setdefault(note.category, []).append(note.number)
    return out


@dataclass(frozen=True)
class ScheduleIIIFinding:
    """One mandatory Schedule III row: whether it was found, and where."""

    row: str
    found: bool
    page: int | None = None
    line: int | None = None
    excerpt: str = ""

    @property
    def locator(self) -> str:
        return f"p.{self.page} l.{self.line}" if self.found else ""


def scan_schedule_iii(pages: Sequence[str]) -> list[ScheduleIIIFinding]:
    """Locate every Schedule III mandatory disclosure row, with a (page, line) anchor when present.

    A `found=False` row is the signal: the law requires the company to address it, so its absence is
    either non-disclosure or an unreadable filing — both feed `disclosure_gap` (ADR-0014).
    """
    findings: list[ScheduleIIIFinding] = []
    for row, keywords in SCHEDULE_III_ROWS:
        hit: ScheduleIIIFinding | None = None
        for p_idx, page in enumerate(pages, start=1):
            for l_idx, line in enumerate(page.splitlines(), start=1):
                low = line.lower()
                if any(k in low for k in keywords):
                    hit = ScheduleIIIFinding(row, True, p_idx, l_idx, line.strip()[:200])
                    break
            if hit is not None:
                break
        findings.append(hit or ScheduleIIIFinding(row, False))
    return findings


def schedule_iii_gaps(
    findings: Sequence[ScheduleIIIFinding], fiscal_year: int | None = None
) -> tuple[list[str], bool]:
    """(missing mandatory rows, is_flagged) — feeds the `disclosure_gap` forensic signal.

    `fiscal_year` is the year the filing reports (2017 for FY17). Rows the law did not yet require are
    NOT gaps: a missing-capability-or-era claim must never become a company non-disclosure. None means
    era-unknown and keeps the strict behaviour (every row required), which is only correct for current
    filings."""
    if fiscal_year is not None and fiscal_year < SCHEDULE_III_EFFECTIVE_FY:
        return [], False
    missing = sorted(f.row for f in findings if not f.found)
    return missing, bool(missing)


def parse_caro_clauses(text: str) -> dict[str, str]:
    """Split the CARO annexure into clauses keyed by roman numeral ('i'..'xxi').

    Returns {} when no CARO section is present — which, for a company required to have one, is itself
    a `disclosure_gap` for the caller to raise (never a silent skip).
    """
    if not any(hint.lower() in text.lower() for hint in _CARO_SECTION_HINTS):
        return {}
    matches = list(_CARO_CLAUSE.finditer(text))
    clauses: dict[str, str] = {}
    for i, m in enumerate(matches):
        key = m.group(1).lower()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[m.end():end].strip()
        if key not in clauses and body:   # first occurrence wins; empty bodies dropped
            clauses[key] = body
    return clauses


def caro_candidate_flags(clauses: dict[str, str]) -> list[tuple[str, str]]:
    """Clauses whose language matches an adverse marker and no clean-formulation phrase.

    Triage only: each hit is (clause_key, matched_marker) for the forensic agent to read with the
    clause text. The standard clean answer to clause (xi) — "no fraud ... has been noticed" — must NOT
    fire, which is what the CLEAN_PHRASES guard is for.
    """
    hits: list[tuple[str, str]] = []
    for key, body in clauses.items():
        low = body.lower()
        if any(phrase in low for phrase in CLEAN_PHRASES):
            continue
        for marker in ADVERSE_MARKERS:
            if marker in low:
                hits.append((key, marker))
                break
    return hits
