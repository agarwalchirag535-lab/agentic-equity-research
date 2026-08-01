"""Tests for the audited-filing walk: grade-A facts, enumerated notes, honest dispositions (ADR-0021)."""

from __future__ import annotations

import pytest

from firm.core.compute.models import BusinessModel, build_playbook
from firm.core.config import (
    load_thresholds,
    model_forensic_thresholds,
    model_playbooks,
    universal_forensic_thresholds,
)
from firm.core.pipeline import derive as D
from firm.core.pipeline.checks import evaluate_checks
from firm.core.pipeline.filing import FilingSource, disposition_notes, walk_filing
from tests.conftest import (
    AS_OF,
    CLEAN_AR_PAGES,
    FILING_PUBLISHED,
    FRAUD_AR_PAGES,
    clean_series,
    filing_for,
    seed_store,
)

TH = load_thresholds()


def _walk_and_evaluate(store, ticker, pages, series=None, models=(BusinessModel.MANUFACTURER,)):
    seed_store(store, ticker, series or clean_series())
    walk = walk_filing(store, ticker, filing_for(ticker, pages))
    facts = D.load_company_facts(store, ticker, AS_OF)
    derived = D.derive_metrics(facts)
    evaluation = evaluate_checks(
        build_playbook(list(models), model_playbooks()), derived, facts,
        forensic=TH["forensic"], universal=universal_forensic_thresholds(),
        model_specific=model_forensic_thresholds(), external=walk.external,
    )
    return walk, evaluation


def test_filing_figures_are_stored_as_grade_a_facts_bound_to_page_and_line(store):
    walk, _ = _walk_and_evaluate(store, "ARCO", CLEAN_AR_PAGES)
    assert walk.registered_fact_ids

    fact = store.query_fact("ARCO", D.RECEIVABLES, "FY26", as_of=AS_OF)
    assert fact is not None
    assert fact.value == 118.0
    assert fact.grade == "A"                      # the audited filing outranks the screener snapshot
    # Provenance down to the line (Law 2), plus the scale AS PRINTED on the page — so a reader can
    # re-derive the stored crore figure from the filing without re-guessing the unit (ADR-0024).
    assert fact.locator == "p.1 l.6 (as printed: INR_cr)"
    assert fact.unit == "INR_cr"                  # canonical money scale, whatever the page declared
    assert fact.doc_id == "AR-ARCO-FY26"

    prior = store.query_fact("ARCO", D.RECEIVABLES, "FY25", as_of=AS_OF)
    assert prior is not None and prior.value == 110.0   # the comparative column is captured too


def test_the_notes_are_enumerated_and_all_dispositioned(store):
    walk, evaluation = _walk_and_evaluate(store, "ARCO", CLEAN_AR_PAGES)
    numbers = {n.number for n in walk.notes}
    assert {1, 2, 9, 10, 11, 21, 24, 29, 30} <= numbers

    review, dispositions = disposition_notes(walk.notes, evaluation)
    assert review.coverage == 1.0 and review.undispositioned == ()
    assert len(dispositions) == len(walk.notes)
    assert {d.status for d in dispositions} <= {"clean", "flag", "unknown"}


def test_substantive_share_exposes_coverage_that_did_not_read_anything(store):
    """100% coverage is cheap; the honest number is how many notes a real check actually looked at."""
    walk, evaluation = _walk_and_evaluate(store, "ARCO", CLEAN_AR_PAGES)
    review, dispositions = disposition_notes(walk.notes, evaluation)

    substantive = [d for d in dispositions if d.status in ("clean", "flag")]
    assert 0 < review.substantive_share < 1.0
    assert review.substantive_share == len(substantive) / review.notes_total
    # the notes no check covers say so, rather than being called clean
    unknown = [d for d in dispositions if d.status == "unknown"]
    assert unknown and any("no deterministic check covers" in d.rationale for d in unknown)


