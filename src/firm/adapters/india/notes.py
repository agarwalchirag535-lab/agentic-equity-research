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
_NOTE_HEADING = re.compile(
    r"^\s*(?:NOTE|Note)\s+(\d{1,3})\s*[:.\-–)]\s*(\S.{2,90})$|"
    r"^\s*(\d{1,3})\s*[.)]\s+([A-Z][A-Za-z &,/()'\-]{3,90})\s*$"
)

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
SCHEDULE_III_ROWS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("struck_off_companies", ("struck off", "struck-off")),
    ("benami_property", ("benami",)),
    ("wilful_defaulter", ("wilful defaulter", "willful defaulter")),
    ("undisclosed_income", ("undisclosed income",)),
    ("crypto_currency", ("crypto currency", "cryptocurrency", "virtual currency")),
    ("cwip_ageing", ("capital work-in-progress ageing", "cwip ageing", "ageing schedule of capital")),
    ("receivables_ageing", ("trade receivables ageing", "ageing schedule of trade receivable")),
    ("payables_ageing", ("trade payables ageing", "ageing schedule of trade payable")),
    ("loans_to_promoters", ("loans or advances to promoters", "loans and advances to promoters",
                            "advances to directors")),
    ("ratios_disclosure", ("current ratio", "debt-equity ratio", "debt equity ratio")),
    ("title_deeds", ("title deeds of immovable propert",)),
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


def enumerate_notes(pages: Sequence[str]) -> list[Note]:
    """Every numbered note heading across the pages, with (page, line) anchors.

    Duplicate note numbers keep the FIRST occurrence (continuation pages repeat headings).
    """
    seen: set[int] = set()
    notes: list[Note] = []
    for p_idx, page in enumerate(pages, start=1):
        for l_idx, line in enumerate(page.splitlines(), start=1):
            m = _NOTE_HEADING.match(line)
            if not m:
                continue
            number = int(m.group(1) or m.group(3))
            title = (m.group(2) or m.group(4) or "").strip(" .:-–")
            if number in seen:
                continue
            seen.add(number)
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


def schedule_iii_gaps(findings: Sequence[ScheduleIIIFinding]) -> tuple[list[str], bool]:
    """(missing mandatory rows, is_flagged) — feeds the `disclosure_gap` forensic signal."""
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
