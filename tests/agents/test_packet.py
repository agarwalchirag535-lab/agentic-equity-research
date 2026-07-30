"""Tests for the agent prompt-packet assembler."""

from pathlib import Path

from firm.core.agents.loader import load_agent
from firm.core.agents.packet import build_packet, load_house_style
from firm.schemas.agents import ForensicAccountantOutput

REPO = Path(__file__).resolve().parents[2]


def test_load_house_style():
    style = load_house_style(REPO)
    assert "Numbers over adjectives" in style
    assert "provenance" in style.lower() or "fact_id" in style


def test_build_packet_includes_facts_and_schema():
    agent = load_agent(REPO / "agents" / "forensic_accountant.md")
    facts = {"cfo_pat_FY26": 2.01, "cumulative_cfo_pat": 1.71}
    schema_json = ForensicAccountantOutput.model_json_schema()
    system, user = build_packet(agent, facts, schema_json, load_house_style(REPO))

    assert "Numbers over adjectives" in system          # house style is the system prompt
    assert "absolute veto" in user.lower()               # agent mandate is in the user prompt
    assert "cumulative_cfo_pat" in user                  # computed facts embedded
    assert "verdict" in user                             # schema embedded