def test_a_fired_check_flags_its_note(store):
    walk, evaluation = _walk_and_evaluate(store, "STUFFED", FRAUD_AR_PAGES)
    _, dispositions = disposition_notes(walk.notes, evaluation)
    by_label = {d.note_label: d for d in dispositions}

    assert by_label["9"].status == "flag"                       # Note 9: Trade Receivables
    assert "receivables_divergent" in by_label["9"].rationale
    assert by_label["9"].figure_locators == ["p.4 l.3"]   # the notes page follows the three audited statement pages


def test_missing_mandated_disclosures_and_adverse_caro_clauses_surface(store):
    walk, _ = _walk_and_evaluate(store, "OPAQUE", FRAUD_AR_PAGES)
    assert "benami_property" in walk.missing_disclosures
    assert "wilful_defaulter" in walk.missing_disclosures
    assert walk.external.disclosure_scanned is True
    assert dict(walk.caro_flags).get("ix") == "default in repayment"


def test_a_row_absent_from_the_filing_is_simply_not_stored(store):
    pages = ("Notes to the Financial Statements\nNote 1: Corporate Information\n",)
    walk, evaluation = _walk_and_evaluate(store, "THIN", pages)
    assert walk.rows == {}
    assert store.query_fact("THIN", D.RECEIVABLES, "FY26", as_of=AS_OF) is None
    assert evaluation.record("receivables_divergent").reason.startswith("inputs not disclosed")


# ------------------------------------------------------------------------------------------------
# Scale discipline (ADR-0024) — found by running the pipeline on the real Alkyl Amines filings.


#: The FY26 Alkyl Amines balance-sheet page, as pypdf actually extracts it — including the ₹ glyph landing
#: as a backtick and the Schedule III note-reference column. The totals are what make it recognisable as
#: the balance sheet rather than a note (`audited_statement_pages`).
LAKH_AR_PAGES = (
    "Balance Sheet as at March 31, 2026\n"
    "` In Lakhs\n"
    "(ii)  Trade Receivables 11  23,049.50  23,064.82\n"
    "(iii) Cash and Cash Equivalents 12  9,415.34  4,877.87\n"
    "Total Assets  2,10,000.00  1,95,000.00\n"
    "Total Equity and Liabilities  2,10,000.00  1,95,000.00\n",
)
UNDECLARED_AR_PAGES = (
    "Balance Sheet as at March 31, 2026\n"
    "(ii)  Trade Receivables 11  23,049.50  23,064.82\n"
    "Total Assets  2,10,000.00  1,95,000.00\n"
    "Total Equity and Liabilities  2,10,000.00  1,95,000.00\n",
)


def test_a_lakh_filing_is_converted_to_the_canonical_crore_scale(store):
    """The real defect: Indian filings report in lakhs, every screener fact is in crore.

    Storing 23,049.50 as-is put receivables in the fact store 100x too large, wearing a grade-A stamp —
    so it would be believed over the correct secondary figure. Verified against the FY26 filing, where
    the audited revenue (₹1,535.86cr) matches the screener's 1,536.
    """
    filing = FilingSource(
        doc_id="AR-LAKHCO-FY26", source_url="https://example.test/ar.pdf",
        published_at=FILING_PUBLISHED, pages=LAKH_AR_PAGES, period="FY26", prior_period="FY25",
        sha256="0" * 8,
    )
    walk = walk_filing(store, "LAKHCO", filing)

    fact = store.query_fact("LAKHCO", D.RECEIVABLES, "FY26", as_of=AS_OF)
    assert fact is not None
    assert fact.value == pytest.approx(230.4950)      # 23,049.50 lakh -> ₹230.50 crore
    assert fact.unit == "INR_cr"
    assert "as printed: INR_lakh" in fact.locator
    assert walk.rows[D.RECEIVABLES].values[0] == 23049.50   # the row keeps the printed figure


