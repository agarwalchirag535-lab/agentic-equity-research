"""A real provider wraps its JSON; the envelope must not fail the run (ADR-0075).

The no-API-key path the owner depends on shells out to `claude -p`, and that CLI — like most chat
models asked for JSON — habitually returns a ```json fence, often with a line of preamble. Validating
the raw text alone rejected those replies for their punctuation rather than their content, burned all
three attempts and raised, so the firm's primary free path could break on formatting while the agent's
answer was correct.

What must NOT be loosened, and is asserted here: the extracted object still has to satisfy the schema,
and a reply with no valid object in it still fails. Tolerating an envelope is not tolerating an answer.
"""

from __future__ import annotations

import json

import pytest

from firm.core.agents.runner import AgentValidationError, candidate_payloads, run_agent
from firm.core.llm.provider import StaticProvider
from firm.schemas.agents import ForensicAccountantOutput

VALID = {
    "agent": "forensic_accountant", "agent_version": "1.0.0", "ticker": "ACME",
    "as_of": "2026-07-30", "observations": [], "inferences": [], "speculations": [],
    "open_questions": ["What is the cash yield?"],
    "disconfirming_search": "Looked for a cash-conversion break and found none.",
    "narrative": "Nothing in the readable rows contradicts the reported cash position.",
    "verdict": "PASS", "flags": [], "veto": False,
}


def _run(text: str) -> ForensicAccountantOutput:
    return run_agent(StaticProvider(text), system="s", user="u", model="m",
                     schema=ForensicAccountantOutput)


def test_a_bare_json_object_still_works():
    assert _run(json.dumps(VALID)).verdict == "PASS"


def test_a_fenced_object_is_accepted():
    assert _run(f"```json\n{json.dumps(VALID)}\n```").verdict == "PASS"


def test_a_preamble_and_a_trailing_remark_are_tolerated():
    reply = f"Here is my analysis:\n\n```json\n{json.dumps(VALID)}\n```\n\nLet me know if you need more."
    assert _run(reply).verdict == "PASS"


def test_an_unfenced_object_after_prose_is_found():
    assert _run(f"My answer follows.\n{json.dumps(VALID)}").verdict == "PASS"


def test_prose_with_no_object_still_fails_the_run():
    """The envelope is tolerated; a missing answer is not."""
    with pytest.raises(AgentValidationError):
        _run("I could not complete this analysis.")


def test_an_object_that_breaks_the_schema_still_fails():
    """Law 4 is untouched: unwrapping changes what is read, never what must be true of it."""
    broken = {**VALID, "veto": "not a boolean"}
    del broken["ticker"]
    with pytest.raises(AgentValidationError):
        _run(f"```json\n{json.dumps(broken)}\n```")


def test_the_outermost_object_wins_over_one_quoted_inside_it():
    """A JSON snippet the agent quotes in its own prose must not displace the real answer."""
    nested = {**VALID, "narrative": 'The filing shows {"cash": 0} in the note, which is unusual.'}
    assert _run(json.dumps(nested)).narrative.startswith("The filing shows")


def test_the_most_literal_reading_is_tried_first():
    """Order is the conservative direction: a reply that IS the object is never unwrapped further."""
    payloads = candidate_payloads('{"a": 1}')
    assert payloads[0] == '{"a": 1}'
    assert len(payloads) == 1          # no spurious duplicates for a bare object
