"""Tests for the memory loop: predictions, resolution, Brier scoring."""

from datetime import date

import pytest

from firm.core.monitoring.brier import brier_by_agent, brier_score
from firm.core.monitoring.predictions import Prediction, append_jsonl, read_jsonl
from firm.core.monitoring.resolver import evaluate, resolve


def _pred(pid: str = "p1", prob: float = 0.65, agent: str = "thesis_synthesizer") -> Prediction:
    return Prediction(
        prediction_id=pid, run_id="r1", ticker="ACME", agent=agent, agent_version="1.0.0",
        claim="Gross margin >= 34% by Q4FY27", metric="gross_margin", operator=">=", threshold=0.34,
        resolve_by=date(2027, 5, 31), probability=prob, load_bearing=True, evidence_fact_ids=["f1"],
    )


def test_evaluate_all_operators():
    assert evaluate(">=", 0.34, 0.34) is True
    assert evaluate(">", 0.34, 0.34) is False
    assert evaluate("<=", 0.30, 0.34) is True
    assert evaluate("<", 0.40, 0.34) is False
    assert evaluate("==", 0.34, 0.34) is True


def test_resolve_marks_outcome():
    r = resolve(_pred(), actual=0.36)
    assert r.resolved is True and r.outcome is True
    miss = resolve(_pred(), actual=0.30)
    assert miss.outcome is False


def test_brier_score():
    assert brier_score([(0.8, True), (0.2, False)]) == pytest.approx(0.04)
    with pytest.raises(ValueError):
        brier_score([])


def test_brier_by_agent():
    preds = [
        resolve(_pred("p1", 0.8, "forensic_accountant"), 0.36),   # outcome True,  prob 0.8
        resolve(_pred("p2", 0.2, "forensic_accountant"), 0.30),   # outcome False, prob 0.2
    ]
    scores = brier_by_agent(preds)
    assert scores["forensic_accountant"] == pytest.approx(0.04)


def test_predictions_jsonl_roundtrip(tmp_path):
    path = tmp_path / "predictions.jsonl"
    assert read_jsonl(path) == []           # missing file -> empty
    append_jsonl(path, _pred("p1"))
    append_jsonl(path, _pred("p2"))
    loaded = read_jsonl(path)
    assert [p.prediction_id for p in loaded] == ["p1", "p2"]
