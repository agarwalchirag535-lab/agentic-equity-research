"""Tests for the verdict ladder and report assembly (ADR-0021).

The verdict is the single most consequential thing this system emits, so it is chosen by code and tested
directly here: given a screen result, a checklist, a notes review and a feasibility result, exactly one
verdict must follow, and the ordering between them must not drift.
"""

from __future__ import annotations

import pytest

from firm.core.compute.models import BusinessModel
from firm.core.compute.multibagger import GateVerdict, feasibility_gate
from firm.core.compute.quality import (
    Flag,
    ForensicMetrics,
    ForensicScreenResult,
    ForensicVerdict,
    Severity,
)
from firm.core.config import load_thresholds, report_policy
from firm.core.pipeline import derive as D
from firm.core.pipeline.checks import CheckEvaluation
from firm.core.report.assemble import (
    Narration,
    NotesReview,
    VerdictDecision,
    assemble_report,
    build_checklist,
    choose_verdict,
    report_confidence,
)
from firm.schemas._base import Citation, Grade
from firm.schemas.evidence import Evidence, EvidenceGraph, SourceClass
from firm.schemas.report import CheckOutcome, CheckRecord, GapKind, Verdict
from tests.conftest import AS_OF, clean_series, seed_store

POLICY = report_policy()
THRESHOLDS = load_thresholds()
MIN_HISTORY = int(THRESHOLDS["screen"]["min_history_years"])

CLEAN_SCREEN = ForensicScreenResult(ForensicVerdict.PASS, False, [])
HARD_FAIL_SCREEN = ForensicScreenResult(ForensicVerdict.HARD_FAIL, True, [
    Flag("cumulative_cfo_pat_low", Severity.SEVERE, "ΣCFO/ΣPAT 0.21 < 0.70")])
MEDIUM_ONLY_SCREEN = ForensicScreenResult(ForensicVerdict.REVIEW, False, [
    Flag("inventory_divergent", Severity.MEDIUM, "inventory outrunning revenue")])

FULL_NOTES = NotesReview(coverage=1.0, substantive_share=0.6, notes_total=10, scanned=True)
NO_NOTES = NotesReview()
SELF_FUNDED = feasibility_gate(
    g_required=0.258, roic=0.40, self_fund_ceiling=1.0, high_quality_ceiling=0.6,
    debt_capacity_available=True, thesis_allows_dilution=False)
UNAFFORDABLE = feasibility_gate(
    g_required=0.258, roic=0.15, self_fund_ceiling=1.0, high_quality_ceiling=0.6,
    debt_capacity_available=True, thesis_allows_dilution=False)


def _evaluation(unavailable: int = 0, total: int = 10, flagged: int = 0,
                gap: GapKind = GapKind.DISCLOSURE) -> CheckEvaluation:
    """`gap` decides WHOSE the unavailability is (ADR-0051). DISCLOSURE by default because that is the
    case these ladder tests are about; pass CAPABILITY to build the run whose gaps are the firm's own."""
    records = []
    names = [f"check_{i}" for i in range(total)]
    for i, name in enumerate(names):
        if i < unavailable:
            records.append(CheckRecord(name=name, outcome=CheckOutcome.UNAVAILABLE, reason="absent",
                                       gap=gap))
        elif i < unavailable + flagged:
            records.append(CheckRecord(name=name, outcome=CheckOutcome.FLAG, detail="fired"))
        else:
            records.append(CheckRecord(name=name, outcome=CheckOutcome.PASS, detail="ok"))
    return CheckEvaluation(tuple(records), ForensicMetrics(), tuple(names))


def _choose(screen=CLEAN_SCREEN, evaluation=None, notes=FULL_NOTES, feasibility=SELF_FUNDED,
            years=10, veto=False) -> VerdictDecision:
    return choose_verdict(
        screen, evaluation or _evaluation(), notes, feasibility,
        policy=POLICY, history_years=years, min_history_years=MIN_HISTORY, forensic_veto=veto)


# ---- the ladder ----------------------------------------------------------------------------------
def test_clean_self_funding_company_with_full_notes_is_a_compounder():
    assert _choose().verdict is Verdict.COMPOUNDER


def test_a_severe_flag_outranks_everything_else():
    decision = _choose(screen=HARD_FAIL_SCREEN, notes=NO_NOTES, feasibility=UNAFFORDABLE)
    assert decision.verdict is Verdict.FORENSIC_CAUTION
    assert "cumulative_cfo_pat_low" in decision.rationale


