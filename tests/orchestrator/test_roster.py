"""The Phase-3 roster: who runs, in what order, and what a skip means (ADR-0030)."""

from __future__ import annotations

from firm.core.orchestrator.roster import RosterEntry, load_roster, plan_run
from firm.core.orchestrator.stages import Gate, Stage

#: What a run has today: a screener snapshot and an ingested annual report. Everything else — transcripts,
#: shareholding, pledge, peers, prices — is not ingested (see config/roster.yaml).
TODAY = ("financials", "filing", "segments")


def test_the_roster_is_ordered_by_pipeline_stage():
    roster = load_roster()
    stages = [e.stage.value for e in roster]
    assert stages == sorted(stages)
    assert {e.name for e in roster} >= {
        "business_analyst", "financial_statement_analyst", "forensic_accountant",
        "sector_analyst", "management_analyst", "thesis_synthesizer",
    }


def test_the_phase_2_three_still_run_on_what_we_have():
    plan = plan_run(load_roster(), available_inputs=TODAY, max_phase=2)
    assert plan.names == ("business_analyst", "financial_statement_analyst", "forensic_accountant")
    assert plan.coverage == 1.0                       # fully staffed for its phase


def test_phase_3_adds_the_agents_whose_inputs_exist_and_names_the_rest():
    """The honest result: unit_economics and macro can run, the management tier cannot."""
    plan = plan_run(load_roster(), available_inputs=TODAY, max_phase=3)

    assert "macro_strategist" in plan.names
    assert "unit_economics_analyst" in plan.names
    # Blocked on ingestion that does not exist — and each says exactly what is missing.
    blocked = {s.agent: s.missing_inputs for s in plan.skipped if s.missing_inputs}
    assert blocked["transcript_analyst"] == ("transcripts",)
    assert blocked["ownership_flows_analyst"] == ("shareholding", "pledge")
    assert blocked["sector_analyst"] == ("peers",)
    assert plan.coverage < 1.0


def test_a_skipped_agent_becomes_a_coverage_gap_phrased_against_the_firm(): 
    """ADR-0019: never charge a company for the firm's own missing extractor."""
    plan = plan_run(load_roster(), available_inputs=TODAY, max_phase=3)
    gaps = plan.disclosure_gaps()

    assert any("transcript_analyst did not run" in g for g in gaps)
    assert all("gap in our coverage, not in the company's disclosure" in g for g in gaps)


def test_build_order_is_enforced_rather_than_remembered():
    """A phase-3 run must not quietly recruit the phase-4 judgment tier."""
    plan = plan_run(load_roster(), available_inputs=TODAY, max_phase=3)
    assert "valuation_modeler" not in plan.names
    assert "thesis_synthesizer" not in plan.names

    reason = next(s.reason for s in plan.skipped if s.agent == "valuation_modeler")
    assert "phase 4" in reason
    # Out-of-phase skips are NOT coverage gaps: following the build order is not a failure to look.
    assert all("valuation_modeler" not in g for g in plan.disclosure_gaps())


def test_a_failed_gate_stops_the_stages_below_it():
    """Gate B is the deterministic forensic kill — nothing downstream should burn tokens."""
    plan = plan_run(
        load_roster(), available_inputs=TODAY, gates_passed={Gate.B: False}, max_phase=3,
    )
    assert plan.names == ()
    assert all("gate B did not pass" in s.reason for s in plan.skipped if s.agent == "business_analyst")
    # A gate C agent is stopped because B failed, not because its own gate was tested and failed.
    mgmt = next(s.reason for s in plan.skipped if s.agent == "management_analyst")
    assert "gate B did not pass" in mgmt and "gate C was never reached" in mgmt
    # A gate stop is also not a coverage gap — the funnel working is not the firm failing to look.
    assert plan.disclosure_gaps() == ()


def test_missing_returns_only_what_is_absent():
    entry = RosterEntry("x", Stage.DEEP_FINANCIALS, Gate.B, 3, ("financials", "transcripts"))
    assert entry.missing(("financials",)) == ("transcripts",)
    assert entry.missing(("financials", "transcripts")) == ()


def test_available_inputs_are_derived_from_the_documents_actually_ingested():
    """Four agents were called "blocked on data that does not exist" while 28 shareholding patterns and
    15 concall transcripts sat on the company's own website. Availability is now derived, not asserted."""
    from firm.core.orchestrator.roster import available_inputs_from

    manifest = {"documents": [
        {"doc_class": "annual_report"}, {"doc_class": "shareholding"}, {"doc_class": "transcript"},
    ]}
    inputs = available_inputs_from(manifest)
    # A shareholding pattern carries pledge as a COLUMN, so it satisfies both prerequisites.
    assert "shareholding" in inputs and "pledge" in inputs
    # Transcripts carry management's forward statements, which is what guidance means here.
    assert "transcripts" in inputs and "guidance" in inputs

    plan = plan_run(load_roster(), available_inputs=inputs, max_phase=3)
    assert {"management_analyst", "transcript_analyst", "ownership_flows_analyst"} <= set(plan.names)
    # sector_analyst still cannot run: a peer set is a different company's documents.
    assert "sector_analyst" not in plan.names


def test_an_empty_manifest_grants_nothing():
    from firm.core.orchestrator.roster import available_inputs_from

    assert available_inputs_from({"documents": []}) == ()
    assert available_inputs_from({}) == ()
