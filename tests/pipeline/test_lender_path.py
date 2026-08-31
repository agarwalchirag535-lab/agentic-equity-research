"""The lender path, first wired to a real filing by ADR-0050.

`quality.py` has had lender check functions since ADR-0002/0012 and `VALIDATION_TIER0.md` calibrated
them on hand-transcribed figures — but no lender's filing had ever been read: the reading vocabulary had
no loan book, `statement_shape` never computed `loan_book_to_assets` (so LENDER could not be detected at
all), and `checks.py` had no evaluator for any of the seven lender checks.

Figures are CreditAccess Grameen FY24/FY25 consolidated, ₹ crore, from the audited annual report.
"""

from __future__ import annotations

from datetime import date

import pytest

from firm.core.compute import quality
from firm.core.compute.models import BusinessModel, build_playbook, detect_models
from firm.core.config import (
    forensic_thresholds,
    load_thresholds,
    model_detection_thresholds,
    model_forensic_thresholds,
    model_playbooks,
    universal_forensic_thresholds,
)
from firm.core.facts.store import Document, FactStore
from firm.core.pipeline import derive as D
from firm.core.pipeline.checks import evaluate_checks
from firm.core.pipeline.deep_dive import statement_shape
from firm.core.pipeline.filing import ExternalInputs

CREDITACC = {
    "FY25": {D.LOAN_BOOK: 24274.45, D.IMPAIRMENT: 1929.51, D.INTEREST_INCOME_PNL: 5546.76,
             D.SALES: 5752.33, D.PAT: 531.40, D.TOTAL_ASSETS: 27802.45, D.CFO: 1125.24,
             D.OTHER_INCOME: 3.81, D.PBT: 708.87, D.FIXED_ASSETS: 43.58},
    "FY24": {D.LOAN_BOOK: 25104.99, D.IMPAIRMENT: 451.77, D.INTEREST_INCOME_PNL: 4900.11,
             D.SALES: 5166.67, D.PAT: 1445.93, D.TOTAL_ASSETS: 28870.83, D.CFO: -4733.78,
             D.OTHER_INCOME: 5.98, D.PBT: 1939.18, D.FIXED_ASSETS: 32.08},
}


def _facts() -> D.CompanyFacts:
    store = FactStore(":memory:")
    for period, rows in CREDITACC.items():
        doc, pub = f"AR-{period}", date(int(f"20{period[2:]}"), 7, 5)
        store.add_document(Document(doc_id=doc, source_url="u", sha256="", published_at=pub,
                                    fetched_at=pub, grade="A", extractor_version="llm-read@1"))
        for metric, value in rows.items():
            store.add_fact(fact_id=f"{doc}:{metric}:{period}", doc_id=doc, ticker="CA", metric=metric,
                           period=period, value=value, unit="INR_cr", locator="p.138",
                           period_end=f"20{period[2:]}-03-31")
    return D.load_company_facts(store, "CA", date(2025, 12, 31), start_year=2024)


def _evaluate(facts: D.CompanyFacts):
    derived = D.derive_metrics(facts)
    models = tuple(detect_models(statement_shape(facts, derived), model_detection_thresholds()))
    playbook = build_playbook(models, model_playbooks())
    evaluation = evaluate_checks(
        playbook, derived, facts, forensic=load_thresholds()["forensic"],
        universal=universal_forensic_thresholds(), model_specific=model_forensic_thresholds(),
        external=ExternalInputs())
    return models, playbook, evaluation


def test_a_lender_is_detected_from_its_balance_sheet():
    facts = _facts()
    shape = statement_shape(facts, D.derive_metrics(facts))
    assert shape.loan_book_to_assets == pytest.approx(0.873, abs=0.005)
    assert shape.interest_income_to_revenue == pytest.approx(0.964, abs=0.005)
    assert BusinessModel.LENDER in detect_models(shape, model_detection_thresholds())


def test_the_pipeline_reproduces_the_hand_computed_creditaccess_result():
    """VALIDATION_TIER0 concluded REVIEW on provision-book divergence, with reserve-suppression
    correctly NOT firing (they provisioned more, honestly) and gain-on-sale UNAVAILABLE. The pipeline
    now reaches the same conclusion from the audited statements rather than from typed-in figures."""
    models, _, ev = _evaluate(_facts())
    divergence = ev.record("provision_book_divergent")
    assert divergence.outcome.value == "FLAG"
    assert "+327.1%" in divergence.detail            # impairment growth, as the filing prints it
    assert ev.record("reserve_suppression").outcome.value == "PASS"
    assert "raised" in ev.record("reserve_suppression").detail
    assert ev.record("gain_on_sale_reliant").outcome.value == "UNAVAILABLE"

    screen = quality.forensic_screen(quality.SectorClass.FINANCIAL, ev.metrics, forensic_thresholds())
    assert screen.verdict is quality.ForensicVerdict.REVIEW
    assert [f.name for f in screen.flags] == ["provision_book_divergent"]


def test_cash_conversion_is_suppressed_for_a_lender_because_it_measures_book_growth():
    """Under Ind AS 7 a lender's loan flows ARE its operating activity. CreditAccess converts +2.12 in
    FY25 (book shrank 3.3%) and -3.27 in FY24 (book grew) — same company, same accounting, opposite
    verdicts. Left applicable, the cumulative form is a SEVERE flag, so every growing lender is a fraud."""
    _, playbook, ev = _evaluate(_facts())
    for check in ("cumulative_cfo_pat", "cfo_pat"):
        assert not playbook.runs(check)
        assert ev.record(check).outcome.value == "NOT_APPLICABLE"
        assert "LENDER" in ev.record(check).reason
    # the arithmetic that justifies the suppression, stated so a reader can check it
    assert CREDITACC["FY24"][D.CFO] / CREDITACC["FY24"][D.PAT] == pytest.approx(-3.27, abs=0.01)
    assert CREDITACC["FY25"][D.CFO] / CREDITACC["FY25"][D.PAT] == pytest.approx(2.12, abs=0.01)


def test_a_note_level_lender_check_names_what_it_needs():
    """A check we cannot yet run must not read like a disclosure the company failed to make."""
    _, _, ev = _evaluate(_facts())
    reason = ev.record("gnpa_drift").reason
    assert "asset-quality note" in reason and "not\nthe face" not in reason
    assert ev.record("provision_coverage_low").reason != ev.record("gnpa_drift").reason
