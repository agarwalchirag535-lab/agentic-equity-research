"""Prompt evolution: proposals a person approves, and a way to tell whether one worked (ADR-0077).

`core/evolution/` held nothing but `__init__.py` from Phase 0 until now, so no prompt in this repo has
ever been revised on evidence — SPEC §7.3 existed as an intention.

Three properties are defended here, and they are the reasons this module is allowed to exist at all:

* **It proposes; it never applies.** A system that rewrites its own instructions from its own failure
  log, unattended, optimises for a quiet log rather than for being right.
* **It never invents a root cause.** Classifying why a forecast missed is a human judgment. A lesson
  without one is reported as needing it — the 18 real lessons in this repo are exactly that case.
* **It never invents guidance.** A proposed patch is assembled from what lesson authors wrote,
  verbatim and attributed. A cluster with no stated action produces a proposal that says so.
"""

from __future__ import annotations

from firm.core.config import load_thresholds
from firm.core.evolution.calibration import brier_by_agent_version, compare_versions
from firm.core.evolution.lessons import ROOT_CAUSES, Lesson, read_lessons
from firm.core.evolution.propose import propose_changes
from firm.core.monitoring.predictions import Prediction

POLICY = load_thresholds()["evolution"]
MIN_CLUSTER = int(POLICY["min_lessons_per_cluster"])


def _lesson(**kw) -> Lesson:
    base = {
        "date": "2026-08-31", "run_id": "r1", "ticker": "ACME", "lesson": "the base rate was wrong",
        "action": "State the sector base rate before asserting a growth path.",
        "category": "wrong_base_rate", "agent": "business_analyst",
    }
    return Lesson(**{**base, **kw})


def _prediction(**kw) -> Prediction:
    base = {
        "prediction_id": "p", "run_id": "r", "ticker": "ACME", "agent": "report",
        "agent_version": "1.0.0", "claim": "c", "metric": "m", "operator": ">=", "threshold": 1.0,
        "resolve_by": "2026-07-01", "probability": 0.8, "resolved": True, "outcome": True,
    }
    return Prediction(**{**base, **kw})


# ---- clustering ------------------------------------------------------------------------------------
def test_three_lessons_on_one_root_cause_propose_a_change():
    report = propose_changes([_lesson(run_id=f"r{i}") for i in range(MIN_CLUSTER)],
                             min_cluster=MIN_CLUSTER)
    assert len(report.ready) == 1
    proposal = report.ready[0]
    assert proposal.agent == "business_analyst" and proposal.category == "wrong_base_rate"
    assert proposal.size == MIN_CLUSTER


def test_a_cluster_below_the_floor_is_reported_but_not_proposed():
    """One miss is a sample of one, and a card patched every bad quarter overfits to it."""
    report = propose_changes([_lesson(run_id=f"r{i}") for i in range(MIN_CLUSTER - 1)],
                             min_cluster=MIN_CLUSTER)
    assert report.ready == ()
    assert len(report.proposals) == 1 and report.proposals[0].ready is False


def test_lessons_cluster_per_agent_not_across_the_firm():
    """A base-rate failure in the business analyst is not evidence about the forensic accountant."""
    lessons = ([_lesson(agent="business_analyst", run_id=f"a{i}") for i in range(MIN_CLUSTER)]
               + [_lesson(agent="forensic_accountant", run_id="f1")])
    report = propose_changes(lessons, min_cluster=MIN_CLUSTER)
    assert {p.agent for p in report.ready} == {"business_analyst"}
    assert any(p.agent == "forensic_accountant" and not p.ready for p in report.proposals)


def test_the_largest_cluster_is_presented_first():
    lessons = ([_lesson(category="wrong_base_rate", run_id=f"w{i}") for i in range(4)]
               + [_lesson(category="macro_shock", run_id=f"m{i}") for i in range(3)])
    report = propose_changes(lessons, min_cluster=MIN_CLUSTER)
    assert [p.category for p in report.proposals] == ["wrong_base_rate", "macro_shock"]


# ---- what it refuses to do -------------------------------------------------------------------------
def test_an_unclassified_lesson_is_surfaced_never_bucketed():
    report = propose_changes([_lesson(category="")], min_cluster=MIN_CLUSTER)
    assert report.proposals == ()
    assert len(report.unclassified) == 1
    assert "root cause nobody has named" in report.unclassified[0][1]


