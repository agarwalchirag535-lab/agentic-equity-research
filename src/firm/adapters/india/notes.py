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
_NOTE_HEADING = re.compile(
    r"^\s*(?:NOTE|Note)\s+(\d{1,3})\s*[:.\-–)]\s*(\S.{2,90})$|"
    r"^\s*(\d{1,3})\s*[.)]\s+([A-Z][A-Za-z &,/()'\-]{3,90})\s*$|"
    r"^\s*(\d{1,3})\s+([A-Z][A-Za-z &,/()'\-]{4,90})\s*$"
)

#: The currency-unit marker Indian filings print on the SAME line as the note heading:
#: "9 INVENTORIES ` In Lakhs", "3. Property, Plant and Equipment  ` In Lakhs", "... Rs. In Lakhs".
#: (The backtick is how the ₹ glyph survives text extraction.)
#:
#: This one suffix was the whole of ADR-0037. The end-of-line anchor above is deliberate and correct — it
#: is what keeps the bare form off balance-sheet rows carrying figures — but on these filings almost every
#: balance-sheet and P&L note heading ends in a unit marker rather than in its title, so the anchor
#: rejected them. Enumeration returned notes 1, 2 and 38-49 and NOTHING between 3 and 37: precisely the
#: inventory, receivables, borrowings, payables and CWIP notes, i.e. every note the mandated-disclosure
#: scan looks for. Strip the marker, then anchor.
_UNIT_TAIL = re.compile(
    r"[\s(\[]*(?:`|₹|Rs\.?|INR)?\s*(?:In|in|IN)\s+"
    r"(?:Lakhs?|Lacs?|Crores?|Cr\.?|Millions?|Mn\.?|Thousands?|'?000s?)\s*[)\]]*\s*$"
)


def _strip_unit_tail(line: str) -> str:
    """Drop a trailing currency-unit marker so the heading anchor sees the end of the TITLE."""
    return _UNIT_TAIL.sub("", line)

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
    ("ppe_cwip", ("property, plant", "capital work", "fixed asset", "tangible asset")),
    ("intangibles", ("intangible asset", "goodwill")),
    ("inventory", ("inventor", "stock-in-trade")),
    ("cash", ("cash and cash equivalent", "bank balance")),
    ("borrowings", ("borrowing", "long-term debt", "short-term debt")),
    ("provisions", ("provision",)),
    ("revenue", ("revenue from operation", "revenue recognition")),
    ("other_income", ("other income",)),
    ("employee_benefits", ("employee benefit", "gratuity", "esop", "share-based")),
    ("tax", ("income tax", "deferred tax", "current tax", "taxation")),
    ("segment", ("segment",)),
    ("ecl_impairment", ("expected credit loss", "impairment of financial")),
    ("fair_value", ("fair value", "financial instrument", "risk management")),
    ("investments", ("investment",)),
    ("loans_advances", ("loans and advance", "loans given")),
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
#
# THESE ARE PATTERNS, NOT HEADINGS (ADR-0037). The first version matched the wording of the *statute*
# ("ageing schedule of trade receivable") against filings that use the wording of the *accountant*. On the
# FY26 Alkyl Amines report that produced six false gaps out of eleven rows, and since `disclosure_gap` is
# the only MEDIUM-severity signal in the universal set, it alone drove a published `REVIEW` screen on a
# real listed company for disclosures that were on pages 103, 107, 112 and 133. Charging a company for our
# own phrase list is precisely the failure the DISCLOSURE-vs-CAPABILITY split exists to prevent.
#
# So each row now carries alternates drawn from how the disclosures are actually printed:
#   * word order is not fixed — "Ageing of Capital Work in progress", not "capital work-in-progress ageing";
#   * the ageing schedules are TABLES that may never use the word "ageing" — they are identified by their
#     Schedule III row labels ("Undisputed Trade Receivables - considered good") instead;
#   * the negative disclosures are answered in the negative — "The Company does not have any benami
#     property", "There is no income surrendered or disclosed as income" — so match the answer, not the
#     question.
SCHEDULE_III_ROWS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("struck_off_companies", (r"struck[\s-]*off",)),
    ("benami_property", (r"benami",)),
    ("wilful_defaulter", (r"wil{1,2}ful\s+defaulter",)),
    ("undisclosed_income", (r"undisclosed\s+income",
                            r"income\s+surrendered\s+or\s+disclosed\s+as\s+income",
                            r"not\s+recorded\s+in\s+the\s+books\s+of\s+account")),
    ("crypto_currency", (r"crypto\s*currency", r"cryptocurrency", r"virtual\s+currency")),
    ("cwip_ageing", (r"ageing.{0,60}capital\s+work", r"capital\s+work.{0,80}ageing",
                     r"cwip\s+ageing")),
    ("receivables_ageing", (r"ageing.{0,60}(?:trade\s+)?receivable",
                            r"(?:trade\s+)?receivables?.{0,80}ageing",
                            r"(?:un)?disputed\s+trade\s+receivable")),
    ("payables_ageing", (r"ageing.{0,60}(?:trade\s+)?payable",
                         r"(?:trade\s+)?payables?.{0,80}ageing",
                         r"(?:un)?disputed\s+trade\s+payable",
                         r"micro\s+enterprises\s+and\s+small\s+enterprises\s*-?\s*undisputed")),
    ("loans_to_promoters", (r"loans?\s+(?:or|and)\s+advances?.{0,60}promoter",
                            r"advances?\s+in\s+the\s+nature\s+of\s+loans?",
                            r"advances?\s+to\s+(?:promoters?|directors?|kmps?)")),
    ("ratios_disclosure", (r"current\s+ratio", r"debt[\s-]*equity\s+ratio")),
    ("title_deeds", (r"title\s+deeds?.{0,80}immovable", r"immovable\s+propert.{0,80}title\s+deeds?")),
)

