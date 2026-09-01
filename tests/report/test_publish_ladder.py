"""The completeness invariant: an owner-chosen company always ends the run with an artifact (ADR-0065).

Two things are being defended here at once, and they pull against each other, which is why the tests
are explicit about both:

* **Completeness** — a publication gate refusing the report must never be the reason the owner gets
  nothing. Research eligibility and investment verdict are separate (ADR-0064).
* **Honesty** — completeness must not be bought by weakening a gate. Every rung of the ladder asserts
  strictly LESS than the one above it, the degradation is stated on the artifact, and the deterministic
  checklist (flags included) survives every rung intact. A degraded report may never launder a
  forensic caution into silence.
"""

from __future__ import annotations

from functools import partial

from firm.core.compute.models import BusinessModel
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
from firm.core.report.assemble import Narration, NotesReview, VerdictDecision, assemble_report
from firm.core.report.narration import deterministic_narration, merge_narration
from firm.core.report.publish import publish_or_degrade
from firm.core.validators.evidence_graph import validate_graph
from firm.core.validators.publication import validate_report
from firm.schemas.evidence import ClaimKind, EvidenceClaim, EvidenceGraph
from firm.schemas.report import CheckOutcome, CheckRecord, GapKind, Verdict
from tests.conftest import AS_OF, clean_answers, clean_series, filing_for, seed_store

POLICY = report_policy()
THRESHOLDS = load_thresholds()

CLEAN_SCREEN = ForensicScreenResult(ForensicVerdict.PASS, False, [])
HARD_FAIL_SCREEN = ForensicScreenResult(ForensicVerdict.HARD_FAIL, True, [
    Flag("cumulative_cfo_pat_low", Severity.SEVERE, "ΣCFO/ΣPAT 0.21 < 0.70")])

FULL_NOTES = NotesReview(coverage=1.0, substantive_share=0.6, notes_total=10, scanned=True)
PARTIAL_NOTES = NotesReview(coverage=0.4, substantive_share=0.2, notes_total=10, scanned=True,
                            undispositioned=("note 7",))

# Prose an agent would have written. Deliberately missing the anti-thesis and the open questions, which
# is the commonest way a real narration fails P2.
LOPSIDED = Narration(
    executive_summary="ACME compounds.", thesis="The business earns above its cost of capital.")
COMPLETE = Narration(
    executive_summary="ACME compounds.", thesis="The business earns above its cost of capital.",
    anti_thesis="Concentration in one customer is the standing risk.",
    open_questions=("What is the top-customer share?",))


def _evaluation(unavailable: int = 0, total: int = 8, flagged: int = 0,
                gap: GapKind = GapKind.DISCLOSURE) -> CheckEvaluation:
    records = []
    names = [f"check_{i}" for i in range(total)]
    for i, name in enumerate(names):
        if i < unavailable:
            records.append(CheckRecord(name=name, outcome=CheckOutcome.UNAVAILABLE,
                                       reason="the filing does not carry the input", gap=gap))
        elif i < unavailable + flagged:
            records.append(CheckRecord(name=name, outcome=CheckOutcome.FLAG,
                                       detail="fired", fact_ids=[f"fact:{name}"]))
        else:
            records.append(CheckRecord(name=name, outcome=CheckOutcome.PASS, detail="ok"))
    return CheckEvaluation(tuple(records), ForensicMetrics(), tuple(names))


def _assembler(store, evaluation, notes):
    seed_store(store, "ACME", clean_series())
    facts = D.load_company_facts(store, "ACME", AS_OF)
    derived = D.derive_metrics(facts)
    return partial(
        assemble_report,
        ticker="ACME", company_name="ACME Limited", as_of=AS_OF, run_id="2026-07-30-testrun",
        derived=derived, evaluation=evaluation, models=[BusinessModel.MANUFACTURER], notes=notes,
        agent_versions={"forensic_accountant": "1.0.0"},
        forensic=THRESHOLDS["forensic"], policy=POLICY,
    )


