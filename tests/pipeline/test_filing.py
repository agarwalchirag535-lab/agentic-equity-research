"""Tests for the audited-filing walk: grade-A facts, enumerated notes, honest dispositions (ADR-0021)."""

from __future__ import annotations

from firm.core.compute.models import BusinessModel, build_playbook
from firm.core.config import (
    load_thresholds,
    model_forensic_thresholds,
    model_playbooks,
    universal_forensic_thresholds,
)
from firm.core.pipeline import derive as D
from firm.core.pipeline.checks import evaluate_checks
from firm.core.pipeline.filing import disposition_notes, walk_filing
from tests.conftest import (
    AS_OF,
    CLEAN_AR_PAGES,
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
    assert fact.locator == "p.1 l.4"              # provenance down to the line (Law 2)
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
    by_number = {d.note_number: d for d in dispositions}

    assert by_number[9].status == "flag"                       # Note 9: Trade Receivables
    assert "receivables_divergent" in by_number[9].rationale
    assert by_number[9].figure_locators == ["p.1 l.3"]


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
