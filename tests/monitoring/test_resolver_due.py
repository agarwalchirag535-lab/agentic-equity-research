"""`resolve_due` — the first closing of the memory loop (SPEC §7.2), built for the PC Jeweller
resolution. Point-in-time applies to scoring exactly as to research."""

from __future__ import annotations

from datetime import date

import pytest

from firm.core.facts.store import Document, FactStore
from firm.core.monitoring.predictions import Prediction, append_jsonl, read_jsonl
from firm.core.monitoring.resolver import resolve_due


def _seed(store: FactStore, ticker: str, cfo: float, pat: float, published: date) -> None:
    doc = f"AR-{published.year}"
    store.add_document(Document(doc_id=doc, source_url="u", sha256="", published_at=published,
                                fetched_at=published, grade="A", extractor_version="t@1"))
    fy = f"FY{published.year % 100:02d}"
    store.add_fact(fact_id=f"{doc}:cf:{fy}", doc_id=doc, ticker=ticker,
                   metric="cashflow:Cash from Operating Activity", period=fy, value=cfo,
                   unit="INR_cr", locator="p.1")
    store.add_fact(fact_id=f"{doc}:np:{fy}", doc_id=doc, ticker=ticker,
                   metric="pnl:Net Profit", period=fy, value=pat, unit="INR_cr", locator="p.1")
    store.add_fact(fact_id=f"{doc}:sales:{fy}", doc_id=doc, ticker=ticker,
                   metric="pnl:Sales", period=fy, value=pat * 10, unit="INR_cr", locator="p.1")


def _prediction(metric: str, op: str, threshold: float, resolve_by: date) -> Prediction:
    return Prediction(
        prediction_id=f"run:{metric}", run_id="run", ticker="T", agent="core.report.criteria",
        agent_version="1.0.0", claim="c", metric=metric, operator=op, threshold=threshold,
        resolve_by=resolve_by, probability=0.4, load_bearing=True)


def test_a_due_prediction_resolves_against_the_point_in_time_metric(tmp_path):
    store = FactStore(":memory:")
    _seed(store, "T", cfo=10.0, pat=100.0, published=date(2023, 6, 1))
    _seed(store, "T", cfo=20.0, pat=100.0, published=date(2024, 6, 1))
    ledger = tmp_path / "predictions.jsonl"
    append_jsonl(ledger, _prediction("cfo_pat_latest", ">=", 0.7, date(2024, 10, 27)))

    out = resolve_due(store, ledger, "T", date(2024, 11, 1), start_year=2023)
    assert len(out) == 1 and out[0].outcome is False and out[0].actual == 0.2
    back = read_jsonl(ledger)
    assert back[0].resolved is True and back[0].outcome is False
    # idempotent: a second pass finds nothing due
    assert resolve_due(store, ledger, "T", date(2024, 11, 1), start_year=2023) == []


def test_an_undue_or_foreign_prediction_is_left_alone(tmp_path):
    store = FactStore(":memory:")
    _seed(store, "T", cfo=90.0, pat=100.0, published=date(2024, 6, 1))
    ledger = tmp_path / "predictions.jsonl"
    append_jsonl(ledger, _prediction("cfo_pat_latest", ">=", 0.7, date(2025, 10, 27)))  # not yet due
    other = _prediction("cfo_pat_latest", ">=", 0.7, date(2024, 1, 1))
    append_jsonl(ledger, other.model_copy(update={"ticker": "OTHER", "prediction_id": "o:1"}))
    assert resolve_due(store, ledger, "T", date(2024, 11, 1), start_year=2023) == []
    assert all(p.resolved is None for p in read_jsonl(ledger))


def test_an_underivable_metric_is_reported_not_skipped(tmp_path):
    store = FactStore(":memory:")
    _seed(store, "T", cfo=90.0, pat=100.0, published=date(2024, 6, 1))
    ledger = tmp_path / "predictions.jsonl"
    append_jsonl(ledger, _prediction("incremental_roic_3y", ">=", 0.15, date(2024, 10, 27)))
    out = resolve_due(store, ledger, "T", date(2024, 11, 1), start_year=2023)
    assert len(out) == 1 and out[0].outcome is None and "not derivable" in out[0].reason
    assert read_jsonl(ledger)[0].resolved is None    # stays open, visibly


def test_resolution_respects_point_in_time(tmp_path):
    """A filing published after the resolution date must not answer the prediction."""
    store = FactStore(":memory:")
    _seed(store, "T", cfo=10.0, pat=100.0, published=date(2023, 6, 1))
    _seed(store, "T", cfo=95.0, pat=100.0, published=date(2024, 12, 15))   # the future
    ledger = tmp_path / "predictions.jsonl"
    append_jsonl(ledger, _prediction("cfo_pat_latest", ">=", 0.7, date(2024, 10, 27)))
    out = resolve_due(store, ledger, "T", date(2024, 11, 1), start_year=2023)
    # as-of 1 Nov 2024 only the 2023 filing exists: latest CFO/PAT = 0.1 -> fails
    assert out[0].actual == 0.1 and out[0].outcome is False


def test_criterion_probability_is_per_criterion_not_broadcast():
    """Lesson 2 (memory/lessons.jsonl): a criterion the metric already violates must not carry the same
    P(holds) as one it comfortably satisfies. P = c*prior + (1-c)/2, prior flipped by today's state."""
    from firm.core.monitoring.predictions import predictions_from_report
    from firm.schemas._base import Confidence, Grade
    from firm.schemas.report import Criterion, ResearchReport, Verdict

    report = ResearchReport(
        ticker="T", company_name="T", as_of=date(2017, 12, 31), run_id="r1",
        verdict=Verdict.FORENSIC_CAUTION,
        confidence=Confidence(value=0.38, evidence_count=9, lowest_grade_relied_on=Grade.A,
                              rationale="test"),
        computed_facts={"cum_cfo_pat": 0.24, "accrual_ratio_latest": -0.051},
        kill_criteria=[
            Criterion(statement="s", metric="cum_cfo_pat", operator=">=", threshold=0.7,
                      resolve_by=date(2018, 10, 27), load_bearing=True),          # violated today
            Criterion(statement="s", metric="accrual_ratio_latest", operator="<=", threshold=0.1,
                      resolve_by=date(2018, 10, 27)),                             # satisfied today
            Criterion(statement="s", metric="not_derived", operator=">=", threshold=1.0,
                      resolve_by=date(2018, 10, 27)),                             # unknown today
        ],
    )
    preds = {p.metric: p for p in predictions_from_report(report, persistence=0.8)}
    assert preds["cum_cfo_pat"].probability == pytest.approx(0.38 * 0.2 + 0.62 / 2)          # 0.386
    assert preds["accrual_ratio_latest"].probability == pytest.approx(0.38 * 0.8 + 0.62 / 2)  # 0.614
    assert preds["not_derived"].probability == pytest.approx(0.38)   # cannot assess -> bare confidence
    assert preds["cum_cfo_pat"].probability < preds["accrual_ratio_latest"].probability
    # the PCJ outcomes (broken, held) under these probabilities score better than the broadcast rule
    outcomes = {"cum_cfo_pat": False, "accrual_ratio_latest": True}
    new = sum((preds[m].probability - (1.0 if o else 0.0)) ** 2 for m, o in outcomes.items()) / 2
    old = sum((0.38 - (1.0 if o else 0.0)) ** 2 for o in outcomes.values()) / 2
    assert new < old
