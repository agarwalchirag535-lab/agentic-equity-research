"""A full eight-agent run: everyone who ran reaches the report, and nobody else is spoken for (ADR-0040).

THE BUG AT THE CENTRE OF THIS FILE
`_narration` read three agents by name. When the roster grew to eight, the other five produced validated,
cited, schema-conformant output that was then dropped on the floor — everything except their
`disconfirming_search` and `open_questions`.

The sharp end of it was the Management section, which was a hardcoded string:

    "No management or governance assessment is made in this report: `management_analyst`,
     `transcript_analyst` and `ownership_flows_analyst` are Phase 3 agents and did not run."

printed verbatim into reports where all three HAD run and had findings. A report that misstates the
firm's own coverage is the inward-facing version of exactly what the coverage-gap machinery exists to
prevent, and no validator could catch it because the sentence is grammatical, hedged and false.
"""

from __future__ import annotations

import pytest

from firm.core.report.render import render_markdown
from tests.conftest import AS_OF, agent_answer, clean_answers, clean_series, filing_for, seed_store

from firm.core.pipeline.deep_dive import run_deep_dive

#: The five agents the roster added, with a narrative each so the report has something to lose.
_PHASE3_EXTRAS = {
    "macro_strategist": {
        "cycle_position": "mid-cycle for specialty chemicals; the China restart is the swing factor",
    },
    "unit_economics_analyst": {
        "unit_definition": "one tonne of amine capacity at a named plant",
        "units_today": None, "units_plausible_in_7y": None,
        "contribution_margin_per_unit": None, "payback_years": None,
    },
    "management_analyst": {
        "promise_delivery_score": None, "capital_allocation_grade": "B",
        "promoter_pledge_pct": None,
    },
    "transcript_analyst": {
        "guidance_drift": "Commissioning slipped one quarter across two consecutive calls; the wording "
                          "moved from a date to a range without the change being called out.",
        "dodged_questions": ["segment-wise realisation, declined twice by the CFO"],
        "tone_trace": ["FY25Q2 confident", "FY25Q4 hedged"],
    },
    "ownership_flows_analyst": {
        "smart_money_score": None, "days_to_exit_at_20pct_adv": None,
        "institutional_absence_read": "undiscovered rather than looked-and-passed, on the evidence read",
    },
}

_EIGHT = (
    "business_analyst", "financial_statement_analyst", "forensic_accountant",
    "macro_strategist", "unit_economics_analyst", "management_analyst",
    "transcript_analyst", "ownership_flows_analyst",
)


@pytest.fixture()
def eight_agent_run(store, tmp_path):
    seed_store(store, "ROSTERCO", clean_series(roic_boost=1.6))
    answers = clean_answers("ROSTERCO")
    for name, extra in _PHASE3_EXTRAS.items():
        answers[name] = agent_answer(
            name, "ROSTERCO", extra,
            narrative=f"{name} reporting: the computed table carries the figures; this note interprets "
                      "them without restating any number.",
        )
    return run_deep_dive(
        store, "ROSTERCO", AS_OF, answers=answers, agents=_EIGHT, filing=filing_for("ROSTERCO"),
        company_name="Rosterco Limited", reports_root=tmp_path, memory_root=tmp_path, write=True,
    )


def test_all_eight_agents_reach_the_published_report(eight_agent_run):
    result = eight_agent_run
    assert result.published, result.publication_violations
    assert set(result.report.agent_versions) == set(_EIGHT)


def test_the_report_never_says_an_agent_did_not_run_while_quoting_it(eight_agent_run):
    """The regression itself. This sentence was published over three agents' live findings."""
    markdown = render_markdown(eight_agent_run.report)

    assert "did not run" not in eight_agent_run.report.management_narrative
    assert "are Phase 3 agents" not in markdown
    # and the section is present because the agents that own it actually spoke
    assert "management_analyst" in eight_agent_run.report.management_narrative
    assert "transcript_analyst" in eight_agent_run.report.management_narrative


def test_every_agent_that_ran_is_quoted_and_attributed(eight_agent_run):
    """Five agents' narratives used to be discarded in full. Attribution is what makes that visible."""
    markdown = render_markdown(eight_agent_run.report)
    for name in _EIGHT:
        assert f"{name} reporting" in markdown or name in ("business_analyst",
                                                           "financial_statement_analyst",
                                                           "forensic_accountant"), name

    assert "## Sector, cycle and unit economics" in markdown
    assert "## Management and governance" in markdown


def test_a_section_whose_agents_all_sat_out_says_so_instead_of_going_blank(store, tmp_path):
    """The honest fallback still has to work — and only when it is true."""
    seed_store(store, "THREECO", clean_series(roic_boost=1.6))
    result = run_deep_dive(
        store, "THREECO", AS_OF, answers=clean_answers("THREECO"), filing=filing_for("THREECO"),
        company_name="Threeco Limited", reports_root=tmp_path, memory_root=tmp_path, write=True,
    )

    management = result.report.management_narrative
    assert "none of" in management and "ran" in management
    # absent, explicitly — never quietly clean (ADR-0027)
    assert "absent rather than clean" in management