#: The first fiscal year in which these rows are legally required. MCA notification G.S.R. 207(E) of
#: 24 March 2021 amended Schedule III with effect from 1 April 2021, so the earliest annual report that
#: must carry them is **FY22**.
#:
#: Without this, the scan is an anachronism: it charges a company for omitting a disclosure the law did not
#: yet require. The FY20 Alkyl Amines report is reported "missing" on nine of eleven rows, every one of them
#: correctly absent. That is not a curiosity — Phase 6's golden set is built from 2015-2021 filings, so
#: every company in it would carry a spurious `disclosure_gap` and the threshold calibrated against it
#: would be calibrated against our own bug (ADR-0037).
SCHEDULE_III_FIRST_FY = 22


def _fy_number(period: str | None) -> int | None:
    """'FY22' -> 22. None when the period is absent or not a fiscal-year label."""
    if not period:
        return None
    m = re.fullmatch(r"FY(\d{2})", period.strip(), re.IGNORECASE)
    return int(m.group(1)) if m else None


#: Compiled once. Matching is against the FLATTENED page (newlines collapsed to spaces) because these
#: filings wrap a heading mid-phrase constantly — "Micro Enterprises and Small\nEnterprises- Undisputed" is
#: one label printed as two lines, and a line-by-line scan can never see it.
_SCHEDULE_III_PATTERNS: tuple[tuple[str, tuple[re.Pattern[str], ...]], ...] = tuple(
    (row, tuple(re.compile(p, re.IGNORECASE) for p in patterns))
    for row, patterns in SCHEDULE_III_ROWS
)


