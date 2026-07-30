"""Smoke tests for the agent output contracts (Law 4)."""

from datetime import date

import pytest
from pydantic import ValidationError

from firm.schemas import AGENT_OUTPUTS, AgentOutputBase
from firm.schemas.agents import ForensicAccountantOutput


def test_all_14_agents_have_contracts_extending_base():
    assert len(AGENT_OUTPUTS) == 14
    assert all(issubclass(m, AgentOutputBase) for m in AGENT_OUTPUTS.values())


def test_forensic_output_constructs():
    out = ForensicAccountantOutput(
        agent="forensic_accountant", agent_version="1.0.0", ticker="ACME", as_of=date(2026, 7, 23),
        disconfirming_search="looked for offsetting related-party disclosures; found none",
        verdict="HARD_FAIL", flags=["cash_interest_inconsistent"], veto=True,
    )
    assert out.veto is True and out.verdict == "HARD_FAIL"
    assert out.open_questions == []  # empty is allowed but 'suspicious' per house style


def test_missing_required_field_is_rejected():
    with pytest.raises(ValidationError):
        ForensicAccountantOutput(  # missing disconfirming_search + verdict
            agent="forensic_accountant", agent_version="1.0.0", ticker="ACME", as_of=date(2026, 7, 23),
        )
