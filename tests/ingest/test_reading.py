"""ADR-0046: the reading verifier. Every rule refuses the failure class that produced it — the PC
Jeweller transition-note misread (wrong table, at grade A, past every internal-consistency defence) is
the regression fixture the whole module answers to."""

from __future__ import annotations

from datetime import date

import pytest

from firm.core.facts.store import FactStore
from firm.core.ingest.reading import (
    VERIFY_NET_CHANGE_IN_CASH,
    VERIFY_TOTAL_EQ_LIAB,
    FilingReading,
    ProposedColumn,
    ProposedFigure,
    ProposedStatement,
    build_reading_packet,
    proposal_from_json,
    register_reading,
    verify_statement,
)

# A faithful miniature of the real FY17 balance sheet page (p.74 shape): two dated columns, crores.
BS_PAGE = """\
BaLancE sHEEt as at 31 march 2017
(` in crores)
Particulars  note  as at  as at
31 march 2017  31 march 2016
Inventories  3  3,528.60  3,228.30
Trade receivables  4  1,183.83  767.53
Cash and cash equivalents  5  183.75  92.11
total assets  6,153.30  4,705.11
Equity share capital  179.10  179.10
Other equity  2,479.79  1,892.34
Borrowings (non-current)  0.25  0.41
Borrowings (current)  2,159.24  680.97
Trade payables  12  1,148.14  1,801.96
total equity and liabilities  6,153.30  4,705.11
"""

# The table that poisoned the store: the Ind AS transition note. Its heading names 2016, its columns
# name no year at all — V1 and V3 must both refuse it.
TRANSITION_PAGE = """\
B.2  Effect of ind as adoption on the balance sheet as at 31 march 2016
(` in crores)
Particulars  notes  Previous  adjustments  amount under
GaaP*  ind as
Inventories  3  3,229.85  (1.55)  3,228.30
total assets  4,711.52  (6.41)  4,705.11
total equity and liabilities  4,711.52  (6.41)  4,705.11
"""


def _columns() -> tuple[ProposedColumn, ...]:
    return (
        ProposedColumn(period="FY17", label_quote="as at\n31 march 2017"),
        ProposedColumn(period="FY16", label_quote="31 march 2016"),
    )


def _bs_statement(**overrides) -> ProposedStatement:
    base = {
        "statement": "balance_sheet", "basis": "standalone", "period": "FY17", "pages": (1,),
        "heading_quote": "BaLancE sHEEt as at 31 march 2017",
        "unit_quote": "(` in crores)", "unit": "INR_cr",
        "columns": _columns(),
        "figures": (
            ProposedFigure("balance_sheet:Inventories", "FY17", "3,528.60", 1, "Inventories"),
            ProposedFigure("balance_sheet:Trade Receivables", "FY17", "1,183.83", 1, "Trade receivables"),
            ProposedFigure("balance_sheet:Non-Current Borrowings", "FY17", "0.25", 1,
                           "Borrowings (non-current)"),
            ProposedFigure("balance_sheet:Current Borrowings", "FY17", "2,159.24", 1,
                           "Borrowings (current)"),
            ProposedFigure("balance_sheet:Total Assets", "FY17", "6,153.30", 1, "total assets"),
            ProposedFigure(VERIFY_TOTAL_EQ_LIAB, "FY17", "6,153.30", 1, "total equity and liabilities"),
        ),
    }
    base.update(overrides)
    return ProposedStatement(**base)


