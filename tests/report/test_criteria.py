"""Tests for deterministic kill / rehabilitation criteria (ADR-0021).

The rule being protected: a criterion is a *number*, so no LLM may author one, and a criterion that cannot
trip is not a criterion.
"""

from __future__ import annotations

from datetime import date

from firm.core.config import load_thresholds, report_policy
from firm.core.pipeline import derive as D
from firm.core.report.criteria import kill_criteria, rehabilitation_criteria, resolve_by
from firm.schemas.report import CheckOutcome, CheckRecord, VerifiedCleanChecklist
from tests.conftest import AS_OF, clean_series, seed_store

FORENSIC = load_thresholds()["forensic"]
POLICY = report_policy()


def _derived(store, ticker="ACME", series=None):
    seed_store(store, ticker, series or clean_series())
    return D.derive_metrics(D.load_company_facts(store, ticker, AS_OF))


def test_resolve_by_is_the_next_fy_close_plus_the_filing_lag():
    # as-of July 2026 -> FY27 closes 31 Mar 2027 -> + 210 days
    assert resolve_by(date(2026, 7, 30), 1, 210) == date(2027, 10, 27)
    # a January run is still inside FY26, so one horizon out is the 2026 close
    assert resolve_by(date(2026, 1, 10), 1, 210) == date(2026, 10, 27)


def test_kill_criteria_are_dated_falsifiable_and_below_todays_level(store):
    derived = _derived(store)
    criteria = kill_criteria(derived, forensic=FORENSIC, policy=POLICY, as_of=AS_OF)

    assert len(criteria) >= 3
    assert any(c.load_bearing for c in criteria)
    assert all(c.resolve_by > AS_OF for c in criteria)
    assert all(c.operator in (">=", "<=") for c in criteria)

    # every '>=' tripwire sits strictly inside today's value: it can actually trip
    for criterion in criteria:
        current = derived.value(criterion.metric)
        if current is None or criterion.operator != ">=":
            continue
        assert criterion.threshold < current or criterion.threshold == FORENSIC.get(
            "cumulative_cfo_pat_min", -1)


def test_a_kill_threshold_never_falls_below_the_published_policy_floor(store):
    """Headroom may not be given away below the floor the firm already committed to publicly."""
    series = clean_series()
    # CFO barely covers PAT: 10% headroom would push the tripwire under the 0.70 policy floor
    series["cashflow:Cash from Operating Activity"] = [45, 52, 62, 74, 86, 95]
    derived = _derived(store, "TIGHT", series)
    criteria = {c.metric: c for c in kill_criteria(
        derived, forensic=FORENSIC, policy=POLICY, as_of=AS_OF)}

    assert criteria["cum_cfo_pat"].threshold >= FORENSIC["cumulative_cfo_pat_min"]


def test_no_derivable_metrics_means_no_invented_criteria(store):
    derived = _derived(store, "GHOST", {"pnl:Sales": [1.0]})
    assert kill_criteria(derived, forensic=FORENSIC, policy=POLICY, as_of=AS_OF) == []


def test_rehabilitation_criteria_come_from_the_fired_and_unavailable_checks(store):
    derived = _derived(store)
    checklist = VerifiedCleanChecklist(
        expected_checks=["cumulative_cfo_pat", "receivables_divergent", "promoter_lending"],
        records=[
            CheckRecord(name="cumulative_cfo_pat", outcome=CheckOutcome.FLAG, detail="0.42 vs 0.70"),
            CheckRecord(name="receivables_divergent", outcome=CheckOutcome.PASS),
            CheckRecord(name="promoter_lending", outcome=CheckOutcome.UNAVAILABLE,
                        reason="Schedule III row absent"),
        ],
        note_coverage=0.6, notes_undispositioned=["30"],
    )
    criteria = rehabilitation_criteria(
        derived, checklist, forensic=FORENSIC, policy=POLICY, as_of=AS_OF)
    metrics = [c.metric for c in criteria]

    assert "cum_cfo_pat" in metrics                 # the fired check must clear its policy floor
    assert "checks_unavailable" in metrics          # the undisclosed inputs must be disclosed
    assert "note_coverage" in metrics               # and the notes must be readable
    assert all(c.resolve_by > AS_OF for c in criteria)
    assert any(c.load_bearing for c in criteria)
    # a check that PASSED does not generate a rehabilitation criterion
    assert "receivables_divergent" not in metrics


def test_a_clean_but_unaffordable_company_gets_a_re_entry_trigger(store):
    """A forensically spotless company withheld purely on maths must still state its exit route.

    Without this the P2 symmetry gate would refuse to publish the `QUALITY_WRONG_PRICE` note that
    REPORT_ARCHITECTURE §2 explicitly calls for.
    """
    from firm.core.compute.multibagger import feasibility_gate

    derived = _derived(store)
    checklist = VerifiedCleanChecklist(
        expected_checks=["cumulative_cfo_pat"],
        records=[CheckRecord(name="cumulative_cfo_pat", outcome=CheckOutcome.PASS)],
        note_coverage=1.0,
    )
    # nothing fired and nothing is missing, so the only reason to withhold is the funding maths
    assert rehabilitation_criteria(
        derived, checklist, forensic=FORENSIC, policy=POLICY, as_of=AS_OF) == []

    gate = feasibility_gate(
        g_required=0.258, roic=0.204, self_fund_ceiling=1.0, high_quality_ceiling=0.6,
        debt_capacity_available=True, thesis_allows_dilution=False)
    criteria = rehabilitation_criteria(
        derived, checklist, forensic=FORENSIC, policy=POLICY, as_of=AS_OF,
        feasibility=gate, self_fund_ceiling=1.0)

    assert len(criteria) == 1
    trigger = criteria[0]
    assert trigger.metric == "roic_latest" and trigger.load_bearing
    assert trigger.threshold == 0.258            # the ROIC at which the target growth self-funds
    assert trigger.resolve_by > AS_OF
