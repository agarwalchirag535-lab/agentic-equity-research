"""The four-outcome headline (ADR-0067).

`Verdict` stays the operative value — it drives criteria symmetry, the publication gates and the
golden set. `Outcome` is the summary axis above it, and it exists because reading RETURN_HURDLE_NOT_CLEARED
as a flat negative was the last place the 5-10x question was still masquerading as the whole mandate.

The tests that matter here are the structural ones: the mapping must be exhaustive, so a verdict added
later cannot ship without someone deciding what it means at the headline; and it must not drift from
POSITIVE_VERDICTS, which is what actually attaches kill criteria.
"""

from __future__ import annotations

from datetime import date

from firm.schemas._base import Confidence, Grade
from firm.schemas.report import (
    OUTCOME_BY_VERDICT,
    POSITIVE_VERDICTS,
    Outcome,
    ResearchReport,
    Verdict,
)


def test_every_verdict_declares_exactly_one_outcome():
    """Exhaustive by construction: adding a verdict without an outcome fails here, not in production."""
    assert set(OUTCOME_BY_VERDICT) == set(Verdict)


def test_the_headline_never_drifts_from_the_verdicts_that_carry_kill_criteria():
    """Two ways of saying "this company passed" must not be able to disagree."""
    assert {v for v, o in OUTCOME_BY_VERDICT.items() if o is Outcome.PASS} == set(POSITIVE_VERDICTS)


def test_a_good_business_that_cannot_compound_5x_is_mixed_not_failed():
    """The ADR-0063 correction, pinned: failing the return hurdle is not a finding against the company."""
    assert OUTCOME_BY_VERDICT[Verdict.RETURN_HURDLE_NOT_CLEARED] is Outcome.MIXED
    assert OUTCOME_BY_VERDICT[Verdict.WATCH] is Outcome.MIXED
    # ... and a corroborated forensic finding is still the one thing that reads as a failure
    assert OUTCOME_BY_VERDICT[Verdict.FORENSIC_CAUTION] is Outcome.FAIL


def test_both_kinds_of_not_knowing_read_as_insufficient_evidence():
    """The verdict keeps WHOSE gap it was; the headline does not pretend that changes the conclusion."""
    assert OUTCOME_BY_VERDICT[Verdict.INSUFFICIENT_DISCLOSURE] is Outcome.INSUFFICIENT_EVIDENCE
    assert OUTCOME_BY_VERDICT[Verdict.INSUFFICIENT_EVIDENCE] is Outcome.INSUFFICIENT_EVIDENCE


def test_the_outcome_travels_with_the_serialised_artifact():
    """A computed field, so it cannot be set independently of the verdict — and it must reach the JSON."""
    report = ResearchReport(
        ticker="ACME", company_name="ACME Limited", as_of=date(2026, 7, 30), run_id="r",
        verdict=Verdict.RETURN_HURDLE_NOT_CLEARED,
        confidence=Confidence(value=0.5, evidence_count=1, lowest_grade_relied_on=Grade.A,
                              rationale="test"),
    )
    assert report.outcome is Outcome.MIXED
    assert '"outcome":"MIXED"' in report.model_dump_json().replace(" ", "")