def test_a_faithful_transcription_verifies_and_registers():
    reading = verify_statement(_bs_statement(), [BS_PAGE])
    assert reading.verified, reading.violations
    store = FactStore(":memory:")
    ids, skipped = register_reading(
        store, "PCJEWELLER",
        FilingReading("AR-FY17-x.pdf", (reading,)),
        source_url="https://example.test", published_at=date(2017, 9, 9),
        preferred_basis="standalone",
    )
    assert skipped == ()
    assert "AR-FY17-x.pdf:balance_sheet:Trade Receivables:FY17" in ids
    fact = store.query_fact("PCJEWELLER", "balance_sheet:Trade Receivables", "FY17", date(2018, 1, 1))
    assert fact is not None and fact.value == pytest.approx(1183.83)
    # Borrowings composed deterministically from the two printed rows, locator naming both.
    borrow = store.query_fact("PCJEWELLER", "balance_sheet:Borrowings", "FY17", date(2018, 1, 1))
    assert borrow is not None and borrow.value == pytest.approx(2159.49)
    assert "+" in borrow.locator


def test_the_transition_note_is_refused_even_though_it_balances():
    """The exact PC Jeweller failure: internally consistent, correctly unit-declared, and WRONG."""
    stmt = _bs_statement(
        pages=(1,),
        heading_quote="Effect of ind as adoption on the balance sheet as at 31 march 2016",
        columns=(
            ProposedColumn(period="FY17", label_quote="Previous\nGaaP*"),
            ProposedColumn(period="FY16", label_quote="adjustments"),
        ),
        figures=(
            ProposedFigure("balance_sheet:Inventories", "FY17", "3,229.85", 1, "Inventories"),
            ProposedFigure("balance_sheet:Total Assets", "FY17", "4,711.52", 1, "total assets"),
            ProposedFigure(VERIFY_TOTAL_EQ_LIAB, "FY17", "4,711.52", 1, "total equity and liabilities"),
        ),
    )
    reading = verify_statement(stmt, [TRANSITION_PAGE])
    rules = {v.rule for v in reading.violations}
    assert "V1_heading" in rules      # heading names 2016, not FY17's 2017
    assert "V3_column" in rules       # "Previous GaaP*" / "adjustments" name no year
    assert not reading.figures


def test_a_fabricated_value_is_refused_by_literal_search():
    stmt = _bs_statement(figures=_bs_statement().figures[:-2] + (
        ProposedFigure("balance_sheet:Total Assets", "FY17", "6,999.99", 1, "total assets"),
        ProposedFigure(VERIFY_TOTAL_EQ_LIAB, "FY17", "6,153.30", 1, "total equity and liabilities"),
    ))
    reading = verify_statement(stmt, [BS_PAGE])
    assert any(v.rule == "V4_value" and "6,999.99" in v.detail for v in reading.violations)


def test_an_unknown_or_undeclared_unit_is_refused():
    assert any(v.rule == "V2_unit" for v in
               verify_statement(_bs_statement(unit="USD_mm"), [BS_PAGE]).violations)
    assert any(v.rule == "V2_unit" for v in
               verify_statement(_bs_statement(unit_quote="(Rs in lakhs)"), [BS_PAGE]).violations)


def test_plain_rupee_filings_convert_to_crore():
    """The pre-2016 era: ten-digit figures under a bare rupee sign (PC Jeweller FY13)."""
    page = ("Statement of Profit and Loss for the year ended March 31, 2013\n`\n"
            "Year ended\nMarch 31, 2013\nRevenue from operations  20  40,184,193,574\n")
    stmt = ProposedStatement(
        statement="pnl", basis="consolidated", period="FY13", pages=(1,),
        heading_quote="Statement of Profit and Loss for the year ended March 31, 2013",
        unit_quote="`", unit="INR",
        columns=(ProposedColumn(period="FY13", label_quote="Year ended\nMarch 31, 2013"),),
        figures=(ProposedFigure("pnl:Sales", "FY13", "40,184,193,574", 1, "Revenue from operations"),),
    )
    # standalone/consolidated: heading has no 'consolidated', so claim standalone for this fixture
    stmt = ProposedStatement(**{**stmt.__dict__, "basis": "standalone"})
    reading = verify_statement(stmt, [page])
    assert reading.verified, reading.violations
    assert reading.figures[0].value_crore == pytest.approx(4018.4193574)


