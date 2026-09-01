"""SPEC §8's funnel as findings, not filters (ADR-0071).

The gates keep a 3,000-company sweep affordable by dropping the illiquid, the out-of-band and the
forensic hard-fails before the expensive agents run. That economics is right for discovery, where the
FIRM chooses the company, and wrong when the OWNER chooses: research eligibility and investment verdict
are separate (ADR-0064), so a company that was named must never lose a section for failing an
investment gate.

So the test that matters most here is the negative one: a company that fails every gate still gets the
whole report. The rest pin the honesty of the individual gates — chiefly that UNAVAILABLE is not PASS.
"""

from __future__ import annotations

from datetime import date

from firm.core.compute.multibagger import feasibility_gate
from firm.core.compute.quality import (
    Flag,
    ForensicScreenResult,
    ForensicVerdict,
    Severity,
)
from firm.core.config import load_thresholds
from firm.core.orchestrator.stages import Gate
from firm.core.pipeline.deep_dive import run_deep_dive
from firm.core.pipeline.gates import evaluate_gates
from firm.core.report.render import render_markdown
from tests.conftest import AS_OF, clean_answers, filing_for, seed_store
from tests.pipeline.test_valuation_wiring import seed_price, valuable_series

SCREEN = load_thresholds()["screen"]
CLEAN = ForensicScreenResult(ForensicVerdict.PASS, False, [])
HARD_FAIL = ForensicScreenResult(ForensicVerdict.HARD_FAIL, True, [
    Flag("cumulative_cfo_pat_low", Severity.SEVERE, "SigmaCFO/SigmaPAT 0.21 < 0.70")])
SELF_FUNDED = feasibility_gate(g_required=0.258, roic=0.40, self_fund_ceiling=1.0,
                               high_quality_ceiling=0.6, debt_capacity_available=True,
                               thesis_allows_dilution=False)
UNAFFORDABLE = feasibility_gate(g_required=0.258, roic=0.15, self_fund_ceiling=1.0,
                                high_quality_ceiling=0.6, debt_capacity_available=True,
                                thesis_allows_dilution=False)


def _gates(**kw):
    base = {"screen": CLEAN, "feasibility": SELF_FUNDED, "history_years": 10, "thresholds": SCREEN,
            "market_cap_cr": 5000.0, "adv_cr": 4.0, "kill_criteria": [object()],
            "red_team_ran": True}
    return {g.gate: g for g in evaluate_gates(**{**base, **kw})}


def test_a_liquid_in_band_company_with_history_clears_gate_a():
    a = _gates()[Gate.A]
    assert a.passed is True and "in-band" in a.reason


def test_gate_a_fails_on_the_liquidity_floor_and_says_the_number():
    a = _gates(adv_cr=0.2)[Gate.A]
    assert a.passed is False
    assert "liquidity floor" in a.reason and "0.20" in a.reason


def test_gate_a_is_unavailable_not_passed_when_the_price_inputs_are_absent():
    """UNAVAILABLE is not PASS. A gate whose inputs were missing has not been cleared, and treating
    the two alike is the missing-reads-as-clean failure at funnel level."""
    a = _gates(market_cap_cr=None, adv_cr=None)[Gate.A]
    assert a.passed is None and a.status == "UNAVAILABLE"
    assert "market cap" in a.reason and "average daily traded value" in a.reason


def test_a_deterministic_hard_fail_closes_gate_b_and_names_the_flag():
    b = _gates(screen=HARD_FAIL)[Gate.B]
    assert b.passed is False and "cumulative_cfo_pat_low" in b.reason


def test_gate_c_refuses_to_claim_a_runway_it_cannot_test():
    """Asserting PASS because nothing contradicted it is exactly how a gate becomes decoration."""
    c = _gates()[Gate.C]
    assert c.passed is None and "judgment about the" in c.reason


def test_gate_d_is_the_feasibility_math_and_unavailable_without_roic():
    assert _gates()[Gate.D].passed is True
    assert _gates(feasibility=UNAFFORDABLE)[Gate.D].passed is False
    unavailable = _gates(feasibility=None)[Gate.D]
    assert unavailable.passed is None and "ROIC is not derivable" in unavailable.reason


def test_gate_e_needs_a_bear_case_and_dated_kill_criteria():
    assert _gates()[Gate.E].passed is True
    unchallenged = _gates(red_team_ran=False)[Gate.E]
    assert unchallenged.passed is None and "has not survived anything" in unchallenged.reason
    assert _gates(kill_criteria=[])[Gate.E].passed is False


def test_a_company_that_fails_every_gate_still_gets_the_whole_report(store, tmp_path):
    """The ADR-0064 invariant at funnel level: gates annotate, they never remove a section.

    Below the liquidity floor, below the cap floor and forensically hard-failing — in a sweep this
    company would never have been looked at. Because the owner named it, the report is complete.
    """
    seed_store(store, "TINYCO", valuable_series())
    seed_price(store, "TINYCO", 2.0, date(2026, 7, 28))          # a nanocap, far below the band

    result = run_deep_dive(
        store, "TINYCO", AS_OF, answers=clean_answers("TINYCO"), filing=filing_for("TINYCO"),
        company_name="Tinyco Limited", reports_root=tmp_path, write=True, memory_root=tmp_path)

    report = result.report
    assert result.published, "a company that fails the funnel must still get a report"
    assert report.gates, "the funnel must be reported even when it fails"
    assert {g.gate for g in report.gates} == {"A", "B", "C", "D", "E"}

    markdown = render_markdown(report)
    assert "## The funnel, applied to this company" in markdown
    assert "none of them removed a section from this report" in markdown
    # every substantive section is still present
    for heading in ("## Forensic review", "## Valuation", "## Return potential", "## Thesis",
                    "## Anti-thesis"):
        assert heading in markdown, f"{heading} was dropped by a failing gate"
