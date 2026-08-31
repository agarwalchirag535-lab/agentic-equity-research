"""ADR-0049, the reading half: V3c establishes every period column's CLOSING DATE from the filing's
own words, the same way V3b establishes its length. `FY{yy}` assumes a 31-March close for every
company; Symphony's FY13–FY15 close on 30 June, and a column that states no close is refused rather
than assumed."""

from __future__ import annotations

from datetime import date

import pytest

from firm.core.facts.store import FactStore
from firm.core.ingest.reading import (
    FilingReading,
    ProposedColumn,
    ProposedFigure,
    ProposedStatement,
    dates_stated,
    end_stated,
    proposal_from_json,
    register_reading,
    verify_statement,
)

# A June-closer's P&L page in the layout Symphony's pre-FY16 filings use ("year ended 30th June").
# The figures are synthetic; the LAYOUT — ordinal date forms, split header, June close — is the real
# thing V3c has to read. Symphony's own FY13-FY15 filings are the live target once ingested.
JUNE_PNL_PAGE = """\
Statement of Profit and Loss for the year ended 30th June, 2015
(` in crores)
Particulars  note  Year ended  Year ended
30th June, 2015  30th June, 2014
Revenue from operations  21  531.61  438.94
Profit for the year  110.02  86.99
"""


def _june_statement(**overrides) -> ProposedStatement:
    base = {
        "statement": "pnl", "basis": "standalone", "period": "FY15", "pages": (1,),
        "heading_quote": "Statement of Profit and Loss for the year ended 30th June, 2015",
        "unit_quote": "(` in crores)", "unit": "INR_cr",
        "columns": (
            ProposedColumn(period="FY15", label_quote="Year ended\n30th June, 2015"),
            ProposedColumn(period="FY14", label_quote="30th June, 2014"),
        ),
        "figures": (
            ProposedFigure("pnl:Sales", "FY15", "531.61", 1, "Revenue from operations"),
            ProposedFigure("pnl:Net Profit", "FY15", "110.02", 1, "Profit for the year"),
        ),
    }
    base.update(overrides)
    return ProposedStatement(**base)


# ---- the date grammar -----------------------------------------------------------------------------

def test_dates_stated_reads_every_form_indian_filings_print():
    assert dates_stated("as at 31/03/2016") == {date(2016, 3, 31)}
    assert dates_stated("year ended 31-03-2016") == {date(2016, 3, 31)}
    assert dates_stated("for the year ended 31 March 2017") == {date(2017, 3, 31)}
    assert dates_stated("year ended 30th June, 2015") == {date(2015, 6, 30)}
    assert dates_stated("AS AT MARCH 31, 2026") == {date(2026, 3, 31)}


def test_an_impossible_printed_date_is_not_a_date():
    assert dates_stated("as at 31/04/2016") == frozenset()


def test_end_stated_filters_to_the_periods_own_calendar_year():
    # a split header carries both columns' dates; the year filter separates them
    text = "Year ended  Nine months ended  31/03/2017  31/03/2016"
    assert end_stated(text, 2017) == date(2017, 3, 31)
    assert end_stated(text, 2016) == date(2016, 3, 31)


def test_two_dates_in_the_same_year_are_ambiguous_not_a_guess():
    assert end_stated("as at 31 March 2016 and 1 April 2016", 2016) is None


# ---- V3c ------------------------------------------------------------------------------------------

def test_a_june_year_end_is_read_from_the_filings_own_words():
    reading = verify_statement(_june_statement(), [JUNE_PNL_PAGE])
    assert reading.verified, reading.violations
    by_metric = {f.metric: f for f in reading.figures}
    assert by_metric["pnl:Sales"].period_end == date(2015, 6, 30)
    assert by_metric["pnl:Sales"].period_months == 12


def test_a_column_stating_no_close_is_refused_not_assumed_to_be_march():
    page = JUNE_PNL_PAGE.replace("Statement of Profit and Loss for the year ended 30th June, 2015",
                                 "Statement of Profit and Loss for the year FY2015")
    stmt = _june_statement(
        heading_quote="Statement of Profit and Loss for the year FY2015",
        columns=(
            ProposedColumn(period="FY15", label_quote="Year ended\n30th June, 2015"),
            ProposedColumn(period="FY14", label_quote="Year ended 2014"),
        ),
    )
    page = page.replace("30th June, 2014", "Year ended 2014")
    reading = verify_statement(stmt, [page])
    rules = {v.rule for v in reading.violations}
    assert "V3c_period_close" in rules
    assert any("cannot be assumed to be 31 March" in v.detail for v in reading.violations)


