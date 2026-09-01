"""`firm resolve` closes the memory loop (ADR-0073).

`resolve_due` and `brier_score` have existed and been tested since Phase 0, and nothing ever called
them: the ledger had inputs and no loop, so the firm logged forecasts and never learned whether it was
right. Predictions only enter the ledger from PUBLISHED reports, which is what makes scoring them the
only measure of this firm's calibration that is not self-assessment.

The property that matters most is the one shared with research: resolution is point-in-time. An actual
recomputed from a filing published after the resolution date would score the firm against information
it could not have had, which flatters every backtest ever run.
"""

from __future__ import annotations

import json
from datetime import date

from typer.testing import CliRunner

from firm.cli import app
from firm.core.monitoring.predictions import Prediction, append_jsonl, read_jsonl
from tests.conftest import AS_OF, clean_series, seed_store

runner = CliRunner()


def _prediction(**kw) -> Prediction:
    base = {
        "prediction_id": "p1", "run_id": "r1", "ticker": "ACME", "agent": "report",
        "agent_version": "1.0.0", "claim": "cash conversion holds",
        "metric": "cfo_pat_latest", "operator": ">=", "threshold": 0.5,
        "resolve_by": date(2026, 7, 1), "probability": 0.8, "load_bearing": True,
    }
    return Prediction(**{**base, **kw})


def _ledger(tmp_path, *predictions):
    memory = tmp_path / "memory"
    memory.mkdir()
    for p in predictions:
        append_jsonl(memory / "predictions.jsonl", p)
    return memory


def _db(tmp_path, store):
    """The CLI opens its own FactStore by path, so the fixture store must be on disk."""
    from firm.core.facts.store import FactStore

    path = tmp_path / "firm.db"
    disk = FactStore(str(path))
    seed_store(disk, "ACME", clean_series())
    disk.close()
    return str(path)


def test_a_due_prediction_is_scored_against_what_the_filings_showed(tmp_path, store):
    memory = _ledger(tmp_path, _prediction())
    result = runner.invoke(app, ["resolve", "--ticker", "ACME", "--as-of", AS_OF.isoformat(),
                                 "--db", _db(tmp_path, store), "--memory", str(memory)])

    assert result.exit_code == 0, result.output
    assert "1 prediction(s) due" in result.output
    assert "HELD" in result.output or "BROKE" in result.output
    assert "Brier score" in result.output

    # the ledger is rewritten with the outcome, so a second run does not re-resolve it
    rewritten = read_jsonl(memory / "predictions.jsonl")
    assert rewritten[0].resolved is True and rewritten[0].outcome is not None


def test_a_prediction_not_yet_due_is_left_alone(tmp_path, store):
    memory = _ledger(tmp_path, _prediction(resolve_by=date(2030, 1, 1)))
    result = runner.invoke(app, ["resolve", "--ticker", "ACME", "--as-of", AS_OF.isoformat(),
                                 "--db", _db(tmp_path, store), "--memory", str(memory)])

    assert result.exit_code == 0
    assert "no prediction is due" in result.output
    assert read_jsonl(memory / "predictions.jsonl")[0].resolved is None


def test_a_confident_prediction_that_broke_is_named_as_a_lesson_candidate(tmp_path, store):
    """A hedged miss is ordinary; a miss the report was confident about is where a lesson lives."""
    memory = _ledger(tmp_path, _prediction(threshold=99.0, probability=0.9))
    result = runner.invoke(app, ["resolve", "--ticker", "ACME", "--as-of", AS_OF.isoformat(),
                                 "--db", _db(tmp_path, store), "--memory", str(memory)])

    assert result.exit_code == 0, result.output
    assert "BROKE" in result.output
    assert "LESSON CANDIDATE" in result.output


def test_an_empty_ledger_is_reported_rather_than_crashed(tmp_path, store):
    result = runner.invoke(app, ["resolve", "--ticker", "ACME", "--as-of", AS_OF.isoformat(),
                                 "--db", _db(tmp_path, store), "--memory", str(tmp_path / "nowhere")])
    assert result.exit_code == 1
    assert "nothing has been published to resolve" in result.output


def test_the_ledger_json_stays_readable_after_a_rewrite(tmp_path, store):
    """`resolve_due` rewrites the WHOLE file; a malformed line would silently lose the record."""
    memory = _ledger(tmp_path, _prediction(), _prediction(prediction_id="p2", ticker="OTHER"))
    runner.invoke(app, ["resolve", "--ticker", "ACME", "--as-of", AS_OF.isoformat(),
                        "--db", _db(tmp_path, store), "--memory", str(memory)])

    lines = (memory / "predictions.jsonl").read_text().strip().splitlines()
    assert len(lines) == 2
    for line in lines:
        json.loads(line)
    # the other company's row passed through untouched
    other = [p for p in read_jsonl(memory / "predictions.jsonl") if p.ticker == "OTHER"]
    assert other and other[0].resolved is None