def _degrade(store, *, decision, narration, evaluation, notes, screen=CLEAN_SCREEN,
             graph=None, ids=()):
    """Assemble, validate for real, and run the ladder on whatever the gates actually said."""
    assemble = _assembler(store, evaluation, notes)
    graph = graph if graph is not None else EvidenceGraph()
    report = assemble(decision=decision, narration=narration, graph=graph, load_bearing_ids=ids,
                      coverage_gaps=())
    return publish_or_degrade(
        assemble=assemble, as_of=AS_OF, report=report, decision=decision,
        publication_violations=tuple(validate_report(report)),
        graph_violations=tuple(validate_graph(graph, AS_OF)),
        agent_narration=narration,
        fallback_narration=deterministic_narration(
            evaluation=evaluation, screen=screen, notes=notes),
        graph=graph, load_bearing_ids=ids,
    )


# ---- the code-authored narration ------------------------------------------------------------------
def test_the_deterministic_narration_always_argues_both_sides():
    """P2 demands a thesis, an anti-thesis and open questions. Code must be able to supply all three."""
    narration = deterministic_narration(
        evaluation=_evaluation(), screen=CLEAN_SCREEN, notes=FULL_NOTES)
    assert narration.thesis.strip()
    assert narration.anti_thesis.strip()
    assert narration.open_questions
    assert narration.forensic_narrative.strip()


def test_it_argues_both_sides_even_when_nothing_could_be_evaluated():
    """The floor's hardest case: no checks ran at all, and the report still may not go silent."""
    narration = deterministic_narration(
        evaluation=_evaluation(unavailable=8, total=8), screen=CLEAN_SCREEN, notes=PARTIAL_NOTES)
    assert "no deterministic case" in narration.thesis.lower()
    assert narration.anti_thesis.strip() and narration.open_questions


def test_open_questions_separate_managements_gap_from_the_firms(store):
    """ADR-0051: publishing our unfinished extractor as their opacity is a false accusation."""
    theirs = deterministic_narration(
        evaluation=_evaluation(unavailable=3, gap=GapKind.DISCLOSURE), screen=CLEAN_SCREEN,
        notes=FULL_NOTES).open_questions
    ours = deterministic_narration(
        evaluation=_evaluation(unavailable=3, gap=GapKind.CAPABILITY), screen=CLEAN_SCREEN,
        notes=FULL_NOTES).open_questions

    assert any(q.startswith("For management:") for q in theirs)
    assert not any(q.startswith("For management:") for q in ours)
    assert any("Firm backlog" in q for q in ours)


def test_flags_reach_the_anti_thesis_with_a_replication_route_and_no_accusation():
    evaluation = _evaluation(flagged=2)
    narration = deterministic_narration(
        evaluation=evaluation, screen=HARD_FAIL_SCREEN, notes=FULL_NOTES)
    assert "check_0" in narration.anti_thesis
    assert len(narration.replication_notes) == 2
    assert all("recompute from facts" in n for n in narration.replication_notes)
    # P3: the wording states what evidence indicates; it never asserts fraud as established fact.
    assert "warrant explanation" in narration.forensic_narrative


def test_merge_lets_the_analyst_win_wherever_they_wrote_anything():
    merged = merge_narration(LOPSIDED, deterministic_narration(
        evaluation=_evaluation(), screen=CLEAN_SCREEN, notes=FULL_NOTES))
    assert merged.thesis == LOPSIDED.thesis                 # the analyst's, untouched
    assert merged.anti_thesis                                # supplied by code
    assert merged.open_questions


# ---- the ladder -----------------------------------------------------------------------------------
def test_a_report_the_gates_accept_is_returned_untouched(store):
    decision = VerdictDecision(Verdict.WATCH, "promise, thesis unproven")
    report, degradation, residual = _degrade(
        store, decision=decision, narration=COMPLETE, evaluation=_evaluation(unavailable=1),
        notes=FULL_NOTES)
    assert degradation == () and residual == ()
    assert report.verdict is Verdict.WATCH
    assert report.thesis == COMPLETE.thesis