@dataclass(frozen=True)
class Note:
    number: int
    title: str
    page: int    # 1-based
    line: int    # 1-based

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

    note_number: int
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

    Two rules beyond the regex, each closing a way the count went wrong (ADR-0037):

    * a trailing currency-unit marker is stripped before matching, because these filings print it on the
      heading line itself and the end-of-line anchor would otherwise reject the heading;
    * note numbers must ASCEND. Notes are numbered in document order, so a "5." appearing after note 38 is
      not note 5 — on the FY26 filing it was a row inside the employee-benefits actuarial table
      ("5. Withdrawal Rate Indian Assured"), enumerated as a note and dispositioned `unknown`. A phantom
      note inflates the denominator of `substantive_share`, which is the number the verdict reads.
    """
    seen: set[int] = set()
    notes: list[Note] = []
    highest = 0
    floor = first_page or 1
    for p_idx, page in enumerate(pages, start=1):
        if p_idx < floor:
            continue
        for l_idx, line in enumerate(page.splitlines(), start=1):
            m = _NOTE_HEADING.match(_strip_unit_tail(line))
            if not m:
                continue
            number = int(m.group(1) or m.group(3) or m.group(5))
            title = (m.group(2) or m.group(4) or m.group(6) or "").strip(" .:-–")
            if number in seen or number <= highest:
                continue
            seen.add(number)
            highest = number
            notes.append(Note(number, title, p_idx, l_idx))
    return notes


def coverage(notes: Sequence[Note], dispositions: Sequence[NoteDisposition]) -> tuple[float, list[int]]:
    """(fraction of notes dispositioned, note numbers still missing). Publish gate requires (1.0, []).

    A disposition for a note that was never enumerated raises — you cannot claim to have read a note
    that does not exist (that is how fake coverage would sneak in).
    """
    have = {n.number for n in notes}
    got = {d.note_number for d in dispositions}
    phantom = sorted(got - have)
    if phantom:
        raise ValueError(f"dispositions reference non-existent notes: {phantom}")
    if not have:
        return 0.0, []
    missing = sorted(have - got)
    return (len(have) - len(missing)) / len(have), missing


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
    #: False when the filing predates the row's statutory effective date. Kept as a THIRD state rather than
    #: silently dropping the row: "not required of this filing" and "required and absent" are opposite
    #: findings, and only the second is a disclosure gap (ADR-0027's tri-state, applied to the law).
    applicable: bool = True

    @property
    def locator(self) -> str:
        return f"p.{self.page} l.{self.line}" if self.found else ""


def scan_schedule_iii(
    pages: Sequence[str], *, period: str | None = None
) -> list[ScheduleIIIFinding]:
    """Locate every Schedule III mandatory disclosure row, with a (page, line) anchor when present.

    A `found=False, applicable=True` row is the signal: the law requires the company to address it, so its
    absence is either non-disclosure or an unreadable filing — both feed `disclosure_gap` (ADR-0014).

    ``period`` is the fiscal year the filing reports ('FY22'). Pass it and rows that were not yet law for
    that year come back `applicable=False`; omit it and every row is treated as in force, which is the old
    behaviour and wrong for any filing before FY22.
    """
    fy = _fy_number(period)
    in_force = fy is None or fy >= SCHEDULE_III_FIRST_FY
    if not in_force:
        return [ScheduleIIIFinding(row, False, applicable=False) for row, _ in SCHEDULE_III_ROWS]
    findings: list[ScheduleIIIFinding] = []
    for row, patterns in _SCHEDULE_III_PATTERNS:
        hit: ScheduleIIIFinding | None = None
        for p_idx, page in enumerate(pages, start=1):
            lines = page.splitlines()
            flat = " ".join(page.split())
            match = next((m for p in patterns if (m := p.search(flat))), None)
            if match is None:
                continue
            # Anchor the provenance to a real line: the flattened offset cannot be mapped back exactly
            # once whitespace is collapsed, so find the line carrying the match's first word.
            head = match.group(0).split()[0].lower()
            l_idx = next(
                (i for i, line in enumerate(lines, start=1) if head in line.lower()), 1
            )
            hit = ScheduleIIIFinding(row, True, p_idx, l_idx, lines[l_idx - 1].strip()[:200])
            break
        findings.append(hit or ScheduleIIIFinding(row, False))
    return findings


def schedule_iii_gaps(findings: Sequence[ScheduleIIIFinding]) -> tuple[list[str], bool]:
    """(missing mandatory rows, is_flagged) — feeds the `disclosure_gap` forensic signal.

    A row that was not yet law for this filing is NOT a gap: `applicable=False` rows are excluded, so a
    2015-2021 filing is never charged for the 2021 Schedule III amendment (ADR-0037).
    """
    missing = sorted(f.row for f in findings if f.applicable and not f.found)
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
