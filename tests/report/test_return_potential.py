"""The return-potential section (ADR-0068).

SPEC §6 calls the feasibility gate the intellectual centre of the system, and until this section
existed it reached the reader only obliquely — through a verdict rationale and a rehabilitation
criterion. A report could therefore be judged against "5x over 7 years" without ever printing that
target, which made the most consequential assumption in the analysis the one thing a reader could not
check.

Two things are pinned here. The section must appear even when the gate could not run, because "ROIC is
not derivable" is a finding and a silently absent section is not. And the target must be a parameter of
the question rather than a property of the firm (ADR-0063): the same company judged at 3x/5y and at
10x/7y is the same company, and the report must say which question it answered.
"""

from __future__ import annotations

import pytest

from firm.core.compute.multibagger import feasibility_gate
from firm.core.config import report_policy
from firm.core.pipeline import derive as D
from firm.core.pipeline.deep_dive import feasibility_at_target
from firm.core.report.assemble import build_return_potential
from firm.core.report.render import render_markdown
from tests.conftest import AS_OF, clean_series, seed_store

POLICY = report_policy()
SELF_FUNDED = feasibility_gate(
    g_required=0.258, roic=0.40, self_fund_ceiling=1.0, high_quality_ceiling=0.6,
    debt_capacity_available=True, thesis_allows_dilution=False)


def test_the_required_cagr_is_the_spec_identity():
    """10x over 7 years with no re-rating is 38.9% (SPEC §6.2, re-derived in PLAN §4)."""
    rp = build_return_potential(None, target_multiple=10, target_years=7)
    assert rp.required_earnings_cagr == pytest.approx(0.389, abs=0.001)


def test_the_section_exists_even_when_the_gate_could_not_run():
    """Missing is reported as missing: the target and its required growth still tell the reader
    something, and the blocking input is NAMED rather than the section quietly disappearing."""
    rp = build_return_potential(None, target_multiple=5, target_years=7)
    assert rp.unavailable_reason and "ROIC" in rp.unavailable_reason
    assert rp.roic is None and rp.required_reinvestment is None
    assert rp.required_earnings_cagr > 0


def test_a_self_funder_carries_its_gate_verdict_and_reinvestment_need():
    rp = build_return_potential(SELF_FUNDED, target_multiple=5, target_years=7)
    # 0.258 / 0.40 = 64.5% of NOPAT — self-funding, but above the 60% "surplus" ceiling.
    assert rp.gate_verdict == "SELF_FUNDED"
    assert rp.roic == pytest.approx(0.40)
    assert rp.required_reinvestment == pytest.approx(0.258 / 0.40, abs=0.001)
    assert rp.unavailable_reason == ""


def test_the_target_is_a_parameter_of_the_question_not_a_property_of_the_firm(store):
    """ADR-0063: the same ROIC clears a modest target and fails an aggressive one, and the report has
    to say which one it answered. A hardwired 5x was the last thing making that invisible."""
    seed_store(store, "ACME", clean_series())
    facts = D.load_company_facts(store, "ACME", AS_OF)
    derived = D.derive_metrics(facts)
    mb = {"self_fund_ceiling": 1.0, "high_quality_ceiling": 0.6}

    modest = feasibility_at_target(derived, POLICY, mb, target_multiple=2, target_years=7)
    aggressive = feasibility_at_target(derived, POLICY, mb, target_multiple=20, target_years=7)
    assert modest is not None and aggressive is not None
    assert modest.g_required < aggressive.g_required
    assert modest.required_reinvestment < aggressive.required_reinvestment


def test_the_section_prints_the_target_it_was_judged_against(store):
    from firm.core.compute.models import BusinessModel
    from firm.core.compute.quality import ForensicMetrics
    from firm.core.config import load_thresholds
    from firm.core.pipeline.checks import CheckEvaluation
    from firm.core.report.assemble import Narration, NotesReview, VerdictDecision, assemble_report
    from firm.schemas.evidence import EvidenceGraph
    from firm.schemas.report import Verdict

    seed_store(store, "ACME", clean_series())
    facts = D.load_company_facts(store, "ACME", AS_OF)
    report = assemble_report(
        ticker="ACME", company_name="ACME Limited", as_of=AS_OF, run_id="r",
        decision=VerdictDecision(Verdict.WATCH, "unproven"), derived=D.derive_metrics(facts),
        evaluation=CheckEvaluation((), ForensicMetrics(), ()),
        models=[BusinessModel.MANUFACTURER], notes=NotesReview(), graph=EvidenceGraph(),
        load_bearing_ids=(), narration=Narration(thesis="t", anti_thesis="a", open_questions=("q",)),
        agent_versions={}, forensic=load_thresholds()["forensic"], policy=POLICY,
        feasibility=SELF_FUNDED, target_multiple=3, target_years=5,
    )

    assert report.return_potential.target_multiple == 3
    markdown = render_markdown(report)
    assert "## Return potential" in markdown
    assert "**3x over 5 years**" in markdown
    assert "`SELF_FUNDED`" in markdown
    assert "64% of NOPAT" in markdown
