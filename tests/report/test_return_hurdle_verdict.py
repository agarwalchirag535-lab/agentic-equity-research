"""The last of the old charter, out of the verdict layer (ADR-0081).

ADR-0063 flagged four places where the 5-10x question still behaved as the system's purpose rather than
one section of a report. Three were closed by ADR-0067 (the MIXED outcome) and ADR-0068 (the target as a
per-run parameter). What remained was the verdict layer's own language, which is what a reader sees
first and therefore the last place the old framing could still do damage:

* `QUALITY_WRONG_PRICE` was named for a price comparison it has never performed — it fires on the §6.3
  feasibility gate. A reader shown "wrong price today" would look for a valuation argument that was not
  made.
* Its rationale said "forensically clean, BUT the feasibility gate returned …", which reads as a
  finding against the company rather than a finding against the target the run was given.
* An un-runnable gate said "no compounding claim is provable yet", framing a whole report around the
  one section that could not run.
"""

from __future__ import annotations

from firm.core.compute.multibagger import feasibility_gate
from firm.core.compute.quality import ForensicScreenResult, ForensicVerdict
from firm.core.config import load_thresholds, report_policy
from firm.core.report.assemble import NotesReview, choose_verdict
from firm.core.report.render import render_markdown
from firm.schemas.report import OUTCOME_BY_VERDICT, Outcome, Verdict
from tests.report.test_assemble import _evaluation

POLICY = report_policy()
MIN_HISTORY = int(load_thresholds()["screen"]["min_history_years"])
CLEAN = ForensicScreenResult(ForensicVerdict.PASS, False, [])
FULL_NOTES = NotesReview(coverage=1.0, substantive_share=0.6, notes_total=10, scanned=True)

UNAFFORDABLE = feasibility_gate(g_required=0.258, roic=0.15, self_fund_ceiling=1.0,
                                high_quality_ceiling=0.6, debt_capacity_available=True,
                                thesis_allows_dilution=False)
SELF_FUNDED = feasibility_gate(g_required=0.258, roic=0.40, self_fund_ceiling=1.0,
                               high_quality_ceiling=0.6, debt_capacity_available=True,
                               thesis_allows_dilution=False)


def _choose(feasibility, years: int = 10):
    return choose_verdict(CLEAN, _evaluation(), FULL_NOTES, feasibility, policy=POLICY,
                          history_years=years, min_history_years=MIN_HISTORY)


def test_the_verdict_is_named_for_the_test_it_actually_runs():
    """It fires on the §6.3 self-funding gate. It has never compared a price to anything."""
    assert _choose(UNAFFORDABLE).verdict is Verdict.RETURN_HURDLE_NOT_CLEARED
    assert not hasattr(Verdict, "QUALITY_WRONG_PRICE")


def test_the_rationale_puts_the_miss_against_the_target_not_against_the_company():
    rationale = _choose(UNAFFORDABLE).rationale
    assert "forensically clean and adequately disclosed" in rationale
    assert "THIS RUN'S RETURN TARGET" in rationale
    assert "not a judgment that the business is unsound" in rationale
    # ... and it tells the reader the result is contingent on a parameter they chose.
    assert "a different target may clear" in rationale


def test_a_clean_business_missing_the_hurdle_reads_as_mixed_never_as_a_failure():
    """The whole point of ADR-0063: not clearing YOUR target is not a finding against the company."""
    assert OUTCOME_BY_VERDICT[Verdict.RETURN_HURDLE_NOT_CLEARED] is Outcome.MIXED
    assert OUTCOME_BY_VERDICT[Verdict.FORENSIC_CAUTION] is Outcome.FAIL


def test_an_untestable_gate_does_not_frame_the_whole_verdict_around_compounding():
    rationale = _choose(None).rationale
    assert "forensically clean and adequately disclosed" in rationale
    assert "untested rather than answered" in rationale
    assert "not a verdict on the business" in rationale


def test_clearing_the_target_is_still_the_positive_rung():
    """The ladder did not go soft: a company that clears the gate is still a COMPOUNDER and still PASS."""
    decision = _choose(SELF_FUNDED)
    assert decision.verdict is Verdict.COMPOUNDER
    assert OUTCOME_BY_VERDICT[decision.verdict] is Outcome.PASS


def test_the_headline_a_reader_sees_first_describes_the_finding():
    from datetime import date

    from firm.schemas._base import Confidence, Grade
    from firm.schemas.report import ResearchReport

    report = ResearchReport(
        ticker="ACME", company_name="ACME Limited", as_of=date(2026, 7, 30), run_id="r",
        verdict=Verdict.RETURN_HURDLE_NOT_CLEARED,
        confidence=Confidence(value=0.6, evidence_count=4, lowest_grade_relied_on=Grade.A,
                              rationale="test"))
    markdown = render_markdown(report)
    assert "Clean business; does not clear this run's return target" in markdown
    assert "Outcome: `MIXED`" in markdown
    assert "wrong price" not in markdown