def test_a_category_outside_the_taxonomy_is_rejected_and_the_taxonomy_named():
    report = propose_changes([_lesson(category="vibes")], min_cluster=MIN_CLUSTER)
    reason = report.unclassified[0][1]
    assert "outside SPEC" in reason and "wrong_base_rate" in reason


def test_a_lesson_with_no_agent_cannot_target_a_card():
    report = propose_changes([_lesson(agent="")], min_cluster=MIN_CLUSTER)
    assert "needs a card to change" in report.unclassified[0][1]


def test_the_repos_real_lessons_are_all_unclassified_and_say_so():
    """The 18 lessons predate this schema. Auto-assigning them a root cause would be the module
    inventing the one judgment it exists to defer."""
    lessons = read_lessons("memory/lessons.jsonl")
    report = propose_changes(lessons, min_cluster=MIN_CLUSTER)
    assert lessons and report.ready == ()
    assert len(report.unclassified) == len(lessons)


# ---- the patch -------------------------------------------------------------------------------------
def test_the_patch_quotes_the_authors_actions_verbatim_with_attribution():
    lessons = [_lesson(run_id=f"r{i}", action=f"Do the thing numbered {i}.") for i in range(3)]
    patch = propose_changes(lessons, min_cluster=MIN_CLUSTER).ready[0].patch
    for i in range(3):
        assert f"Do the thing numbered {i}." in patch
    assert "ACME" in patch and "2026-08-31" in patch      # attribution travels with the line
    assert "wrong_base_rate" in patch


def test_a_cluster_with_no_stated_action_proposes_nothing_rather_than_composing_guidance():
    lessons = [_lesson(run_id=f"r{i}", action="") for i in range(MIN_CLUSTER)]
    patch = propose_changes(lessons, min_cluster=MIN_CLUSTER).ready[0].patch
    assert "no lesson states an action" in patch
    assert "telling itself what to think" in patch


def test_the_taxonomy_is_the_spec_one():
    assert "wrong_base_rate" in ROOT_CAUSES and "overconfident_prior" in ROOT_CAUSES
    assert len(ROOT_CAUSES) == 9


# ---- did the change work? --------------------------------------------------------------------------
def test_brier_is_scored_per_agent_version():
    preds = ([_prediction(prediction_id=f"a{i}", agent_version="1.0.0", probability=0.9,
                          outcome=True) for i in range(3)]
             + [_prediction(prediction_id=f"b{i}", agent_version="1.1.0", probability=0.6,
                            outcome=True) for i in range(2)])
    scores = {(s.agent, s.version): s for s in brier_by_agent_version(preds)}
    assert scores[("report", "1.0.0")].resolved == 3
    assert scores[("report", "1.1.0")].resolved == 2
    assert scores[("report", "1.0.0")].brier < scores[("report", "1.1.0")].brier


def test_unresolved_predictions_are_not_scored():
    assert brier_by_agent_version([_prediction(resolved=None, outcome=None)]) == []


def test_a_thin_sample_refuses_to_declare_an_improvement():
    """Brier over two predictions is noise wearing a decimal point."""
    preds = ([_prediction(prediction_id=f"a{i}", agent_version="1.0.0") for i in range(2)]
             + [_prediction(prediction_id=f"b{i}", agent_version="1.1.0") for i in range(2)])
    comparison = compare_versions(brier_by_agent_version(preds), min_resolved=5)[0]
    assert comparison.improved is None
    assert "not comparable" in comparison.verdict


def test_a_version_bump_that_forecast_better_is_credited_and_one_that_did_not_is_not():
    better = ([_prediction(prediction_id=f"a{i}", agent_version="1.0.0", probability=0.5,
                           outcome=True) for i in range(5)]
              + [_prediction(prediction_id=f"b{i}", agent_version="1.1.0", probability=0.95,
                             outcome=True) for i in range(5)])
    comparison = compare_versions(brier_by_agent_version(better), min_resolved=5)[0]
    assert comparison.improved is True and "earned itself" in comparison.verdict

    worse = ([_prediction(prediction_id=f"a{i}", agent_version="1.0.0", probability=0.95,
                          outcome=True) for i in range(5)]
             + [_prediction(prediction_id=f"b{i}", agent_version="1.1.0", probability=0.5,
                            outcome=True) for i in range(5)])
    regressed = compare_versions(brier_by_agent_version(worse), min_resolved=5)[0]
    assert regressed.improved is False and "older card forecast better" in regressed.verdict
