"""Tests for provenance-locked numeric extraction. The P&L page mirrors the REAL line layout observed in
CreditAccess Grameen's Q4FY25 presentation during live validation (docs/VALIDATION_TIER0.md)."""

from firm.adapters.base.tables import (
    ExtractedValue,
    extract_labeled_rows,
    find_row,
    numbers_on_line,
    page_unit_hint,
    parse_number,
)

# Page 1 mirrors a real Indian P&L table; page 2 has lakh-grouping and paren negatives.
PAGE_PNL = (
    "Profit & Loss Statement (INR Cr) Q4 FY25 Q4 FY24 YoY% Q3 FY25 QoQ% FY25 FY24 YoY%\n"
    "Impairment of Financial Instruments 582.9 153.3 280.2% 751.9 -22.5% 1,929.5 451.8 327.1%\n"
    "Profit After Tax 47.2 397.1 -88.1% (99.5) 147.4% 531.4 1,445.9 -63.2%\n"
    "Narrative line with no numbers at all\n"
)
PAGE_BS = (
    "Balance Sheet (Rs. in lakhs)\n"
    "Gross Loan Portfolio 1,08,314\n"
    "Net loss for the period (2,452.1)\n"
    "12,345\n"   # bare number, no label -> must be skipped
)


# ---- token parsing ------------------------------------------------------------------------------
def test_parse_number_indian_formats():
    assert parse_number("1,08,314") == 108314.0        # Indian lakh grouping
    assert parse_number("1,929.5") == 1929.5
    assert parse_number("(99.5)") == -99.5             # parenthesised negative
    assert parse_number("-22.5") == -22.5
    assert parse_number("280.2%") is None              # percents excluded from values
    assert parse_number("-") is None
    assert parse_number("") is None


def test_numbers_on_line_masks_period_tokens_and_percents():
    vals = numbers_on_line("Impairment FY25 FY24 1,929.5 451.8 327.1%")
    assert vals == (1929.5, 451.8)                     # FY tokens and % never parse as figures


def test_page_unit_hint():
    assert page_unit_hint(PAGE_PNL) == "INR_cr"
    assert page_unit_hint(PAGE_BS) == "INR_lakh"
    assert page_unit_hint("no unit declared here") == ""


# ---- row extraction with provenance -------------------------------------------------------------
def test_extract_labeled_rows_provenance_and_columns():
    rows = extract_labeled_rows([PAGE_PNL, PAGE_BS])
    by_label = {r.label: r for r in rows}

    imp = by_label["Impairment of Financial Instruments"]
    # ALL % columns excluded — including the signed QoQ "-22.5%" (a ratio, not a figure)
    assert imp.values == (582.9, 153.3, 751.9, 1929.5, 451.8)
    assert imp.page == 1 and imp.line == 2                            # exact locator (Law 2)
    assert imp.unit_hint == "INR_cr"
    assert "1,929.5" in imp.raw_line                                  # verbatim audit trail

    glp = by_label["Gross Loan Portfolio"]
    assert glp.values == (108314.0,) and glp.page == 2 and glp.unit_hint == "INR_lakh"

    net = by_label["Net loss for the period"]
    assert net.values == (-2452.1,)                                   # paren negative


def test_extract_skips_numberless_and_unlabeled_lines():
    labels = [r.label for r in extract_labeled_rows([PAGE_PNL, PAGE_BS])]
    assert "Narrative line with no numbers at all" not in labels      # nothing to anchor
    assert all(lbl for lbl in labels)                                 # bare "12,345" row skipped


def test_find_row_and_unavailable():
    row = find_row([PAGE_PNL], ["impairment"])
    assert row is not None and row.values[-2:] == (1929.5, 451.8)     # FY25/FY24 columns
    assert row.locator == "p.1 l.2"
    # absent label -> None, caller reports UNAVAILABLE (never guessed)
    assert find_row([PAGE_PNL], ["gain on sale"]) is None
    # exclude filter: skip 'Profit After Tax' when looking for pre-tax rows
    assert find_row([PAGE_PNL], ["profit"], exclude=["after tax"]) is None


def test_leading_note_reference_is_not_a_figure():
    """Regression (found by tests/test_pipeline_e2e.py): Indian AR line items carry a note
    cross-reference prefix. Without masking it, '9' parses as a value and the label collapses to 'Note'."""
    rows = extract_labeled_rows([("Note 9: Trade Receivables 118.0 110.0\n"
                                 "29. Contingent Liabilities 45.0 40.0\n"
                                 "12) Other Income 3.5\n")])
    by_label = {r.label: r.values for r in rows}
    assert by_label["Trade Receivables"] == (118.0, 110.0)     # note number excluded
    assert by_label["Contingent Liabilities"] == (45.0, 40.0)
    assert by_label["Other Income"] == (3.5,)
    assert "Note" not in by_label


def test_numbers_on_line_excludes_leading_note_ref():
    assert numbers_on_line("Note 9: Trade Receivables 118.0 110.0") == (118.0, 110.0)


def test_extracted_value_locator_property():
    ev = ExtractedValue("x", (1.0,), 3, 7, "", "x 1.0")
    assert ev.locator == "p.3 l.7"
