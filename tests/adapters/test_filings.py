"""Tests for the primary-document (annual report / concall) adapter — pure text logic, no network."""

from firm.adapters.india.filings import (
    REQUIRED_DISCLOSURES,
    SECTION_KEYWORDS,
    disclosure_gaps,
    find_section,
    forensic_sections,
)

SAMPLE = (
    "INDEPENDENT AUDITOR'S REPORT ... Opinion: true and fair ... "
    "Key Audit Matters: Litigation and contingencies were the matter of most significance. "
    "RELATED PARTY: all transactions at arm's length. "
    "Contingent Liabilities: claims not acknowledged as debt Rs 12 cr."
)


def test_find_section_returns_chunk_or_empty():
    chunk = find_section(SAMPLE, ["Key Audit Matters"], window=60)
    assert "Litigation" in chunk
    assert find_section(SAMPLE, ["Qualified Opinion"]) == ""  # clean audit -> keyword absent


def test_forensic_sections_cover_all_keys():
    secs = forensic_sections(SAMPLE, window=200)
    assert set(secs) == set(SECTION_KEYWORDS)
    assert secs["auditors_opinion"] != ""
    assert secs["related_party"] != ""
    assert secs["qualified_or_emphasis"] == ""  # no qualification present


def test_disclosure_gaps_clean_when_all_required_present():
    secs = forensic_sections(SAMPLE, window=200)
    missing, flag = disclosure_gaps(secs)
    assert flag is False and missing == []


def test_disclosure_gaps_flags_missing_mandated_section():
    # a filing where related-party & contingent-liability disclosures can't be found (not disclosed,
    # or unreadable image PDF) -> flagged, never a silent blank
    secs = forensic_sections("INDEPENDENT AUDITOR'S REPORT ... Key Audit Matters: litigation.", window=200)
    missing, flag = disclosure_gaps(secs)
    assert flag is True
    assert "related_party" in missing and "contingent_liabilities" in missing
    # conditional sections are never counted as required gaps
    assert "qualified_or_emphasis" not in missing
    assert set(missing) <= REQUIRED_DISCLOSURES
