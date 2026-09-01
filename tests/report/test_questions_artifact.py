"""The questions page travels separately from the report (ADR-0076).

ADR-0066 made the questions a computed section of the report and deferred the standalone artifact. The
owner's use for them is a meeting, and a 40-page research note is the wrong thing to be holding while
someone is answering — so the same list is also written as its own page, and `firm questions` prints
it without re-running anything.

Both the page and the section project the same `report.management_questions`, which is the property
that matters: the page a company is asked from cannot drift from the page the firm published.
"""

from __future__ import annotations

import json

from typer.testing import CliRunner

from firm.cli import app
from firm.core.compute.models import BusinessModel
from firm.core.config import load_thresholds, report_policy
from firm.core.pipeline import derive as D
from firm.core.report.assemble import Narration, VerdictDecision, assemble_report
from firm.core.report.render import render_questions, write_report
from firm.schemas.evidence import EvidenceGraph
from firm.schemas.report import Verdict
from tests.conftest import AS_OF, clean_series, seed_store
from tests.report.test_management_questions import FULL_NOTES, _evaluation

runner = CliRunner()


def _report(store, **kw):
    seed_store(store, "ACME", clean_series())
    facts = D.load_company_facts(store, "ACME", AS_OF)
    return assemble_report(
        ticker="ACME", company_name="ACME Limited", as_of=AS_OF, run_id="2026-07-30-run1",
        decision=VerdictDecision(Verdict.FORENSIC_CAUTION, "check_0 fired"),
        derived=D.derive_metrics(facts),
        evaluation=kw.get("evaluation", _evaluation(flagged=1, unavailable=1)),
        models=[BusinessModel.MANUFACTURER], notes=FULL_NOTES, graph=EvidenceGraph(),
        load_bearing_ids=(), narration=Narration(thesis="t", anti_thesis="a", open_questions=("q",)),
        agent_versions={}, forensic=load_thresholds()["forensic"], policy=report_policy())


def test_the_page_carries_exactly_the_reports_questions(store):
    report = _report(store)
    page = render_questions(report)
    for q in report.management_questions:
        assert q.question in page
    assert "Questions for management — ACME Limited" in page
    assert report.disclaimer in page                      # research artifact only, on every page


def test_the_page_is_written_beside_the_report(store, tmp_path):
    report = _report(store)
    md_path, _ = write_report(report, tmp_path, force=True)
    page = md_path.parent / "questions.md"
    assert page.exists()
    assert "High priority" in page.read_text()


def test_no_questions_means_no_page_rather_than_an_empty_one(store, tmp_path):
    report = _report(store, evaluation=_evaluation())      # everything passed, nothing to ask
    assert report.management_questions == []
    md_path, _ = write_report(report, tmp_path, force=True)
    assert not (md_path.parent / "questions.md").exists()


def test_the_command_reads_the_published_artifact_rather_than_recomputing(store, tmp_path):
    report = _report(store)
    write_report(report, tmp_path, force=True)

    result = runner.invoke(app, ["questions", "--ticker", "ACME", "--reports", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "question(s) for management" in result.output
    assert "answerable from:" in result.output or "why:" in result.output
    assert "questions.md" in result.output


def test_an_unresearched_company_is_told_so_not_crashed(tmp_path):
    result = runner.invoke(app, ["questions", "--ticker", "NOBODY", "--reports", str(tmp_path)])
    assert result.exit_code == 1
    assert "run `firm deep-dive` first" in result.output


def test_a_named_run_that_does_not_exist_lists_the_ones_that_do(store, tmp_path):
    write_report(_report(store), tmp_path, force=True)
    result = runner.invoke(app, ["questions", "--ticker", "ACME", "--reports", str(tmp_path),
                                 "--run", "no-such-run"])
    assert result.exit_code == 1
    assert "2026-07-30-run1" in result.output


def test_the_page_and_the_json_cannot_disagree(store, tmp_path):
    """Both project the same field; a second derivation is how the meeting list drifts from the report."""
    report = _report(store)
    md_path, json_path = write_report(report, tmp_path, force=True)
    published = json.loads(json_path.read_text())["management_questions"]
    page = (md_path.parent / "questions.md").read_text()
    assert len(published) == len(report.management_questions)
    for q in published:
        assert q["question"] in page