def test_a_balance_sheet_that_does_not_balance_is_refused_whole():
    page = BS_PAGE.replace("total assets  6,153.30", "total assets  6,999.99")
    stmt = _bs_statement(figures=_bs_statement().figures[:-2] + (
        ProposedFigure("balance_sheet:Total Assets", "FY17", "6,999.99", 1, "total assets"),
        ProposedFigure(VERIFY_TOTAL_EQ_LIAB, "FY17", "6,153.30", 1, "total equity and liabilities"),
    ))
    reading = verify_statement(stmt, [page])
    assert any(v.rule == "V5_identity" for v in reading.violations)
    assert not reading.verified


def test_a_balance_sheet_missing_its_totals_cannot_verify():
    stmt = _bs_statement(figures=_bs_statement().figures[:2])
    assert any(v.rule == "V5_identity" for v in verify_statement(stmt, [BS_PAGE]).violations)


def test_pnl_parts_overshooting_the_total_are_refused():
    page = ("statement of Profit and Loss for the year ended 31 march 2017\n(` in crores)\n"
            "year ended 31 march 2017\n"
            "Cost of materials consumed  7,000.00\nEmployee benefits expense  70.17\n"
            "Finance costs  214.65\nTotal expenses  6,769.93\n")
    stmt = ProposedStatement(
        statement="pnl", basis="standalone", period="FY17", pages=(1,),
        heading_quote="statement of Profit and Loss for the year ended 31 march 2017",
        unit_quote="(` in crores)", unit="INR_cr",
        columns=(ProposedColumn(period="FY17", label_quote="year ended 31 march 2017"),),
        figures=(
            ProposedFigure("pnl:Cost of Materials Consumed", "FY17", "7,000.00", 1, "Cost of materials"),
            ProposedFigure("pnl:Employee Benefits", "FY17", "70.17", 1, "Employee benefits expense"),
            ProposedFigure("pnl:Interest", "FY17", "214.65", 1, "Finance costs"),
            ProposedFigure("pnl:Total Expenses", "FY17", "6,769.93", 1, "Total expenses"),
        ),
    )
    assert any(v.rule == "V6_pnl_sum" for v in verify_statement(stmt, [page]).violations)


def test_cashflow_legs_must_reconcile_to_the_net_change():
    page = ("casH fLoW statEmEnt for the year ended 31 March 2017\n(` in crores)\n"
            "year ended 31 march 2017\n"
            "Net cash from operating activities  (410.00)\nNet cash used in investing activities  (25.00)\n"
            "Net cash from financing activities  500.00\nNet increase in cash  165.00\n")
    stmt = ProposedStatement(
        statement="cashflow", basis="standalone", period="FY17", pages=(1,),
        heading_quote="casH fLoW statEmEnt for the year ended 31 March 2017",
        unit_quote="(` in crores)", unit="INR_cr",
        columns=(ProposedColumn(period="FY17", label_quote="year ended 31 march 2017"),),
        figures=(
            ProposedFigure("cashflow:Cash from Operating Activity", "FY17", "(410.00)", 1, "operating"),
            ProposedFigure("cashflow:Cash from Investing Activity", "FY17", "(25.00)", 1, "investing"),
            ProposedFigure("cashflow:Cash from Financing Activity", "FY17", "500.00", 1, "financing"),
            ProposedFigure(VERIFY_NET_CHANGE_IN_CASH, "FY17", "165.00", 1, "Net increase in cash"),
        ),
    )
    assert any(v.rule == "V7_cashflow" for v in verify_statement(stmt, [page]).violations)
    good = ProposedStatement(**{**stmt.__dict__, "figures": stmt.figures[:-1] + (
        ProposedFigure(VERIFY_NET_CHANGE_IN_CASH, "FY17", "65.00", 1, "Net increase"),)})
    page_good = page.replace("Net increase in cash  165.00", "Net increase  65.00")
    assert verify_statement(good, [page_good]).verified


