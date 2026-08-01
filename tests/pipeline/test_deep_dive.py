"""Tests for the Phase-2 orchestration surface: run identity, model shape, packets, and answers.

The end-to-end verdict behaviour lives in `tests/test_phase2_e2e.py`; this file covers the seams a caller
touches — the run id, the detection inputs, and the Claude-in-the-loop packet/answer round trip (ADR-0010).
"""

from __future__ import annotations

import json

import pytest

from firm.core.agents.loader import load_agent
from firm.core.compute.quality import ForensicMetrics, ForensicScreenResult, ForensicVerdict
from firm.core.config import REPO_ROOT, load_thresholds, report_policy
from firm.core.pipeline import derive as D
from firm.core.pipeline.checks import CheckEvaluation
from firm.core.pipeline.deep_dive import (
    PHASE2_AGENTS,
    agent_facts_payload,
    build_packets,
    compute_run_id,
    feasibility_at_target,
    read_answers,
    run_deep_dive,
    statement_shape,
    write_packets,
)
from firm.core.report.assemble import NotesReview
from tests.conftest import AS_OF, clean_answers, clean_series, seed_store


def _derived(store, ticker="ACME", series=None, periods=None):
    seed_store(store, ticker, series or clean_series(), **({"periods": periods} if periods else {}))
    facts = D.load_company_facts(store, ticker, AS_OF)
    return facts, D.derive_metrics(facts)


def test_run_id_changes_with_the_inputs_and_the_agent_versions(store):
    facts, _ = _derived(store, "ACME")
    specs = [load_agent(REPO_ROOT / "agents" / f"{name}.md") for name in PHASE2_AGENTS]

    base = compute_run_id("ACME", AS_OF, specs, facts.all_fact_ids())
    assert base.startswith(AS_OF.isoformat())
    assert base == compute_run_id("ACME", AS_OF, specs, facts.all_fact_ids())          # idempotent
    assert base != compute_run_id("ACME", AS_OF, specs, facts.all_fact_ids()[:-1])     # fewer facts
    assert base != compute_run_id("OTHER", AS_OF, specs, facts.all_fact_ids())         # other company


def test_statement_shape_leaves_undisclosed_gross_margin_as_none(store):
    """A zero would manufacture a TRADER tag out of missing data (models.detect_models contract)."""
    facts, derived = _derived(store, "ACME")
    shape = statement_shape(facts, derived)
    assert shape.gross_margin is None
    assert shape.ppe_to_assets == pytest.approx(700 / 900)
    assert shape.inventory_to_assets == 0.0          # not in the screener feed


def test_statement_shape_is_empty_without_usable_facts(store):
    facts, derived = _derived(store, "GHOST", {"pnl:Sales": [1.0]})
    assert statement_shape(facts, derived).revenue_to_assets == 0.0


def test_feasibility_is_none_when_roic_is_not_derivable(store):
    series = clean_series()
    del series["balance_sheet:Reserves"]             # invested capital incomputable
    _, derived = _derived(store, "NOROIC", series)
    assert derived.get("roic_latest") is None
    assert feasibility_at_target(derived, report_policy(), load_thresholds()["multibagger"]) is None


def test_packets_carry_the_computed_facts_and_the_schema(store):
    _, derived = _derived(store, "ACME")
    payload = agent_facts_payload(
        derived, CheckEvaluation((), ForensicMetrics(), ()),
        ForensicScreenResult(ForensicVerdict.PASS, False, []), None, [], NotesReview())
    packets = build_packets(payload, agents_dir=REPO_ROOT / "agents", repo_root=REPO_ROOT)

    assert set(packets) == set(PHASE2_AGENTS)
    spec, system, user = packets["forensic_accountant"]
    assert spec.version                                        # prompts are versioned (Law 6)
    assert "Numbers over adjectives" in system                 # house style is the system prompt
    assert "cum_cfo_pat" in user and "[fact:derived:cum_cfo_pat]" in user
    assert "DO NOT alter or invent numbers" in user
    assert "ForensicAccountantOutput" in user or "veto" in user   # the schema travels with the packet


def test_packet_payload_names_every_unavailable_metric(store):
    series = clean_series()
    del series["cashflow:Cash from Operating Activity"]
    _, derived = _derived(store, "NOCASH", series)
    payload = agent_facts_payload(
        derived, CheckEvaluation((), ForensicMetrics(), ()),
        ForensicScreenResult(ForensicVerdict.PASS, False, []), None, [], NotesReview())
    assert "cum_cfo_pat" in payload["metrics_unavailable"]
    assert payload["business_models_detected"] == ["none matched — universal checks only"]


def _register_guidance(store, ticker):
    """One transcript with a guided range, dated well before AS_OF, ids deterministic."""
    from firm.adapters.india.transcripts import GuidanceStatement, GuidanceValue, TranscriptSummary
    from firm.core.ingest.transcripts import register_transcript

    return register_transcript(store, ticker, "call.pdf", TranscriptSummary(
        located=True, call_date="2025-05-12", cover_date="2025-05-16",
        period="Q4FY25", period_basis="stated",
        guidance=(GuidanceStatement(
            page=16, quote="So, we expect double digit growth in next year around 10% to 15%.",
            kind="statement", topic="volume_growth",
            values=(GuidanceValue(10.0, "pct"), GuidanceValue(15.0, "pct")),
        ),),
    ))