def test_a_fillable_gap_is_supplemented_and_the_verdict_survives(store):
    """Rung 2. The analysts' work is not thrown away with the gate failure that caught it."""
    decision = VerdictDecision(Verdict.WATCH, "promise, thesis unproven")
    report, degradation, residual = _degrade(
        store, decision=decision, narration=LOPSIDED, evaluation=_evaluation(unavailable=1),
        notes=FULL_NOTES)

    assert residual == ()
    assert report.verdict is Verdict.WATCH                   # the judgment is NOT withheld
    assert report.thesis == LOPSIDED.thesis                  # the analyst's prose stands
    assert report.anti_thesis and report.open_questions      # code supplied what was missing
    assert degradation and "deterministic layer supplied" in degradation[0]
    assert degradation[0] in report.unavailable_items        # stated ON the artifact


def test_when_the_verdict_itself_is_unpublishable_it_is_withheld_not_faked(store):
    """Rung 3. A positive verdict on 40%-read notes fails P1; INSUFFICIENT_EVIDENCE is the honest fall."""
    decision = VerdictDecision(Verdict.COMPOUNDER, "clean and self-funding")
    report, degradation, residual = _degrade(
        store, decision=decision, narration=COMPLETE, evaluation=_evaluation(unavailable=1),
        notes=PARTIAL_NOTES)

    assert residual == ()
    assert report.verdict is Verdict.INSUFFICIENT_EVIDENCE
    assert degradation and "withheld as" in degradation[0]
    # nothing is buried: the verdict the ladder actually reached is named on the artifact
    assert "COMPOUNDER" in report.executive_summary
    assert any("COMPOUNDER" in gap for gap in report.unavailable_items)


def test_degrading_never_launders_a_forensic_caution(store):
    """The invariant that matters most: a red flag cannot be quietened out of existence by a downgrade."""
    decision = VerdictDecision(Verdict.FORENSIC_CAUTION, "cumulative_cfo_pat_low fired")
    evaluation = _evaluation(flagged=2)
    report, degradation, residual = _degrade(
        store, decision=decision, narration=LOPSIDED, evaluation=evaluation, notes=PARTIAL_NOTES,
        screen=HARD_FAIL_SCREEN)

    assert residual == () and degradation
    # whatever rung it landed on, the verdict never IMPROVED and the evidence never vanished
    assert report.verdict is not Verdict.COMPOUNDER
    assert [r.name for r in report.checklist.records if r.outcome is CheckOutcome.FLAG] == [
        "check_0", "check_1"]
    assert "check_0" in report.anti_thesis
    assert any("check_0" in q or "check_0" in n for q in report.open_questions
               for n in report.replication_notes) or report.replication_notes


def test_an_unfixable_graph_falls_to_the_deterministic_floor_and_still_publishes(store):
    """Rung 4. R1-R6 police agent claims, so dropping the claims — not the report — is the fix."""
    graph = EvidenceGraph()
    graph.claims["c1"] = _load_bearing_claim()
    decision = VerdictDecision(Verdict.WATCH, "promise, thesis unproven")

    report, degradation, residual = _degrade(
        store, decision=decision, narration=COMPLETE, evaluation=_evaluation(unavailable=1),
        notes=FULL_NOTES, graph=graph, ids=("c1",))

    assert residual == ()
    assert report.verdict is Verdict.INSUFFICIENT_EVIDENCE
    assert report.load_bearing_points == []                  # the offending claims are gone
    assert report.thesis and report.anti_thesis              # ... and the report is still a report
    assert degradation and "deterministic report" in degradation[-1]
    # the agents that ran are still named, so a withheld narrative is distinguishable from an absent one
    assert "forensic_accountant" in report.agent_versions


def _load_bearing_claim() -> EvidenceClaim:
    """A load-bearing claim resting on no grade-A/B evidence at all — an R1 violation by construction."""
    return EvidenceClaim(id="c1", statement="Cash appears overstated.", kind=ClaimKind.INFERENCE,
                         load_bearing=True, supporting=[])


