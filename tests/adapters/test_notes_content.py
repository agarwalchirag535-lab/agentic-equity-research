"""Reading INSIDE a note (ADR-0027).

The failure mode guarded here is not a wrong number, it is a **false clean**: "I read the related-party note
and there were no loans to promoters" and "I could not find the note" both produce an empty result and mean
opposite things. Every test below pins that distinction, or pins a way the sum got polluted on the real
Alkyl Amines filing.
"""

from __future__ import annotations

import pytest

from firm.adapters.india.notes_content import find_note_body, related_party_summary

#: The FY26 Alkyl Amines note 41, in the layout pypdf actually produces: a category heading, then one line
#: per party with its figure, with last year in brackets underneath, wrapped in page furniture.
RP_NOTE = (
    "Alkyl Amines Chemicals Limited\n"
    "119\n"
    "Annual Report 2025-2026 Website: www.alkylamines.com\n"
    "41 RELATED PARTY DISCLOSURES\n"
    " There was no amount written off or written back from such parties during the year.\n"
    "` in Lakhs\n"
    "Particulars Key Management Personnel\n"
    "Directors' Remuneration/ Commission & Sitting Fees:\n"
    "Yogesh Kothari *  1,360.50\n"
    "(1,398.06)\n"
    "Kirat Patel *  609.04\n"
    " (583.41)\n"
    "Premal N. Kapadia\n"
    "   Sitting Fees  1.20\n"
    " (1.20)\n"
    "42 EARNINGS PER SHARE\n"
    "Net Profit after tax for the year (a)  17,999.91\n"
)


def test_the_note_body_stops_at_the_next_numbered_note():
    """Bleeding into note 42 would sweep ₹17,999.91 lakh of profit into directors' pay."""
    body = find_note_body((RP_NOTE,), r"related\s+part")
    assert body.located and body.number == 41
    assert "1,360.50" in body.text
    assert "17,999.91" not in body.text


def test_a_missing_note_is_located_false_not_an_empty_body():
    """The whole point: absent and empty must never look alike."""
    body = find_note_body(("Balance Sheet as at March 31, 2026\n",), r"related\s+part")
    assert body.located is False
    assert body.locator == "not found"

    summary = related_party_summary(("Balance Sheet\n",))
    assert summary.located is False
    assert summary.has_promoter_lending is None      # NOT False — we did not look
    assert summary.only_remuneration is False


def test_remuneration_is_summed_from_the_party_rows_under_the_category_heading():
    """These notes are block-structured: the heading names the category, the rows carry the figures.

    Summing only the lines that themselves name the category caught the "Sitting Fees" sub-labels and missed
    every director, returning ₹2.86cr against a real ₹27.69cr.
    """
    summary = related_party_summary((RP_NOTE,))
    assert summary.located and summary.note_number == 41
    # (1,360.50 + 609.04 + 1.20) lakh -> ₹19.71cr
    assert summary.remuneration_cr == pytest.approx((1360.50 + 609.04 + 1.20) / 100.0)


def test_page_furniture_is_not_directors_pay():
    """Page numbers and running headers all parse as numbers, and inflated the FY26 sum to ₹52.27cr.

    "119", "Annual Report 2025-2026 Website:", "Particulars Key Management Personnel" and the bracketed
    comparatives must all be excluded.
    """
    summary = related_party_summary((RP_NOTE,))
    assert summary.remuneration_cr is not None
    assert summary.remuneration_cr < 21.0                  # 119 or 26 leaking in would blow past this
    assert all("Annual Report" not in line for line in summary.lines_sampled)
    assert all(not line.startswith("(") for line in summary.lines_sampled)


def test_a_note_with_only_remuneration_is_a_positive_governance_finding():
    """Alkyl Amines FY26: no related-party sales, purchases, loans or guarantees — only director pay.

    That is the strongest statement an Ind AS 24 note can make about a promoter group, and it has to be
    distinguishable from "we didn't read it".
    """
    summary = related_party_summary((RP_NOTE,))
    assert summary.categories == frozenset({"remuneration"})
    assert summary.only_remuneration is True
    assert summary.has_promoter_lending is False           # read, and genuinely absent
    assert summary.explicit_nil_statement is True


def test_loans_and_guarantees_to_promoters_are_detected_when_present():
    """The check must fire when the channel IS used, or the False above means nothing."""
    note = (
        "41 RELATED PARTY DISCLOSURES\n"
        "` in Lakhs\n"
        "Loans given to Promoter Entity  5,000.00\n"
        "Guarantees given on behalf of related parties  2,500.00\n"
    )
    summary = related_party_summary((note,))
    assert {"loans_given", "guarantees"} <= summary.categories
    assert summary.has_promoter_lending is True