def test_payload_carries_guidance_as_quotes_with_citable_ids(store):
    _, derived = _derived(store, "ACME")
    _register_guidance(store, "ACME")
    guidance = store.query_metric_prefix("ACME", "guidance:", AS_OF)
    payload = agent_facts_payload(
        derived, CheckEvaluation((), ForensicMetrics(), ()),
        ForensicScreenResult(ForensicVerdict.PASS, False, []), None, [], NotesReview(),
        guidance=guidance)

    rows = payload["management_guidance"]
    assert [r["value"] for r in rows] == [10.0, 15.0]
    assert all(r["topic"] == "volume_growth" and "double digit" in r["quoted"] for r in rows)
    assert rows[1]["cite_as"].startswith("[fact:TRN-Q4FY25-call.pdf:guidance_volume_growth:")


def test_an_agent_can_cite_managements_guided_figure(store):
    """The whole point of registration (ADR-0035/0036): a quoted guidance number passes the citation
    gate because the fact is real and the value matches — an agent received its own evidence."""
    seed_store(store, "ACME", clean_series())
    result = _register_guidance(store, "ACME")
    answers = clean_answers("ACME", business_analyst={
        "narrative": "Management has guided volume growth toward 15% "
                     f"[fact:{result.fact_ids[1]}] on the Q4FY25 call; this note weighs that "
                     "promise as data about management, not the business.",
    })
    run = run_deep_dive(store, "ACME", AS_OF, answers=answers, write=False)
    assert run.report is not None  # the citation survived the gate; a fake id or value would have raised


def test_an_agent_can_cite_a_peers_figure(store):
    """`sector_analyst`'s claims are relative ones, so the peer's number has to be citable too."""
    seed_store(store, "ACME", clean_series())
    seed_store(store, "RIVAL", clean_series(), periods=("FY21", "FY22", "FY23", "FY24", "FY25"),
               doc_id="ar-RIVAL", grade="A")
    answers = clean_answers("ACME", business_analyst={
        "narrative": "The peer turned over 1000.0 crore [fact:peer:RIVAL:sales:FY25] in the last year "
                     "both companies have filed, which frames the scale question this note discusses.",
    })
    run = run_deep_dive(store, "ACME", AS_OF, answers=answers, peers=["RIVAL"], write=False)
    assert run.report is not None


def test_the_peer_block_reaches_the_packet_with_its_periods(store):
    _, derived = _derived(store, "ACME")
    seed_store(store, "RIVAL", clean_series(), periods=("FY21", "FY22", "FY23", "FY24", "FY25"),
               doc_id="ar-RIVAL", grade="A")
    from firm.core.pipeline.peers import load_peer_comparisons

    comparisons = load_peer_comparisons(store, "ACME", ["RIVAL"], AS_OF)
    payload = agent_facts_payload(
        derived, CheckEvaluation((), ForensicMetrics(), ()),
        ForensicScreenResult(ForensicVerdict.PASS, False, []), None, [], NotesReview(),
        peers=comparisons)

    block = payload["peer_comparison"][0]
    assert block["peer"] == "RIVAL"
    sales = next(m for m in block["metrics"] if m["metric"] == "sales")
    # ACME has FY26; RIVAL stops at FY25. The row must be FY25 on BOTH sides, never FY26 vs FY25.
    assert sales["period"] == "FY25"
    assert sales["ACME"]["value"] == sales["RIVAL"]["value"] == 1000


def test_write_packets_then_read_answers_round_trips(store, tmp_path):
    """The no-API-key path: packets to disk, answered by hand, read back as provider output."""
    _, derived = _derived(store, "ACME")
    payload = agent_facts_payload(
        derived, CheckEvaluation((), ForensicMetrics(), ()),
        ForensicScreenResult(ForensicVerdict.PASS, False, []), None, [], NotesReview())
    written = write_packets(payload, tmp_path)

    assert len(written) == len(PHASE2_AGENTS)
    assert (tmp_path / "facts.json").exists()
    assert json.loads((tmp_path / "facts.json").read_text())["ticker"] == "ACME"
    assert "# SYSTEM" in (tmp_path / "business_analyst.md").read_text()

    assert read_answers(tmp_path) == {}                        # nothing answered yet
    answers = clean_answers("ACME")
    (tmp_path / "business_analyst.json").write_text(answers["business_analyst"])
    assert set(read_answers(tmp_path)) == {"business_analyst"}


def test_a_missing_answer_fails_fast_and_names_every_unstaffed_agent(store):
    """Pre-flight (ADR-0033), and it must run BEFORE any agent call.

    Previously an agent with no answer fell through to the configured provider — by default the local stub,
    whose output fails schema validation — so the run burned three retries per unstaffed agent and died with
    "agent output failed validation after 3 attempts", naming no agent and not hinting at the cause. Now
    that the roster grows with the build phase, planning more agents than the operator has answered is an
    ordinary situation and deserves a precise error.
    """
    seed_store(store, "ACME", clean_series())
    partial = {"business_analyst": clean_answers("ACME")["business_analyst"]}
    with pytest.raises(ValueError, match="no prepared answer for 2 planned agent") as caught:
        run_deep_dive(store, "ACME", AS_OF, answers=partial, write=False)

    message = str(caught.value)
    assert "financial_statement_analyst" in message and "forensic_accountant" in message
    assert "firm packets" in message          # the remedy, not just the complaint
    assert "lower --phase" in message


def test_write_false_returns_the_full_result_without_touching_disk(store, tmp_path):
    """A caller must be able to inspect a run — verdict, checklist, violations — before publishing it."""
    seed_store(store, "DRYRUN", clean_series())
    result = run_deep_dive(
        store, "DRYRUN", AS_OF, answers=clean_answers("DRYRUN"),
        reports_root=tmp_path, write=False)
    assert result.published is False and result.markdown_path is None
    assert result.report.verdict.value == "INSUFFICIENT_DISCLOSURE"   # screener-only run
    assert result.publication_violations == ()                        # it *would* have shipped
    assert list(tmp_path.iterdir()) == []