def test_even_an_unsatisfiable_gate_yields_an_artifact_rather_than_silence(store):
    """Rung 5, the terminal guarantee.

    A negative verdict draws its rehabilitation criteria from flags, unavailable checks and a failed
    feasibility gate. Strip all three — every check passing, nothing unavailable, no feasibility — and
    P2 cannot be satisfied at any rung. The pipeline does not reach that state (a company like that is
    a COMPOUNDER, not a WATCH), but if it ever did, the run must still end in a report that names its
    own failure. Silence is the one outcome ADR-0064 forbids.
    """
    decision = VerdictDecision(Verdict.WATCH, "promise, thesis unproven")
    report, degradation, residual = _degrade(
        store, decision=decision, narration=COMPLETE, evaluation=_evaluation(), notes=FULL_NOTES)

    # Both gates refuse, and both are RIGHT to: there are no rehabilitation criteria to derive (P2),
    # and "we could not tell" is not evidenced when every check ran and every note was read (P1).
    assert set(residual) == {"P1_incomplete_checklist", "P2_asymmetric"}
    assert len(degradation) == 2         # the withholding note, and the failed-gates warning
    assert report.verdict is Verdict.INSUFFICIENT_EVIDENCE
    assert any("FAILS THE FIRM'S OWN PUBLICATION GATES" in gap for gap in report.unavailable_items)
    assert report.thesis and report.anti_thesis and report.open_questions


# ---- end to end: the run always leaves an artifact behind ------------------------------------------
def test_a_gate_blocked_run_still_writes_a_report_and_logs_no_prediction(store, tmp_path, monkeypatch):
    """The invariant at the level the owner experiences it: `firm deep-dive` never ends in silence.

    Every publication gate is forced to refuse, which is worse than anything the real validators do —
    no rung of the ladder can clear it. The run must still produce `report.md` and `report.json`, the
    artifact must say on its face that it failed the firm's own gates, and nothing may enter the
    prediction ledger: a report the gates refused was never a forecast.
    """
    from firm.core.pipeline import deep_dive as dd
    from firm.core.report import publish as pub
    from firm.core.validators.publication import PublicationViolation

    def always_refuse(report, **kwargs):
        return [PublicationViolation("P2_asymmetric", "thesis", "forced refusal for the test")]

    monkeypatch.setattr(dd, "validate_report", always_refuse)
    monkeypatch.setattr(pub, "validate_report", always_refuse)

    seed_store(store, "BLOCKED", clean_series())
    result = dd.run_deep_dive(
        store, "BLOCKED", AS_OF, answers=clean_answers("BLOCKED"), filing=filing_for("BLOCKED"),
        company_name="Blocked Limited", reports_root=tmp_path, write=True, memory_root=tmp_path)

    assert result.published and result.markdown_path.exists() and result.json_path.exists()
    assert result.degraded and result.residual_violations == ("P2_asymmetric",)
    assert "FAILS THE FIRM'S OWN PUBLICATION GATES" in result.markdown_path.read_text()
    assert result.predictions == ()
    assert not (tmp_path / "predictions.jsonl").exists()


def test_a_clean_run_is_unaffected_by_the_ladder(store, tmp_path):
    """The ladder must be invisible when the gates are satisfied — no degradation, predictions logged."""
    from firm.core.pipeline.deep_dive import run_deep_dive

    seed_store(store, "CLEANCO", clean_series(roic_boost=1.6))
    result = run_deep_dive(
        store, "CLEANCO", AS_OF, answers=clean_answers("CLEANCO"), filing=filing_for("CLEANCO"),
        company_name="Cleanco Limited", reports_root=tmp_path, write=True, memory_root=tmp_path)

    assert result.published and not result.degraded
    assert result.degradation == () and result.residual_violations == ()
    assert result.report.verdict is Verdict.COMPOUNDER
    assert result.predictions            # a published positive verdict IS a forecast