def test_an_implausible_magnitude_is_a_unit_error_not_a_fact():
    page = BS_PAGE + "\nSundry row  99,999,999,999,999,999\n"
    stmt = _bs_statement(figures=_bs_statement().figures + (
        ProposedFigure("balance_sheet:CWIP", "FY17", "99,999,999,999,999,999", 1, "Sundry row"),))
    assert any(v.rule == "V9_plausibility" for v in verify_statement(stmt, [page]).violations)


def test_a_nil_dash_is_zero_not_a_search_failure():
    page = BS_PAGE.replace("Trade payables  12  1,148.14", "Trade payables  12  -")
    figs = tuple(f for f in _bs_statement().figures) + (
        ProposedFigure("balance_sheet:Trade Payables", "FY17", "-", 1, "Trade payables"),)
    reading = verify_statement(_bs_statement(figures=figs), [page])
    assert reading.verified, reading.violations
    assert {f.metric: f.value_crore for f in reading.figures}["balance_sheet:Trade Payables"] == 0.0


def test_basis_must_match_the_heading():
    stmt = _bs_statement(basis="consolidated")
    assert any(v.rule == "V1_heading" and "consolidated" in v.detail
               for v in verify_statement(stmt, [BS_PAGE]).violations)


def test_register_prefers_consolidated_and_falls_back_to_standalone():
    reading = verify_statement(_bs_statement(), [BS_PAGE])
    store = FactStore(":memory:")
    ids, _ = register_reading(store, "PCJEWELLER", FilingReading("AR-FY17-x.pdf", (reading,)),
                              source_url="u", published_at=date(2017, 9, 9))
    assert ids  # consolidated absent -> the verified standalone statement is registered
    assert store.query_fact("PCJEWELLER", "balance_sheet:Total Assets", "FY17", date(2018, 1, 1))


def test_a_refused_statement_registers_nothing():
    stmt = _bs_statement(heading_quote="not on the page at all 2017")
    reading = verify_statement(stmt, [BS_PAGE])
    store = FactStore(":memory:")
    ids, _ = register_reading(store, "PCJEWELLER", FilingReading("AR-FY17-x.pdf", (reading,)),
                              source_url="u", published_at=date(2017, 9, 9),
                              preferred_basis="standalone")
    assert ids == ()


def test_proposal_json_round_trip_and_malformed_errors():
    text = """{"statements": [{"statement": "balance_sheet", "basis": "standalone", "period": "FY17",
        "pages": [1], "heading_quote": "BaLancE sHEEt as at 31 march 2017",
        "unit_quote": "(` in crores)", "unit": "INR_cr",
        "columns": [{"period": "FY17", "label_quote": "as at\\n31 march 2017"},
                    {"period": null, "label_quote": "adjustments"}],
        "figures": [{"metric": "balance_sheet:Total Assets", "period": "FY17",
                     "value_printed": "6,153.30", "page": 1, "row_label": "total assets"}]}]}"""
    stmts = proposal_from_json(text)
    assert stmts[0].columns[1].period is None
    assert stmts[0].figures[0].value_printed == "6,153.30"
    with pytest.raises(ValueError, match="not valid JSON"):
        proposal_from_json("{nope")
    with pytest.raises(TypeError, match="statements"):
        proposal_from_json('{"answer": 42}')
    with pytest.raises(ValueError, match=r"statements\[0\]"):
        proposal_from_json('{"statements": [{"statement": "pnl"}]}')


def test_the_packet_numbers_every_page_and_carries_the_vocabulary():
    packet = build_reading_packet("AR-FY17-x.pdf", ["first page text", "second page text"])
    assert "===== page 1 =====" in packet and "===== page 2 =====" in packet
    assert "pnl:Sales" in packet and "never add them yourself" in packet


