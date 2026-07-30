"""Turning a published report's kill criteria into a scoreable prediction ledger (ADR-0023).

The prediction log is only worth keeping if it is honest about what was actually forecast, so most of what
is pinned here is what must NOT go in it: counterfactual rehabilitation criteria, invented probabilities,
agent attribution for numbers code authored, and duplicate rows from a replayed run.
"""

from __future__ import annotations

from datetime import date

from firm.core.monitoring.predictions import (
    log_report_predictions,
    predictions_from_report,
    read_jsonl,
)

# ------------------------------------------------------------------------------------------------
# Report -> prediction ledger (Phase 5, ADR-0023)


def _report_with_criteria(**kw):
    from firm.schemas._base import Confidence, Grade
    from firm.schemas.report import Criterion, ResearchReport, Verdict

    defaults = dict(
        ticker="ABC", company_name="ABC Ltd", as_of=date(2026, 7, 30), run_id="run-1",
        verdict=Verdict.COMPOUNDER,
        confidence=Confidence(value=0.62, evidence_count=9, lowest_grade_relied_on=Grade.B,
                              rationale="9 grade-B facts"),
        kill_criteria=[
            Criterion(statement="CFO/PAT stays above 1.14", metric="cum_cfo_pat", operator=">=",
                      threshold=1.14, resolve_by=date(2027, 10, 27), load_bearing=True),
            Criterion(statement="ROIC stays above 9.2%", metric="roic_latest", operator=">=",
                      threshold=0.092, resolve_by=date(2027, 10, 27)),
        ],
        rehabilitation_criteria=[
            Criterion(statement="the company discloses its cash balance", metric="checks_unavailable",
                      operator="<=", threshold=0.0, resolve_by=date(2027, 10, 27), load_bearing=True),
        ],
    )
    defaults.update(kw)
    return ResearchReport(**defaults)


def test_only_kill_criteria_become_predictions():
    """A rehabilitation criterion is a counterfactual the firm expects NOT to happen.

    Logging it would fill the Brier record with events nobody forecast and make the calibration score
    meaningless — so it stays in the report and out of the ledger.
    """
    preds = predictions_from_report(_report_with_criteria())
    assert [p.metric for p in preds] == ["cum_cfo_pat", "roic_latest"]
    assert "checks_unavailable" not in {p.metric for p in preds}


def test_probability_is_the_reports_own_confidence_not_an_invented_number():
    """Law 1 forbids an authored number, and a made-up per-criterion probability would be worse.

    Confidence already states how much the firm believes the evidence under these claims, so a shallow
    report is scored gently and a confident one is scored hard.
    """
    preds = predictions_from_report(_report_with_criteria())
    assert all(p.probability == 0.62 for p in preds)


def test_the_load_bearing_flag_and_the_operator_survive_the_round_trip():
    preds = {p.metric: p for p in predictions_from_report(_report_with_criteria())}
    assert preds["cum_cfo_pat"].load_bearing is True
    assert preds["roic_latest"].load_bearing is False
    assert preds["cum_cfo_pat"].operator == ">=" and preds["cum_cfo_pat"].threshold == 1.14
    assert preds["cum_cfo_pat"].resolve_by == date(2027, 10, 27)


def test_criteria_are_attributed_to_code_not_to_an_agent():
    """These numbers are computed (ADR-0021 decision 4). Crediting an agent would be a lie the
    calibration record then compounds into a per-agent Brier score."""
    assert {p.agent for p in predictions_from_report(_report_with_criteria())} == {
        "core.report.criteria"}


def test_logging_is_idempotent_so_a_replayed_run_appends_nothing(tmp_path):
    """Law 5: the same inputs produce the same run, and the ledger must record a forecast ONCE.

    Otherwise the ledger measures how often the pipeline was re-run rather than what was predicted.
    """
    path = tmp_path / "memory" / "predictions.jsonl"
    report = _report_with_criteria()

    first = log_report_predictions(report, path)
    assert len(first) == 2
    assert len(read_jsonl(path)) == 2

    again = log_report_predictions(report, path)
    assert again == []
    assert len(read_jsonl(path)) == 2


def test_a_different_run_of_the_same_ticker_logs_separately(tmp_path):
    path = tmp_path / "predictions.jsonl"
    log_report_predictions(_report_with_criteria(), path)
    log_report_predictions(_report_with_criteria(run_id="run-2"), path)

    ids = {p.prediction_id for p in read_jsonl(path)}
    assert ids == {"run-1:cum_cfo_pat", "run-1:roic_latest",
                   "run-2:cum_cfo_pat", "run-2:roic_latest"}


def test_the_ledger_directory_is_created_on_demand(tmp_path):
    path = tmp_path / "does" / "not" / "exist" / "predictions.jsonl"
    assert log_report_predictions(_report_with_criteria(), path)
    assert path.exists()
