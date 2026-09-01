"""`firm evolve` — the command a person reads before changing a prompt (ADR-0077)."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from firm.cli import app
from firm.core.monitoring.predictions import Prediction, append_jsonl

runner = CliRunner()


def _memory(tmp_path, lessons: list[dict], predictions: list[Prediction] | None = None):
    root = tmp_path / "memory"
    root.mkdir()
    (root / "lessons.jsonl").write_text("\n".join(json.dumps(le) for le in lessons) + "\n")
    for p in predictions or []:
        append_jsonl(root / "predictions.jsonl", p)
    return root


def _lesson(**kw) -> dict:
    base = {"date": "2026-08-31", "run_id": "r1", "ticker": "ACME", "lesson": "base rate was wrong",
            "action": "State the sector base rate first.", "category": "wrong_base_rate",
            "agent": "business_analyst"}
    return {**base, **kw}


def test_a_ready_cluster_prints_the_block_to_review(tmp_path):
    memory = _memory(tmp_path, [_lesson(run_id=f"r{i}") for i in range(3)])
    result = runner.invoke(app, ["evolve", "--memory", str(memory)])

    assert result.exit_code == 0, result.output
    assert "1 ready to propose" in result.output
    assert "[READY] business_analyst — wrong_base_rate" in result.output
    assert "agents/business_analyst.md" in result.output
    assert "State the sector base rate first." in result.output
    # It proposes; it must never claim to have applied anything.
    assert "apply by hand" in result.output


def test_a_forming_cluster_is_shown_without_a_block(tmp_path):
    memory = _memory(tmp_path, [_lesson(run_id=f"r{i}") for i in range(2)])
    result = runner.invoke(app, ["evolve", "--memory", str(memory)])
    assert "0 ready to propose" in result.output
    assert "[forming] business_analyst" in result.output
    assert "agents/business_analyst.md" not in result.output


def test_unclassified_lessons_are_grouped_by_reason_not_listed_one_by_one(tmp_path):
    memory = _memory(tmp_path, [_lesson(run_id=f"r{i}", category="") for i in range(18)])
    result = runner.invoke(app, ["evolve", "--memory", str(memory)])
    assert "18 x no `category`" in result.output
    assert "will not guess one" in result.output


def test_the_agent_filter_narrows_the_proposals(tmp_path):
    memory = _memory(tmp_path,
                     [_lesson(run_id=f"a{i}") for i in range(3)]
                     + [_lesson(run_id=f"f{i}", agent="forensic_accountant") for i in range(3)])
    result = runner.invoke(app, ["evolve", "--memory", str(memory), "--agent", "forensic_accountant"])
    assert "forensic_accountant" in result.output
    assert "[READY] business_analyst" not in result.output


def test_calibration_by_version_is_printed_when_predictions_have_resolved(tmp_path):
    preds = [Prediction(prediction_id=f"p{i}", run_id="r", ticker="ACME", agent="report",
                        agent_version="1.0.0", claim="c", metric="m", operator=">=", threshold=1.0,
                        resolve_by="2026-07-01", probability=0.8, resolved=True, outcome=True)
             for i in range(3)]
    memory = _memory(tmp_path, [_lesson()], preds)
    result = runner.invoke(app, ["evolve", "--memory", str(memory)])
    assert "Calibration by agent version" in result.output
    assert "report@1.0.0" in result.output and "3 resolved" in result.output


def test_an_empty_ledger_is_reported_rather_than_crashed(tmp_path):
    root = tmp_path / "memory"
    root.mkdir()
    result = runner.invoke(app, ["evolve", "--memory", str(root)])
    assert result.exit_code == 1
    assert "nothing has been learned to act on" in result.output