def test_a_scrambled_display_font_heading_still_passes_the_semantic_checks():
    """Real extractions scramble case AND intra-word spacing: 'ConsoliDA  teD  B Al  AnCe sHeet'.
    The semantic checks compare letters only; the honest quote of a scrambled heading must pass."""
    page = ("  ConsoliDA  teD  B Al  AnCe sHeet\n  as at 31 March 2016\n(Rs. in crores)\n"
            "Notes  As at  As at\n31 March 2016  31 March 2015\n"
            "total assets  5,762.34  4,723.97\n"
            "total equity and liabilities  5,762.34  4,723.97\n")
    stmt = ProposedStatement(
        statement="balance_sheet", basis="consolidated", period="FY16", pages=(1,),
        heading_quote="ConsoliDA  teD  B Al  AnCe sHeet\n  as at 31 March 2016",
        unit_quote="(Rs. in crores)", unit="INR_cr",
        columns=(ProposedColumn(period="FY16", label_quote="31 March 2016"),
                 ProposedColumn(period="FY15", label_quote="31 March 2015")),
        figures=(
            ProposedFigure("balance_sheet:Total Assets", "FY16", "5,762.34", 1, "total assets"),
            ProposedFigure(VERIFY_TOTAL_EQ_LIAB, "FY16", "5,762.34", 1, "total equity and liabilities"),
        ),
    )
    reading = verify_statement(stmt, [page])
    assert reading.verified, reading.violations


def test_per_share_figures_never_scale_with_the_statement_unit():
    """EPS on a '₹ in lacs' statement is still ₹21.13 — found live when the FY15 lakh conversion
    turned it into 0.21 and the cross-filing quarantine killed it against FY16's 21.13."""
    page = ("Consolidated Statement of Profit and Loss for the year ended 31 March 2015\n"
            "I in lacs\nYear ended\n31 March 2015\nProfit for the year  37,843.17\n"
            "Basic and diluted  21.13\n")
    stmt = ProposedStatement(
        statement="pnl", basis="consolidated", period="FY15", pages=(1,),
        heading_quote="Consolidated Statement of Profit and Loss for the year ended 31 March 2015",
        unit_quote="I in lacs", unit="INR_lakh",
        columns=(ProposedColumn(period="FY15", label_quote="Year ended\n31 March 2015"),),
        figures=(
            ProposedFigure("pnl:Net Profit", "FY15", "37,843.17", 1, "Profit for the year"),
            ProposedFigure("pnl:EPS in Rs", "FY15", "21.13", 1, "Basic and diluted"),
        ),
    )
    reading = verify_statement(stmt, [page])
    assert reading.verified, reading.violations
    values = {f.metric: f.value_crore for f in reading.figures}
    assert values["pnl:Net Profit"] == pytest.approx(378.4317)   # lakhs -> crore
    assert values["pnl:EPS in Rs"] == pytest.approx(21.13)       # rupees, untouched


NOTE_PAGES = [
    "note 1: corporate information\nPC Jeweller Limited was incorporated\n",
    "note 2: inventories\nnote 3: trade receivables\n",
    "note: 4 related party transactions:\ntotal  6.95  6.03\n",
]


def test_a_faithful_note_enumeration_verifies():
    from firm.core.ingest.reading import ProposedNote, verify_notes
    notes, violations = verify_notes([
        ProposedNote("1", "corporate information", 1),
        ProposedNote("2", "inventories", 2),
        ProposedNote("3", "trade receivables", 2),
        ProposedNote("4", "related party transactions", 3),
    ], NOTE_PAGES)
    assert not violations
    assert [n.label for n in notes] == ["1", "2", "3", "4"]
    assert notes[1].category == "inventory"      # the taxonomy still classifies override notes


def test_note_enumeration_refuses_wrong_page_duplicates_and_disorder():
    from firm.core.ingest.reading import ProposedNote, verify_notes
    _, v1 = verify_notes([ProposedNote("1", "corporate information", 3)], NOTE_PAGES)
    assert any(x.rule == "N1_title" for x in v1)
    _, v2 = verify_notes([ProposedNote("2", "inventories", 2),
                          ProposedNote("2", "inventories", 2)], NOTE_PAGES)
    assert any(x.rule == "N2_label" for x in v2)
    _, v3 = verify_notes([ProposedNote("4", "related party transactions", 3),
                          ProposedNote("2", "inventories", 2)], NOTE_PAGES)
    assert {x.rule for x in v3} >= {"N3_order", "N4_order"}


