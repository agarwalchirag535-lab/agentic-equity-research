"""Tests for the notes-walker + CARO parser (line-by-line engine, ADR-0017 §3)."""

import pytest

from firm.adapters.india.notes import (
    SCHEDULE_III_ROWS,
    Note,
    NoteDisposition,
    ScheduleIIIFinding,
    caro_candidate_flags,
    categorise_notes,
    coverage,
    enumerate_notes,
    parse_caro_clauses,
    scan_schedule_iii,
    schedule_iii_gaps,
    sequence_gaps,
)

PAGE_1 = (
    "Notes to the Financial Statements\n"
    "Note 1: Corporate Information\n"
    "The Company is engaged in specialty chemicals.\n"
    "Note 2 - Significant Accounting Policies\n"
    "Revenue is recognised when control transfers.\n"
)
PAGE_2 = (
    "29. CONTINGENT LIABILITIES AND COMMITMENTS\n"
    "Claims not acknowledged as debt Rs 12 cr.\n"
    "Note 2 - Significant Accounting Policies\n"   # continuation-page repeat -> must dedupe
    "30. RELATED PARTY DISCLOSURES\n"
)

CARO_CLEAN = (
    "Annexure B to the Independent Auditor's Report — Companies (Auditor's Report) Order, 2020\n"
    "(i) The Company has maintained proper records of Property, Plant and Equipment.\n"
    "(ii) Physical verification of inventory was conducted; no material discrepancies were noticed.\n"
    "(xi) No fraud by the Company or on the Company has been noticed or reported during the year.\n"
)
CARO_ADVERSE = (
    "Annexure A — CARO 2020\n"
    "(vii) There have been delays in depositing undisputed statutory dues, including GST.\n"
    "(ix) The Company has made default in repayment of loans from banks during the year.\n"
    "(xi) No fraud has been noticed or reported.\n"
)


# ---- note enumeration ---------------------------------------------------------------------------
def test_enumerate_notes_both_heading_styles_with_anchors():
    notes = enumerate_notes([PAGE_1, PAGE_2])
    by_no = {n.number: n for n in notes}
    assert by_no[1].title == "Corporate Information" and by_no[1].page == 1 and by_no[1].line == 2
    assert by_no[2].title == "Significant Accounting Policies"
    assert by_no[29].title == "CONTINGENT LIABILITIES AND COMMITMENTS" and by_no[29].page == 2
    assert by_no[30].title == "RELATED PARTY DISCLOSURES"
    assert len(notes) == 4                                    # continuation repeat of Note 2 deduped


def test_enumerate_notes_ignores_prose_lines():
    notes = enumerate_notes(["Just prose.\nRevenue grew nicely.\n"])
    assert notes == []


#: The three heading shapes the Alkyl Amines FY26 filing actually uses that a digits-then-space pattern
#: could not see. The first is the one that matters most: the contingent-liabilities note — the whole
#: hidden-liability disclosure — is filed as a lettered sub-note and was silently never enumerated.
SUFFIXED_PAGE = (
    "36a  CONTINGENT LIABILITIES AND COMMITMENTS  ` in Lakhs\n"
    "Claims against the company not acknowledged as debt  1234.56\n"
    "44  VALUE OF IMPORTS CALCULATED ON C.I.F. BASIS  ` in Lakhs\n"
    "45a  EXPENDITURE IN FOREIGN CURRENCY  ` in Lakhs\n"
    "45b  EARNINGS IN FOREIGN CURRENCY  ` in Lakhs\n"
)


def test_a_lettered_sub_note_is_enumerated_and_keeps_its_label():
    notes = enumerate_notes([SUFFIXED_PAGE])
    labels = [n.label for n in notes]
    assert labels == ["36a", "44", "45a", "45b"]

    contingent = next(n for n in notes if n.label == "36a")
    assert contingent.title == "CONTINGENT LIABILITIES AND COMMITMENTS"
    assert contingent.category == "contingent_liabilities"
    # The number still orders it; the suffix is what distinguishes it from a sibling.
    assert (contingent.number, contingent.suffix) == (36, "a")


def test_sibling_sub_notes_are_two_notes_not_one():
    """45a and 45b share a number. Keying on the number silently discarded the second."""
    notes = enumerate_notes([SUFFIXED_PAGE])
    assert [n.label for n in notes if n.number == 45] == ["45a", "45b"]


def test_a_dotted_title_is_still_a_heading():
    """"C.I.F." — the character class excluded the period, so the whole note vanished."""
    notes = enumerate_notes([SUFFIXED_PAGE])
    assert next(n for n in notes if n.label == "44").title == (
        "VALUE OF IMPORTS CALCULATED ON C.I.F. BASIS")


def test_a_hole_in_the_filed_numbering_is_reported():
    """Coverage measures the notes we FOUND. A gap in the sequence is a note we could not see, and
    saying 100% without saying that overstates the reading."""
    notes = enumerate_notes(["1  Corporate Information\n2  Accounting Policies\n5  Inventories\n"])
    assert sequence_gaps(notes) == [3, 4]
    assert sequence_gaps([]) == []