def test_the_heading_date_can_never_leak_onto_the_neighbouring_column():
    # heading names 30 June 2015; the FY14 column's own words carry its 2014 date — the heading's
    # 2015 date must date the FY15 column only, which the year filter guarantees
    reading = verify_statement(_june_statement(), [JUNE_PNL_PAGE])
    assert reading.verified
    # were the heading leaking, FY14 columns with no own date would silently inherit 2015-06-30;
    # instead such a column is refused outright:
    stmt = _june_statement(columns=(
        ProposedColumn(period="FY15", label_quote="Year ended\n30th June, 2015"),
        ProposedColumn(period="FY14", label_quote="Year ended (prior)"),
    ))
    page = JUNE_PNL_PAGE.replace("30th June, 2014", "Year ended (prior)")
    refused = verify_statement(stmt, [page])
    assert any(v.rule == "V3c_period_close" and "FY14" in v.detail for v in refused.violations)


def test_a_declared_end_contradicted_by_the_columns_own_words_is_refused():
    stmt = _june_statement(columns=(
        ProposedColumn(period="FY15", label_quote="Year ended\n30th June, 2015",
                       end=date(2015, 3, 31)),
        ProposedColumn(period="FY14", label_quote="30th June, 2014"),
    ))
    reading = verify_statement(stmt, [JUNE_PNL_PAGE])
    assert any(v.rule == "V3c_period_close" and "declares the close" in v.detail
               for v in reading.violations)


def test_a_declared_end_stands_where_the_words_are_ambiguous():
    # the column quote carries two dates of the period's year — ambiguous, so the declaration wins,
    # same discipline as V3b's months
    page = JUNE_PNL_PAGE.replace("Year ended  Year ended\n30th June, 2015",
                                 "Year ended 30th June, 2015 (restated 1st July, 2015)")
    stmt = _june_statement(columns=(
        ProposedColumn(period="FY15",
                       label_quote="Year ended 30th June, 2015 (restated 1st July, 2015)",
                       end=date(2015, 6, 30)),
        ProposedColumn(period="FY14", label_quote="30th June, 2014"),
    ))
    reading = verify_statement(stmt, [page])
    assert reading.verified, reading.violations
    assert {f.period_end for f in reading.figures} == {date(2015, 6, 30)}


# ---- registration + the JSON path -----------------------------------------------------------------

def test_the_stated_close_reaches_the_stored_fact():
    reading = verify_statement(_june_statement(), [JUNE_PNL_PAGE])
    assert reading.verified
    store = FactStore(":memory:")
    ids, skipped = register_reading(
        store, "SYMPHONY", FilingReading("AR-FY15.pdf", (reading,)),
        source_url="u", published_at=date(2015, 8, 31))
    assert ids and not skipped
    fact = store.query_fact("SYMPHONY", "pnl:Sales", "FY15", as_of=date(2015, 12, 31))
    assert fact is not None and fact.period_end == date(2015, 6, 30)


def test_proposal_json_carries_declared_months_and_end():
    text = """
    {"statements": [{
        "statement": "pnl", "basis": "standalone", "period": "FY15", "pages": [1],
        "heading_quote": "h", "unit_quote": "u", "unit": "INR_cr",
        "columns": [{"period": "FY15", "label_quote": "q", "months": 12, "end": "2015-06-30"}],
        "figures": []
    }]}
    """
    (stmt,) = proposal_from_json(text)
    assert stmt.columns[0].months == 12
    assert stmt.columns[0].end == date(2015, 6, 30)


def test_a_malformed_declared_end_names_its_statement():
    text = """
    {"statements": [{
        "statement": "pnl", "basis": "standalone", "period": "FY15", "pages": [1],
        "heading_quote": "h", "unit_quote": "u", "unit": "INR_cr",
        "columns": [{"period": "FY15", "label_quote": "q", "end": "30-06-2015"}],
        "figures": []
    }]}
    """
    with pytest.raises(ValueError, match="statements\\[0\\]"):
        proposal_from_json(text)