def test_related_party_reading_verifies_the_printed_remuneration():
    from firm.core.ingest.reading import ProposedRelatedParty, verify_related_party
    summary, violations = verify_related_party(ProposedRelatedParty(
        note_label="4", page=3, title_quote="note: 4 related party transactions:",
        categories=("remuneration", "rent", "dividend"),
        kmp_remuneration_printed="6.95", remuneration_page=3,
    ), NOTE_PAGES)
    assert not violations
    assert summary.located and summary.remuneration_cr == pytest.approx(6.95)
    assert summary.has_promoter_lending is False     # no loans_given/guarantees category
    _, bad = verify_related_party(ProposedRelatedParty(
        note_label="4", page=3, title_quote="note: 4 related party transactions:",
        categories=("remuneration",), kmp_remuneration_printed="9.99", remuneration_page=3,
    ), NOTE_PAGES)
    assert any(x.rule == "V4_value" for x in bad)


# The Symphony transition filing, in miniature: a twelve-month year beside a NINE-MONTH stub, which is
# how a company that moves its year-end reports. Read as if both were years, revenue "grew 72%" when it
# grew 29%, and a run one year earlier would have fired receivables_divergent on a clean compounder.
STUB_PNL_PAGE = """\
Consolidated Statement of Profit and Loss  for the year ended 31st March, 2017
  (H in Lacs)
  Particulars  Note  Year ended 31/03/2017  Nine months ended 31/03/2016
  I  Revenue from Operations  20  76,802.90  44,554.65
  VII  Profit for the year  16,559.64  11,836.51
"""


def _stub_pnl(**overrides) -> ProposedStatement:
    base = {
        "statement": "pnl", "basis": "consolidated", "period": "FY17", "pages": (1,),
        "heading_quote": "Consolidated Statement of Profit and Loss  for the year ended 31st March, 2017",
        "unit_quote": "(H in Lacs)", "unit": "INR_lakh",
        "columns": (
            ProposedColumn(period="FY17", label_quote="Year ended 31/03/2017", months=12),
            ProposedColumn(period="FY16", label_quote="Nine months ended 31/03/2016", months=9),
        ),
        "figures": (
            ProposedFigure("pnl:Sales", "FY17", "76,802.90", 1, "Revenue from Operations"),
            ProposedFigure("pnl:Sales", "FY16", "44,554.65", 1, "Revenue from Operations"),
            ProposedFigure("pnl:Net Profit", "FY17", "16,559.64", 1, "Profit for the year"),
        ),
    }
    base.update(overrides)
    return ProposedStatement(**base)


def test_a_stub_period_verifies_but_its_flow_figures_are_never_stored():
    reading = verify_statement(_stub_pnl(), [STUB_PNL_PAGE])
    assert reading.verified, reading.violations
    months = {(f.metric, f.period): f.period_months for f in reading.figures}
    assert months[("pnl:Sales", "FY17")] == 12
    assert months[("pnl:Sales", "FY16")] == 9

    store = FactStore(":memory:")
    ids, skipped = register_reading(store, "SYMPHONY", FilingReading("AR-FY17-x.pdf", (reading,)),
                                    source_url="u", published_at=date(2017, 7, 8))
    assert "AR-FY17-x.pdf:pnl:Sales:FY17" in ids
    assert not any(":FY16" in i for i in ids)          # the stub's flows never enter the store
    assert len(skipped) == 1 and "9 months" in skipped[0] and "not annualised" in skipped[0]
    assert store.query_fact("SYMPHONY", "pnl:Sales", "FY16", date(2018, 1, 1)) is None


