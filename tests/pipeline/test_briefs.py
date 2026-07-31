"""Each agent is shown the evidence its own mandate needs (ADR-0038).

THE REGRESSION THESE PIN DOWN
Every agent used to receive a byte-identical payload. It was invisible because the three Phase-2 agents
genuinely do share their inputs — the bug only appeared when the roster grew, and it appeared as five
agents quietly answering from nothing. So the tests here are written against the *mechanism*: that a
brief is built from the roster's own declarations, that an absent input is stated rather than omitted,
and that two agents with different mandates cannot end up with the same brief.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from firm.adapters.india.shareholding import ShareholdingSummary
from firm.adapters.india.transcripts import Exchange, Quote, Speaker, TranscriptRead
from firm.core.compute import quality
from firm.core.config import REPO_ROOT
from firm.core.ingest.documents import DocumentIngest, ShareholdingIngest, TranscriptIngest
from firm.core.orchestrator.roster import load_roster
from firm.core.pipeline import derive as D
from firm.core.pipeline.briefs import (
    EVIDENCE_BUILDERS,
    EvidenceBundle,
    UnknownPrerequisiteError,
    build_brief,
    build_briefs,
)
from firm.core.pipeline.checks import CheckEvaluation
from firm.core.pipeline.deep_dive import agent_requirements, build_packets
from firm.core.report.assemble import NotesReview
from tests.conftest import AS_OF, clean_series, seed_store


def _bundle(store, documents=None, peers=None):
    seed_store(store, "ACME", clean_series())
    derived = D.derive_metrics(D.load_company_facts(store, "ACME", AS_OF))
    return EvidenceBundle(
        ticker="ACME", as_of=AS_OF, derived=derived,
        evaluation=CheckEvaluation(records=(), metrics=quality.ForensicMetrics(), expected=()),
        screen=quality.ForensicScreenResult(quality.ForensicVerdict.PASS, ()),
        feasibility=None, models=(), notes=NotesReview(), documents=documents, peers=peers,
    )


def _documents() -> DocumentIngest:
    call = TranscriptRead(
        source="acme-q2.pdf", held_on=date(2025, 11, 12), period="FY26Q2",
        management=(Speaker("Kirat Patel", "Executive Director"),),
        analysts=("Nirav Jamduia",),
        exchanges=(Exchange("Nirav Jamduia", "What is capacity?", "Kirat Patel",
                            "We do not disclose that.", 4),),
        quotes=(Quote("Kirat Patel", "We expect commissioning in the first quarter of 2026-27.", 5,
                      "guidance"),),
        complete=True,
    )
    return DocumentIngest(
        shareholding=(
            ShareholdingIngest(
                file="shp-q2.pdf", period="FY26Q2", as_on=date(2025, 9, 30),
                summary=ShareholdingSummary(
                    located=True, promoter_pct=72.03, public_pct=27.97, pledged=False,
                    as_on="2025-09-30", as_on_basis="stated", page=3),
                fact_ids=("SHP-FY26Q2:ownership:promoter_pct:FY26Q2",),
            ),
        ),
        transcripts=(TranscriptIngest("acme-q2.pdf", date(2025, 11, 12), call),),
    )


def test_every_prerequisite_the_roster_can_name_has_an_evidence_builder():
    """A roster that plans an agent whose inputs nobody assembles is the original bug, restated."""
    named = {name for entry in load_roster() for name in entry.evidence}
    missing = sorted(named - set(EVIDENCE_BUILDERS))
    assert not missing, (
        f"config/roster.yaml names prerequisites with no builder in briefs.py: {missing}. Those agents "
        "would be planned and then run blind."
    )


def test_an_unknown_prerequisite_fails_loudly_rather_than_thinning_the_brief(store):
    with pytest.raises(UnknownPrerequisiteError, match="insider_trades"):
        build_brief(("financials", "insider_trades"), _bundle(store))


def test_an_absent_input_is_stated_with_the_mandate_it_blocks_and_what_to_do(store):
    """Omitting it would ask the agent to notice an absence. Models fill absences; they do not notice them."""
    brief = build_brief(("shareholding", "prices"), _bundle(store))

    prices = brief["prices"]
    assert prices["status"] == "UNAVAILABLE"
    assert "days-to-exit" in prices["blocks"]
    assert "null" in prices["instruction"]
    # ADR-0019: the firm's own gap must never be scored against the company
    assert "not the company's disclosure" in prices["whose_gap"]

    # and with no documents ingested, shareholding is absent the same explicit way
    assert brief["shareholding"]["status"] == "UNAVAILABLE"


def test_the_ownership_agent_receives_the_promoter_series_and_the_tri_state_pledge(store):
    brief = build_brief(("shareholding", "pledge"), _bundle(store, documents=_documents()))

    quarters = brief["shareholding"]["quarters"]
    assert quarters[0]["promoter_pct"] == 72.03
    assert quarters[0]["fact_ids"], "a filed figure must arrive with the fact id that cites it"

    pledge = brief["pledge"]
    assert pledge["history"][0]["pledged"] is False
    # the distinction ADR-0027 exists to protect: answered-No is a finding, unlocated is not
    assert "THREE STATES" in pledge["how_to_use"]
    assert pledge["quarters_answered"] == 1


def test_the_transcript_agent_receives_quotes_attributed_to_a_speaker_and_a_page(store):
    brief = build_brief(("transcripts",), _bundle(store, documents=_documents()))
    call = brief["transcripts"]["calls"][0]

    assert call["period"] == "FY26Q2" and call["held_on"] == "2025-11-12"
    assert call["analysts_present"] == ["Nirav Jamduia"]
    assert call["guidance"][0]["speaker"] == "Kirat Patel"
    assert call["guidance"][0]["page"] == 5
    assert call["questions_met_with_a_refusal"][0]["analyst"] == "Nirav Jamduia"
    # Law 1's most tempting failure: the brief carries the words, never a number derived from them
    assert "do not convert any statement into a number" in brief["transcripts"]["how_to_use"]


def test_two_agents_with_different_mandates_do_not_get_the_same_brief(store):
    """The one-line statement of the whole defect."""
    bundle = _bundle(store, documents=_documents())
    briefs = build_briefs(agent_requirements(("transcript_analyst", "ownership_flows_analyst")), bundle)

    assert briefs["transcript_analyst"] != briefs["ownership_flows_analyst"]
    assert "transcripts" in briefs["transcript_analyst"]
    assert "shareholding" in briefs["ownership_flows_analyst"]
    assert "transcripts" not in briefs["ownership_flows_analyst"]


def test_the_evidence_reaches_the_rendered_packet_and_not_just_the_brief(store):
    """On the Claude-in-the-loop path the packet file IS the agent's world (ADR-0010)."""
    bundle = _bundle(store, documents=_documents())
    agents = ("transcript_analyst", "forensic_accountant")
    briefs = build_briefs(agent_requirements(agents), bundle)
    packets = build_packets(
        {"ticker": "ACME", "rules": []}, agents_dir=REPO_ROOT / "agents", repo_root=REPO_ROOT,
        agents=agents, briefs=briefs,
    )

    transcript_user = packets["transcript_analyst"][2]
    forensic_user = packets["forensic_accountant"][2]
    assert "commissioning in the first quarter of 2026-27" in transcript_user
    assert "commissioning in the first quarter of 2026-27" not in forensic_user
    assert "your_evidence" in transcript_user


def test_uses_widens_the_brief_without_gating_the_agent():
    """`management_analyst` reads the promoter series but must not be SKIPPED when it is missing.

    Gating a governance read on a secondary input would silence the entire section over shareholding —
    the same over-correction as blaming a company for the firm's own missing extractor.
    """
    entry = {e.name: e for e in load_roster()}["management_analyst"]
    assert "shareholding" in entry.uses and "shareholding" not in entry.requires
    assert "shareholding" in entry.evidence
    assert entry.missing(("financials", "guidance")) == ()


def test_a_brief_is_json_serialisable_because_that_is_how_an_agent_receives_it(store):
    brief = build_brief(("shareholding", "transcripts", "prices"),
                        _bundle(store, documents=_documents()))
    assert json.loads(json.dumps(brief, default=str))