def test_a_medium_flag_alone_does_not_trigger_a_caution():
    """Severity policy lives in config; a MEDIUM tell stays visible in the checklist without headlining."""
    assert _choose(screen=MEDIUM_ONLY_SCREEN).verdict is Verdict.COMPOUNDER


def test_the_forensic_agents_veto_can_only_make_the_verdict_worse():
    assert _choose(veto=True).verdict is Verdict.FORENSIC_CAUTION
    # ... and it cannot make a bad verdict good: there is no path from veto to COMPOUNDER
    assert _choose(screen=HARD_FAIL_SCREEN, veto=False).verdict is Verdict.FORENSIC_CAUTION


def test_too_much_of_the_playbook_unevaluable_is_insufficient_disclosure():
    decision = _choose(evaluation=_evaluation(unavailable=5, total=10))
    assert decision.verdict is Verdict.INSUFFICIENT_DISCLOSURE
    assert "50%" in decision.rationale


def test_incomplete_note_coverage_is_insufficient_disclosure():
    notes = NotesReview(coverage=0.7, undispositioned=("30",), substantive_share=0.7, notes_total=10,
                        scanned=True)
    assert _choose(notes=notes).verdict is Verdict.INSUFFICIENT_DISCLOSURE


def test_notes_we_never_opened_are_not_notes_the_company_withheld():
    """ADR-0051. With no filing walked, `scanned` is False and this rung has nothing to say about the
    company — coverage of 0% is a statement about the firm's reach, not about their disclosure."""
    never_looked = NotesReview(coverage=0.0, substantive_share=0.0, notes_total=0, scanned=False)
    assert _choose(notes=never_looked).verdict is not Verdict.INSUFFICIENT_DISCLOSURE


def test_our_own_missing_capability_can_never_be_published_as_their_opacity():
    """The prohibited failure, caught on a real company (ADR-0051): CreditAccess Grameen discloses its
    asset quality in full, and the firm was about to publish INSUFFICIENT_DISCLOSURE over notes it does
    not read — reasoning that "the inputs are public by law, so the gap is the finding"."""
    ours = _evaluation(unavailable=9, total=10, gap=GapKind.CAPABILITY)
    assert ours.unavailable_share == pytest.approx(0.9)       # we know much less
    assert ours.capability_gap_share == pytest.approx(0.9)
    assert ours.disclosure_gap_share == 0.0                   # and the company is accused of nothing
    assert _choose(evaluation=ours).verdict is not Verdict.INSUFFICIENT_DISCLOSURE

    theirs = _evaluation(unavailable=9, total=10, gap=GapKind.DISCLOSURE)
    decision = _choose(evaluation=theirs)
    assert decision.verdict is Verdict.INSUFFICIENT_DISCLOSURE
    assert "looked for and not disclosed" in decision.rationale


def test_full_coverage_that_read_nothing_does_not_buy_a_thesis():
    """The loophole this closes: disposition every note 'unknown' and coverage hits 100%."""
    theatre = NotesReview(coverage=1.0, substantive_share=0.1, notes_total=10, scanned=True)
    decision = _choose(notes=theatre)
    assert decision.verdict is Verdict.INSUFFICIENT_DISCLOSURE
    assert "coverage without reading" in decision.rationale


def test_a_clean_company_that_cannot_self_fund_the_target_is_withheld_on_price():
    decision = _choose(feasibility=UNAFFORDABLE)
    assert decision.verdict is Verdict.RETURN_HURDLE_NOT_CLEARED
    assert GateVerdict.NEEDS_EXTERNAL_FUNDING.value in decision.rationale


def test_no_feasibility_result_is_watch_not_a_guess():
    assert _choose(feasibility=None).verdict is Verdict.WATCH


def test_short_history_is_watch():
    decision = _choose(years=3)
    assert decision.verdict is Verdict.WATCH and "3y of history" in decision.rationale


# ---- confidence ----------------------------------------------------------------------------------
def test_confidence_is_capped_by_the_weakest_grade_relied_on():
    def graph_with(grade: Grade) -> EvidenceGraph:
        g = EvidenceGraph()
        g.evidence["ev:1"] = Evidence(
            id="ev:1", summary="s", source_class=SourceClass.BINDING_FILING,
            citation=Citation(fact_id="f1", doc_id="d", locator="l", published_at=AS_OF,
                              extractor_version="v", grade=grade))
        return g

    strong = report_confidence(graph_with(Grade.A), _evaluation(), FULL_NOTES)
    weak = report_confidence(graph_with(Grade.D), _evaluation(), FULL_NOTES)
    assert strong.value > weak.value and weak.value <= 0.40
    assert weak.lowest_grade_relied_on is Grade.D
    assert "weakest grade relied on is D" in weak.rationale