def test_a_stub_periods_stock_figures_are_stored_normally():
    """A balance sheet closing a nine-month period is an ordinary balance sheet: stocks are dated,
    flows are periodic, and only flows are damaged by a period-length change."""
    page = ("Consolidated Balance Sheet as at 31st March, 2016\n(H in Lacs)\n"
            "As at  31/03/2016\nTrade receivables  4,686.91\n"
            "TOTAL ASSETS  43,035.70\nTotal Equity and Liabilities  43,035.70\n")
    stmt = ProposedStatement(
        statement="balance_sheet", basis="consolidated", period="FY16", pages=(1,),
        heading_quote="Consolidated Balance Sheet as at 31st March, 2016",
        unit_quote="(H in Lacs)", unit="INR_lakh",
        columns=(ProposedColumn(period="FY16", label_quote="As at  31/03/2016"),),
        figures=(
            ProposedFigure("balance_sheet:Trade Receivables", "FY16", "4,686.91", 1, "Trade receivables"),
            ProposedFigure("balance_sheet:Total Assets", "FY16", "43,035.70", 1, "TOTAL ASSETS"),
            ProposedFigure(VERIFY_TOTAL_EQ_LIAB, "FY16", "43,035.70", 1, "Total Equity and Liabilities"),
        ),
    )
    reading = verify_statement(stmt, [page])
    assert reading.verified, reading.violations
    store = FactStore(":memory:")
    ids, skipped = register_reading(store, "SYMPHONY", FilingReading("AR-FY16-x.pdf", (reading,)),
                                    source_url="u", published_at=date(2016, 9, 1))
    assert skipped == () and any("Trade Receivables:FY16" in i for i in ids)


def test_a_declared_length_that_contradicts_the_filing_is_refused():
    """The failure this rule exists to stop: calling the nine-month column a year."""
    stmt = _stub_pnl(columns=(
        ProposedColumn(period="FY17", label_quote="Year ended 31/03/2017", months=12),
        ProposedColumn(period="FY16", label_quote="Nine months ended 31/03/2016", months=12),  # the lie
    ))
    violations = verify_statement(stmt, [STUB_PNL_PAGE]).violations
    assert any(v.rule == "V3b_period_length" and "words say 9" in v.detail for v in violations)


def test_a_flow_column_of_unstated_length_is_refused_not_assumed_to_be_a_year():
    stmt = _stub_pnl(
        heading_quote="Consolidated Statement of Profit and Loss",   # heading states no length either
        columns=(ProposedColumn(period="FY17", label_quote="Particulars 2017", months=None),),
        figures=(ProposedFigure("pnl:Sales", "FY17", "76,802.90", 1, "Revenue from Operations"),),
    )
    page = STUB_PNL_PAGE.replace(
        "Consolidated Statement of Profit and Loss  for the year ended 31st March, 2017",
        "Consolidated Statement of Profit and Loss 2017").replace(
        "Particulars  Note  Year ended 31/03/2017  Nine months ended 31/03/2016",
        "Particulars 2017")
    violations = verify_statement(stmt, [page]).violations
    assert any(v.rule == "V3b_period_length" and "cannot be assumed" in v.detail for v in violations)


def test_the_heading_supplies_the_length_when_a_column_label_does_not():
    """Real filings label cash-flow columns 'As at' even though they are periods; the heading says
    'for the year ended' and that is what the length comes from."""
    page = ("Consolidated Cash Flow Statement for the year ended March 31, 2014\n`  `\n"
            "As at\n  March 31, 2014\nNet cash generated  5,200,092,868\n")
    stmt = ProposedStatement(
        statement="cashflow", basis="consolidated", period="FY14", pages=(1,),
        heading_quote="Consolidated Cash Flow Statement for the year ended March 31, 2014",
        unit_quote="`  `", unit="INR",
        columns=(ProposedColumn(period="FY14", label_quote="As at\n  March 31, 2014"),),
        figures=(ProposedFigure("cashflow:Cash from Operating Activity", "FY14", "5,200,092,868", 1,
                                "Net cash generated"),),
    )
    reading = verify_statement(stmt, [page])
    assert reading.verified, reading.violations
    assert reading.figures[0].period_months == 12