# ---- disposition + coverage (the publish gate) --------------------------------------------------
def test_coverage_full_and_partial():
    notes = enumerate_notes([PAGE_1, PAGE_2])
    disp = [
        NoteDisposition("1", "clean", "boilerplate"),
        NoteDisposition("2", "clean", "policies unchanged YoY"),
        NoteDisposition("29", "flag", "contingents rose vs net worth", ["p.2 l.2"]),
    ]
    pct, missing = coverage(notes, disp)
    assert pct == pytest.approx(3 / 4) and missing == ["30"]   # note 30 unread -> cannot publish
    pct, missing = coverage(notes, disp + [NoteDisposition("30", "unknown", "RPT schedule unreadable")])
    assert pct == 1.0 and missing == []


def test_coverage_phantom_disposition_raises():
    notes = enumerate_notes([PAGE_1])
    with pytest.raises(ValueError):                           # claiming to have read a non-existent note
        coverage(notes, [NoteDisposition("99", "clean", "??")])


def test_coverage_empty_notes():
    assert coverage([], []) == (0.0, [])


def test_disposition_status_validated():
    with pytest.raises(ValueError):
        NoteDisposition("1", "fine", "not a valid status")


def test_note_is_frozen_dataclass():
    n = Note(1, "x", 1, 1)
    with pytest.raises(AttributeError):
        n.title = "y"  # type: ignore[misc]


# ---- note taxonomy ------------------------------------------------------------------------------
def test_note_category_classification():
    assert Note(1, "Corporate Information", 1, 1).category == "uncategorised"
    assert Note(2, "Significant Accounting Policies", 1, 1).category == "accounting_policies"
    assert Note(29, "CONTINGENT LIABILITIES AND COMMITMENTS", 1, 1).category == "contingent_liabilities"
    assert Note(30, "RELATED PARTY DISCLOSURES", 1, 1).category == "related_party"
    assert Note(9, "Trade Receivables", 1, 1).category == "receivables"
    assert Note(7, "Property, Plant and Equipment", 1, 1).category == "ppe_cwip"
    # specificity: "related party" wins over the generic "loans and advances" keyword
    assert Note(11, "Loans and advances to related party", 1, 1).category == "related_party"


def test_categorise_notes_groups_numbers():
    notes = enumerate_notes([PAGE_1, PAGE_2])
    cats = categorise_notes(notes)
    assert cats["accounting_policies"] == [2]
    assert cats["contingent_liabilities"] == [29]
    assert cats["related_party"] == [30]
    assert cats["uncategorised"] == [1]     # visible, still requires a disposition


# ---- Schedule III mandatory rows (ADR-0017 §3) --------------------------------------------------
SCHED_III_PAGE = (
    "Additional Regulatory Information\n"
    "(i) Details of Benami property held: No proceedings have been initiated.\n"
    "(ii) Wilful defaulter: The Company is not declared a wilful defaulter.\n"
    "Trade Receivables ageing schedule as at 31 March 2026\n"
    "Relationship with struck off companies: NIL transactions during the year.\n"
    "Current Ratio 1.85 1.72\n"
)


def test_scan_schedule_iii_finds_present_rows_with_anchors():
    findings = {f.row: f for f in scan_schedule_iii([SCHED_III_PAGE])}
    assert len(findings) == len(SCHEDULE_III_ROWS)          # every mandatory row is reported either way
    assert findings["benami_property"].found and findings["benami_property"].line == 2
    assert findings["benami_property"].locator == "p.1 l.2"
    assert "Benami" in findings["benami_property"].excerpt
    assert findings["wilful_defaulter"].found
    assert findings["receivables_ageing"].found
    assert findings["struck_off_companies"].found
    assert findings["ratios_disclosure"].found


def test_scan_schedule_iii_absence_is_the_signal():
    findings = {f.row: f for f in scan_schedule_iii([SCHED_III_PAGE])}
    # not addressed anywhere in this filing -> found=False, no locator
    assert findings["title_deeds"].found is False and findings["title_deeds"].locator == ""
    missing, flag = schedule_iii_gaps(list(findings.values()))
    assert flag is True
    assert "title_deeds" in missing and "loans_to_promoters" in missing
    assert "benami_property" not in missing


def test_schedule_iii_gaps_clean_when_all_found():
    all_found = [ScheduleIIIFinding(row, True, 1, 1, "x") for row, _ in SCHEDULE_III_ROWS]
    assert schedule_iii_gaps(all_found) == ([], False)


# ---- CARO 2020 ----------------------------------------------------------------------------------
def test_parse_caro_clauses_and_clean_answers_do_not_flag():
    clauses = parse_caro_clauses(CARO_CLEAN)
    assert set(clauses) == {"i", "ii", "xi"}
    assert "proper records" in clauses["i"]
    # clause (ii) says "no material discrepancies" and (xi) "no fraud ... noticed" — both CLEAN
    assert caro_candidate_flags(clauses) == []


def test_caro_adverse_clauses_triage():
    clauses = parse_caro_clauses(CARO_ADVERSE)
    hits = dict(caro_candidate_flags(clauses))
    assert hits["vii"] == "delays in depositing"
    assert hits["ix"] == "default in repayment"
    assert "xi" not in hits                                   # clean fraud answer must not fire


def test_parse_caro_absent_section_returns_empty():
    # no CARO section at all -> {} -> caller raises disclosure_gap (never a silent skip)
    assert parse_caro_clauses("Independent Auditor's Report. Opinion: true and fair.") == {}
