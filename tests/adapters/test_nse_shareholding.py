"""Shareholding from the exchange's structured feed, and the cross-check against the filed PDF (ADR-0042).

WHY THE PDF PATH WAS THE WRONG TOOL
Parsing the company's own shareholding PDF works where there is a text layer and fails completely where
there is not. 19 of City Union Bank's 25 filings are photographs of paper; OCR rendered the category
table as `oo'o` for `0.00` and `ST88trZ` for `248815`, two of twenty-five parsed, and NONE carried a
readable date — which alone makes them useless to a point-in-time store. A structured numeric table
should not be recovered from a photograph when the same regulatory filing is published as data.
"""

from __future__ import annotations

from datetime import date

from firm.adapters.india.nse_shareholding import crosscheck, parse_master

#: Shaped exactly like the live NSE payload (verified against CUB and ALKYLAMINE, 2026-07-31).
_ROWS = [
    {"symbol": "ACME", "name": "Acme Limited", "date": "30-JUN-2026",
     "broadcastDate": "17-JUL-2026 18:25:43", "pr_and_prgrp": "72.04", "public_val": "27.96",
     "employeeTrusts": "0", "revisedData": "N", "xbrl": "https://nse.test/x.xml"},
    {"symbol": "ACME", "name": "Acme Limited", "date": "31-MAR-2026",
     "broadcastDate": "16-APR-2026 10:00:00", "pr_and_prgrp": "72.05", "public_val": "27.95",
     "employeeTrusts": "0", "revisedData": "Y"},
]


def test_the_feed_parses_into_dated_records_oldest_first():
    records = parse_master(_ROWS, "ACME")

    assert [r.as_on for r in records] == [date(2026, 3, 31), date(2026, 6, 30)]
    assert records[-1].promoter_pct == 72.04 and records[-1].public_pct == 27.96
    assert records[-1].company_name == "Acme Limited"
    assert records[0].revised is True, "a refiled quarter is a governance signal, not a detail"
    assert all(r.reconciles for r in records)


def test_published_at_is_the_broadcast_date_and_not_the_as_on_date():
    """The register described the company on 31 March; the market could not know it until 16 April.

    Using the as-on date would let a Phase-6 historical replay read a filing up to three weeks before it
    existed. Demonstrated live on City Union Bank: the quarter ended 30 June 2025 was disseminated on
    16 July 2025, so a run as-of 30 June 2025 must not see it.
    """
    records = parse_master(_ROWS, "ACME")
    for record in records:
        assert record.broadcast_on is not None
        assert record.broadcast_on >= record.as_on


def test_a_zero_promoter_stake_is_a_holding_and_not_a_missing_value():
    """City Union Bank has NO promoter: category (A) is 0.00% and public is 100.00%."""
    records = parse_master(
        [{"symbol": "CUB", "date": "31-MAR-2025", "broadcastDate": "07-APR-2025",
          "pr_and_prgrp": "0", "public_val": "100", "employeeTrusts": "0"}], "CUB")

    assert len(records) == 1
    assert records[0].promoter_pct == 0.0 and records[0].public_pct == 100.0
    assert records[0].reconciles


def test_an_undated_or_incomplete_row_is_dropped_rather_than_defaulted():
    records = parse_master(
        [{"symbol": "ACME", "date": "", "pr_and_prgrp": "50", "public_val": "50"},
         {"symbol": "ACME", "date": "31-MAR-2026", "pr_and_prgrp": None, "public_val": "50"}],
        "ACME")
    assert records == [], "a missing promoter percentage is not zero, and an undated quarter is unusable"


def test_the_crosscheck_confirms_two_independent_readings_of_the_same_filing():
    """The owner's requirement: extracted data must be cross-checked, not trusted because it parsed.

    Live result on Alkyl Amines: 18 of 18 comparable quarters agree exactly between this feed and the
    PDF parser reading the company's own filing.
    """
    records = parse_master(_ROWS, "ACME")
    result = crosscheck(records, {date(2026, 6, 30): 72.04, date(2026, 3, 31): 72.05})

    assert result.ok
    assert set(result.agreed) == {date(2026, 6, 30), date(2026, 3, 31)}
    assert "2 quarter(s) agree" in result.summary()


def test_a_four_decimal_pdf_reading_still_agrees_with_a_two_decimal_feed():
    """`72.0265` in the PDF against `72.03` from the exchange is the same disclosure, not a conflict."""
    records = parse_master(
        [{"symbol": "ACME", "date": "31-DEC-2025", "broadcastDate": "13-JAN-2026",
          "pr_and_prgrp": "72.03", "public_val": "27.97", "employeeTrusts": "0"}], "ACME")

    assert crosscheck(records, {date(2025, 12, 31): 72.0265}).ok


def test_a_real_disagreement_is_reported_and_never_averaged_away():
    records = parse_master(_ROWS, "ACME")
    result = crosscheck(records, {date(2026, 6, 30): 65.00})

    assert not result.ok
    assert len(result.disagreed) == 1
    assert result.disagreed[0].exchange_pct == 72.04
    assert result.disagreed[0].filing_pct == 65.00
    assert "DISAGREE" in result.summary()


def test_quarters_present_in_only_one_source_are_listed_not_silently_dropped():
    result = crosscheck(parse_master(_ROWS, "ACME"), {date(2025, 9, 30): 71.9})
    assert result.only_exchange == (date(2026, 3, 31), date(2026, 6, 30))
    assert result.only_filing == (date(2025, 9, 30),)