def test_confidence_falls_when_less_of_the_playbook_could_be_evaluated():
    graph = EvidenceGraph()
    graph.evidence["ev:1"] = Evidence(
        id="ev:1", summary="s", source_class=SourceClass.BINDING_FILING,
        citation=Citation(fact_id="f1", doc_id="d", locator="l", published_at=AS_OF,
                          extractor_version="v", grade=Grade.A))
    full = report_confidence(graph, _evaluation(), FULL_NOTES)
    partial = report_confidence(graph, _evaluation(unavailable=5), FULL_NOTES)
    assert partial.value < full.value


# ---- assembly ------------------------------------------------------------------------------------
def test_assembly_attaches_criteria_by_verdict_class_and_states_the_rationale(store):
    seed_store(store, "ACME", clean_series())
    derived = D.derive_metrics(D.load_company_facts(store, "ACME", AS_OF))
    evaluation = _evaluation()
    decision = VerdictDecision(Verdict.COMPOUNDER, "clean on everything that could run")

    report = assemble_report(
        ticker="ACME", company_name="ACME Limited", as_of=AS_OF, run_id="run-1", decision=decision,
        derived=derived, evaluation=evaluation, models=[BusinessModel.MANUFACTURER], notes=FULL_NOTES,
        graph=EvidenceGraph(), load_bearing_ids=(), narration=Narration(thesis="t", anti_thesis="a"),
        agent_versions={"business_analyst": "1.0.0"}, forensic=THRESHOLDS["forensic"], policy=POLICY,
        feasibility=SELF_FUNDED, self_fund_ceiling=1.0,
    )
    assert report.kill_criteria and not report.rehabilitation_criteria
    assert "Verdict rationale (deterministic)" in report.executive_summary
    assert report.computed_facts["cum_cfo_pat"] == derived.value("cum_cfo_pat")
    assert report.fact_citations["cum_cfo_pat"].fact_id == "derived:cum_cfo_pat"

    withheld = assemble_report(
        ticker="ACME", company_name="ACME Limited", as_of=AS_OF, run_id="run-2",
        decision=VerdictDecision(Verdict.RETURN_HURDLE_NOT_CLEARED, "maths"), derived=derived,
        evaluation=evaluation, models=[], notes=FULL_NOTES, graph=EvidenceGraph(),
        load_bearing_ids=(), narration=Narration(thesis="t", anti_thesis="a"), agent_versions={},
        forensic=THRESHOLDS["forensic"], policy=POLICY, feasibility=UNAFFORDABLE,
        self_fund_ceiling=1.0,
    )
    assert withheld.rehabilitation_criteria           # the re-entry trigger
    assert withheld.kill_criteria                     # and the tripwires that would then apply


def test_checklist_carries_the_models_the_expected_checks_and_the_note_proof():
    checklist = build_checklist(
        _evaluation(unavailable=1), [BusinessModel.MANUFACTURER, BusinessModel.LENDER],
        NotesReview(coverage=0.9, undispositioned=("30",), substantive_share=0.5, notes_total=10,
                    disclosure_gaps=("benami_property",)))
    assert checklist.business_models == ["MANUFACTURER", "LENDER"]
    assert len(checklist.expected_checks) == 10
    assert checklist.note_coverage == 0.9 and checklist.notes_undispositioned == ["30"]
    assert checklist.disclosure_gaps == ["benami_property"]
    assert checklist.outcome_of("check_0") is CheckOutcome.UNAVAILABLE


def test_unavailable_checks_are_republished_as_explicit_gaps(store):
    seed_store(store, "ACME", clean_series())
    derived = D.derive_metrics(D.load_company_facts(store, "ACME", AS_OF))
    report = assemble_report(
        ticker="ACME", company_name="ACME", as_of=AS_OF, run_id="r",
        decision=VerdictDecision(Verdict.INSUFFICIENT_DISCLOSURE, "opaque"), derived=derived,
        evaluation=_evaluation(unavailable=3), models=[], notes=NO_NOTES, graph=EvidenceGraph(),
        load_bearing_ids=(), narration=Narration(thesis="t", anti_thesis="a"), agent_versions={},
        forensic=THRESHOLDS["forensic"], policy=POLICY,
    )
    assert len(report.unavailable_items) == 3
    assert all("absent" in item for item in report.unavailable_items)
