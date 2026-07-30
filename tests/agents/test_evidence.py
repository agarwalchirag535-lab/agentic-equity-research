"""Tests for the agent-output → evidence-graph bridge (ADR-0021).

What is under test is the *judgment code makes about an agent's words*: what counts as load-bearing, what
counts as provenance, and what is rejected outright.
"""

from __future__ import annotations

from datetime import date

import pytest

from firm.core.agents.evidence import build_fragment, cap_load_bearing, merge_graphs
from firm.core.validators.evidence_graph import validate_graph
from firm.schemas._base import Claim
from firm.schemas.agents import BusinessAnalystOutput, FinancialStatementOutput
from firm.schemas.evidence import ClaimKind, ClaimStatus, SourceClass
from tests.conftest import AS_OF, agent_answer, cited_claim

KNOWN = {"derived:cum_cfo_pat", "derived:cfo_pat_latest", "derived:roic_latest"}


def _business_output(**extra) -> BusinessAnalystOutput:
    base = {"what_it_does": "Makes and sells amines.", "moat": None,
            "customer_concentration": None, "national_relevance": True}
    return BusinessAnalystOutput.model_validate_json(
        agent_answer("business_analyst", "ACME", {**base, **extra}))


def _financial_output() -> FinancialStatementOutput:
    return FinancialStatementOutput.model_validate_json(
        agent_answer("financial_statement_analyst", "ACME", {
            "incremental_roic": None, "cfo_to_ebitda": None, "fcf_to_pat": None,
            "working_capital_days": None,
        }))


def _fragment(output, *, min_confidence=0.6, max_load_bearing=3):
    return build_fragment(output, known_fact_ids=KNOWN, min_confidence=min_confidence,
                          max_load_bearing=max_load_bearing)


def test_claims_keep_the_epistemic_split_and_get_namespaced_ids():
    fragment = _fragment(_business_output())
    kinds = {cid: claim.kind for cid, claim in fragment.graph.claims.items()}
    assert kinds["business_analyst:observation:1"] is ClaimKind.OBSERVATION
    assert kinds["business_analyst:inference:1"] is ClaimKind.INFERENCE
    assert all(cid.startswith("business_analyst:") for cid in kinds)


def test_a_cited_claim_becomes_supported_evidence_with_provenance():
    fragment = _fragment(_business_output())
    claim = fragment.graph.claims["business_analyst:observation:1"]
    assert claim.status is ClaimStatus.SUPPORTED
    evidence = fragment.graph.evidence[claim.supporting[0]]
    assert evidence.asserts_number is True
    assert evidence.citation.fact_id == "derived:cum_cfo_pat"
    assert evidence.source_class is SourceClass.BINDING_FILING     # grade B
    assert "recompute with core/compute" in claim.replication


def test_an_unknown_fact_id_is_a_problem_not_a_silent_drop():
    output = _business_output()
    output.observations[0].citations[0].fact_id = "derived:invented"
    fragment = _fragment(output)
    assert not fragment.ok
    assert fragment.problems[0].fact_id == "derived:invented"
    # the claim survives but stands unsupported, so R1 will catch anyone leaning on it
    claim = fragment.graph.claims["business_analyst:observation:1"]
    assert claim.supporting == [] and claim.status is ClaimStatus.UNKNOWN


def test_speculation_is_never_load_bearing_however_confident():
    output = _business_output()
    output.speculations = [Claim.model_validate(cited_claim(
        "The promoter may be planning an acquisition [fact:derived:roic_latest].",
        "derived:roic_latest", kind="speculation", confidence=0.99))]
    fragment = _fragment(output)
    assert "business_analyst:speculation:1" not in fragment.load_bearing_claim_ids
    assert fragment.graph.claims["business_analyst:speculation:1"].load_bearing is False


def test_low_confidence_or_weak_grade_claims_are_not_promoted():
    weak_grade = _business_output()
    weak_grade.observations[0].citations[0].grade = "C"
    assert _fragment(weak_grade).load_bearing_claim_ids == ("business_analyst:inference:1",)

    low_confidence = _business_output()
    low_confidence.observations[0].confidence.value = 0.2
    low_confidence.inferences[0].confidence.value = 0.2
    assert _fragment(low_confidence).load_bearing_claim_ids == ()


def test_merge_converges_on_one_evidence_node_per_fact():
    fragments = [_fragment(_business_output()), _fragment(_financial_output())]
    graph = merge_graphs([f.graph for f in fragments])
    assert len(graph.claims) == 4                       # two claims from each agent
    assert set(graph.evidence) == {"ev:derived:cum_cfo_pat", "ev:derived:cfo_pat_latest"}
    assert validate_graph(graph, AS_OF) == []           # R1-R6 clean


def test_merge_refuses_to_overwrite_a_duplicate_claim_id():
    fragment = _fragment(_business_output())
    with pytest.raises(ValueError, match="duplicate claim id"):
        merge_graphs([fragment.graph, fragment.graph])


def test_cap_load_bearing_dedupes_identical_statements_across_agents():
    """Three agents restating one metric is one load-bearing point, not three."""
    fragments = [_fragment(_business_output()), _fragment(_financial_output())]
    graph = merge_graphs([f.graph for f in fragments])
    candidates = [cid for f in fragments for cid in f.load_bearing_claim_ids]
    assert len(candidates) == 4                          # two promoted per agent, same two statements

    kept = cap_load_bearing(graph, candidates, max_points=3)
    assert len(kept) == 2                                # duplicates collapsed by statement
    assert sum(claim.load_bearing for claim in graph.claims.values()) == 2


def test_cap_load_bearing_demotes_everything_outside_the_cap():
    fragment = _fragment(_business_output())
    graph = fragment.graph
    kept = cap_load_bearing(graph, list(fragment.load_bearing_claim_ids), max_points=1)

    assert len(kept) == 1
    assert sum(claim.load_bearing for claim in graph.claims.values()) == 1
    # the highest-confidence claim is the one that survives
    assert graph.claims[kept[0]].confidence.value == max(
        c.confidence.value for c in graph.claims.values() if c.confidence)


def test_lookahead_evidence_is_caught_by_r6():
    fragment = _fragment(_business_output())
    violations = validate_graph(fragment.graph, date(2026, 1, 1))   # before the citation's published_at
    assert violations and all(v.rule == "R6_lookahead" for v in violations)