def test_the_note_reference_column_is_not_read_as_a_figure(store):
    """`Trade Receivables 11  23,049.50` — the 11 points at note 11 and is not money.

    Before this, `values[0]` was 11.0 and receivables entered the store as ₹11 lakh.
    """
    filing = FilingSource(
        doc_id="AR-NOTECO-FY26", source_url="https://example.test/ar.pdf",
        published_at=FILING_PUBLISHED, pages=LAKH_AR_PAGES, period="FY26", prior_period="FY25",
        sha256="0" * 8,
    )
    walk_filing(store, "NOTECO", filing)
    cash = store.query_fact("NOTECO", D.CASH, "FY26", as_of=AS_OF)
    assert cash is not None and cash.value == pytest.approx(94.1534)   # not 0.12


def test_an_undeclared_scale_is_refused_and_reported_rather_than_assumed(store):
    """No unit on the page means the scale is unknown, and a guess would be worse than a gap.

    The row is not stored and the reason surfaces as a disclosure gap, so the check that needed it says
    UNAVAILABLE instead of quietly resting on a 100x error.
    """
    filing = FilingSource(
        doc_id="AR-NOUNIT-FY26", source_url="https://example.test/ar.pdf",
        published_at=FILING_PUBLISHED, pages=UNDECLARED_AR_PAGES, period="FY26", prior_period="FY25",
        sha256="0" * 8,
    )
    walk = walk_filing(store, "NOUNIT", filing)

    assert store.query_fact("NOUNIT", D.RECEIVABLES, "FY26", as_of=AS_OF) is None
    assert D.RECEIVABLES not in walk.rows
    assert any("scale is unknown" in gap for gap in walk.missing_disclosures)


# ------------------------------------------------------------------------------------------------
# Cross-document reconciliation (ADR-0024)


def test_overlap_classification_separates_rounding_from_restatement_from_misread():
    """The three cases found on the real Alkyl Amines filings, each needing a different response."""
    from firm.core.config import reconciliation_thresholds
    from firm.core.ingest.filings import Overlap

    pol = reconciliation_thresholds()

    def overlap(a: float, b: float) -> Overlap:
        return Overlap(metric="pnl:Sales", period="FY22", from_filing="new.pdf", from_value=b,
                       against_filing="old.pdf", against_value=a)

    # float representation noise across two multiplications: literally the same figure
    assert overlap(183.6629, 183.6629 + 1e-13).classify(pol) == "agree"
    # printed at different precision, under ₹1 lakh apart — 18,366.29 vs 18,366.30 lakh
    assert overlap(183.6629, 183.6630).classify(pol) == "rounding"
    assert overlap(37.8580, 37.8639).classify(pol) == "rounding"
    # a real reclassification: FY22 revenue ₹1,542.80cr reported, ₹1,541.99cr as the FY23 comparative
    assert overlap(1542.7985, 1541.9866).classify(pol) == "restated"
    # and the same magnitude on a bigger base must classify the SAME way, which a relative band broke
    assert overlap(1682.3360, 1683.0526).classify(pol) == "restated"
    # our misread, not their accounting: FY21 inventories ₹0.07cr against ₹121.90cr corroborated
    assert overlap(0.07, 121.8970).classify(pol) == "extraction_error"


def test_statement_scoping_rejects_a_cashflow_movement_line(store):
    """"(Increase) / Decrease in Trade Receivables (6,376.60)" is a cash-flow line, not a balance.

    Reading it as the balance gave FY21 receivables of NEGATIVE ₹63.77cr. A page that is not the balance
    sheet must not be a source for a balance-sheet metric.
    """
    from firm.adapters.base.tables import find_statement_row

    cashflow_only = (
        "AUDITED STATEMENT OF CASH FLOWS FOR THE YEAR ENDED\n"
        "` In Lakhs\n"
        "(Increase) / Decrease in Trade Receivables  (6,376.60)  1,234.00\n",
    )
    assert find_statement_row(cashflow_only, "balance_sheet", ("trade receivable",)) is None
