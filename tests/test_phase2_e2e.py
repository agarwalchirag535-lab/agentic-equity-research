"""Phase-2 acceptance (SPEC §11): three agents, deep, on five companies — one of them a fraud pattern.

SPEC's acceptance test for this phase is: *"run on 5 companies including one known accounting fraud …
the forensic agent flags it; every number in all outputs passes the citation validator."* This file is
that test, offline and deterministic (agent answers are scripted, so what is under test is the pipeline
and the gates, not an LLM's mood).

The five are chosen to land on five different verdicts, because a pipeline that can only produce one
verdict has not been shown to discriminate:

  1. COMPOUNDER             — clean, self-funds the target growth
  2. QUALITY_WRONG_PRICE    — same business, ROIC too low to self-fund the target
  3. FORENSIC_CAUTION       — profit never becomes cash; receivables absorb the gap
  4. INSUFFICIENT_DISCLOSURE — screener-only run: most of the playbook cannot be evaluated
  5. WATCH                  — clean and high-return, but too little history to prove a thesis

Every published report also has to survive the P1/P2/P3 publication gates and the R1-R6 evidence-graph
invariants, so "published" in these assertions means "passed every blocking validator".
"""

from __future__ import annotations

import json

import pytest

from firm.core.monitoring.predictions import read_jsonl
from firm.core.pipeline.deep_dive import AgentDisciplineError, authored_texts, run_deep_dive
from firm.core.report.render import render_markdown
from firm.core.validators import citation
from firm.schemas.report import CheckOutcome, Verdict
from tests.conftest import (  # noqa: F401 - imported for the builders, not the fixture
    AS_OF,
    CLEAN_AR_PAGES,
    FRAUD_AR_PAGES,
    agent_answer,
    clean_answers,
    clean_series,
    filing_for,
    fraud_series,
    seed_store,
)


def _run(store, ticker, series, *, answers, filing=None, periods=None, tmp_path=None, company=None):
    seed_store(store, ticker, series, **({"periods": periods} if periods else {}))
    return run_deep_dive(
        store, ticker, AS_OF, answers=answers, filing=filing,
        company_name=company or f"{ticker} Limited",
        reports_root=tmp_path, write=tmp_path is not None,
        # Point the prediction ledger at the tmp dir: without this every run of the suite would append
        # synthetic test companies to the repo's real memory/predictions.jsonl and corrupt the
        # calibration record with theses the firm never published.
        memory_root=tmp_path,
    )


# ---- 1. COMPOUNDER --------------------------------------------------------------------------------
def test_clean_high_return_company_publishes_a_compounder_report(store, tmp_path):
    result = _run(store, "CLEANCO", clean_series(roic_boost=1.6),
                  answers=clean_answers("CLEANCO"), filing=filing_for("CLEANCO"), tmp_path=tmp_path)

    assert result.report.verdict is Verdict.COMPOUNDER, result.decision.rationale
    assert result.graph_violations == () and result.publication_violations == ()
    assert result.published and result.markdown_path.exists() and result.json_path.exists()
    # the run directory is reports/{TICKER}/{run_id}/ (REPORT_ARCHITECTURE §6)
    assert result.markdown_path.parent.name == result.run_id
    assert result.markdown_path.parent.parent.name == "CLEANCO"

    # a positive verdict carries dated, filing-resolvable kill criteria, one of them load-bearing (P2)
    assert len(result.report.kill_criteria) >= 3
    assert any(c.load_bearing for c in result.report.kill_criteria)
    assert all(c.resolve_by > AS_OF for c in result.report.kill_criteria)

    # the credibility backbone: passes are shown, not just failures
    outcomes = {r.name: r.outcome for r in result.report.checklist.records}
    assert outcomes["cumulative_cfo_pat"] is CheckOutcome.PASS
    assert outcomes["receivables_divergent"] is CheckOutcome.PASS
    assert "✅ pass" in render_markdown(result.report)


# ---- 2. QUALITY_WRONG_PRICE ------------------------------------------------------------------------
def test_clean_but_cannot_self_fund_the_target_is_withheld(store, tmp_path):
    result = _run(store, "LOWROIC", clean_series(roic_boost=1.0),
                  answers=clean_answers("LOWROIC"), filing=filing_for("LOWROIC"), tmp_path=tmp_path)

    assert result.report.verdict is Verdict.QUALITY_WRONG_PRICE, result.decision.rationale
    assert result.screen.verdict.value == "PASS"          # forensically clean — the maths is the problem
    assert result.feasibility is not None
    assert result.feasibility.required_reinvestment > 1.0
    # a withholding verdict must say what would reverse it (P2)
    assert result.report.rehabilitation_criteria
    assert result.published


# ---- 3. FORENSIC_CAUTION — the fraud pattern -------------------------------------------------------
def test_profit_that_never_becomes_cash_publishes_a_forensic_caution(store, tmp_path):
    answers = clean_answers("FRAUDCO", forensic_accountant={
        "verdict": "HARD_FAIL", "veto": True,
        "flags": ["cumulative_cfo_pat_low", "receivables_divergent"],
    })
    result = _run(store, "FRAUDCO", fraud_series(), answers=answers,
                  filing=filing_for("FRAUDCO", FRAUD_AR_PAGES), tmp_path=tmp_path)

    assert result.report.verdict is Verdict.FORENSIC_CAUTION, result.decision.rationale
    assert result.screen.hard_fail is True
    fired = {r.name for r in result.report.checklist.records if r.outcome is CheckOutcome.FLAG}
    assert "cumulative_cfo_pat" in fired          # ΣCFO/ΣPAT under the floor — the load-bearing tell
    assert "receivables_divergent" in fired       # the receivables absorbing the gap
    # P3: a caution must be reproducible by a third party and must not read as an accusation
    assert result.report.replication_notes
    assert result.publication_violations == ()
    assert result.published

    md = render_markdown(result.report)
    assert "🚩 flag" in md
    assert "FORENSIC_CAUTION" in md


def test_forensic_agent_cannot_narrate_past_a_deterministic_hard_fail(store):
    """The agent card forbids it; the pipeline must enforce it rather than trust the prompt."""
    answers = clean_answers("FRAUDCO2", forensic_accountant={
        "verdict": "PASS", "flags": [], "veto": False,      # contradicts a deterministic HARD_FAIL
    })
    with pytest.raises(AgentDisciplineError) as err:
        _run(store, "FRAUDCO2", fraud_series(), answers=answers,
             filing=filing_for("FRAUDCO2", FRAUD_AR_PAGES))
    assert "cannot be overturned" in str(err.value)


# ---- 4. INSUFFICIENT_DISCLOSURE --------------------------------------------------------------------
def test_screener_only_run_publishes_the_opacity_as_the_finding(store, tmp_path):
    """No annual report walked → most of the playbook cannot run → the gap IS the finding (ADR-0014)."""
    result = _run(store, "OPAQUE", clean_series(roic_boost=1.6),
                  answers=clean_answers("OPAQUE"), filing=None, tmp_path=tmp_path)

    assert result.report.verdict is Verdict.INSUFFICIENT_DISCLOSURE, result.decision.rationale
    assert result.evaluation.unavailable_share > 0.34
    assert result.notes.notes_total == 0 and result.notes.coverage == 0.0
    # every UNAVAILABLE carries a reason (P1) and is republished as an explicit gap
    unavailable = [r for r in result.report.checklist.records
                   if r.outcome is CheckOutcome.UNAVAILABLE]
    assert unavailable and all(r.reason.strip() for r in unavailable)
    assert result.report.unavailable_items
    # rehabilitation: disclose the inputs. It publishes — opacity withheld is opacity rewarded.
    assert result.report.rehabilitation_criteria
    assert result.published


# ---- 5. WATCH ------------------------------------------------------------------------------------
def test_short_history_company_is_watch_not_rejected(store, tmp_path):
    """ADR-0008: a short-history business is routed, never dropped — and never called a compounder."""
    short = {metric: values[-3:] for metric, values in clean_series(roic_boost=2.5).items()}
    result = _run(store, "YOUNGCO", short, answers=clean_answers("YOUNGCO"),
                  filing=filing_for("YOUNGCO"), periods=("FY24", "FY25", "FY26"), tmp_path=tmp_path)

    assert result.report.verdict is Verdict.WATCH, result.decision.rationale
    assert result.derived.years < 5
    assert result.published


# ---- the citation discipline the acceptance test names explicitly ---------------------------------
def test_every_number_in_every_agent_output_passes_the_citation_validator(store, tmp_path):
    """SPEC §11: "every number in all outputs passes the citation validator" — *all* outputs.

    Checks every string each agent authored, not just the narrative: the fields that carry a report's
    business description, its anti-thesis and its open questions are exactly where an invented figure
    would otherwise ride in unexamined.
    """
    result = _run(store, "CITECO", clean_series(roic_boost=1.6),
                  answers=clean_answers("CITECO"), filing=filing_for("CITECO"), tmp_path=tmp_path)

    known = {f"derived:{n}" for n in result.derived.values}
    known |= {f.fact_id for m in result.derived.values.values() for f in m.inputs}
    for output in result.outputs:
        for label, text in authored_texts(output):
            assert citation.validate(text, known) == [], f"{output.agent}.{label}: {text}"

    # and the check is not vacuous: it does look at the fields the report renders
    labels = {label for output in result.outputs for label, _ in authored_texts(output)}
    assert {"narrative", "disconfirming_search", "open_questions[1]"} <= labels
    assert "what_it_does" in labels                       # rendered as the business-model section
    assert "observations[1].text" in labels


def test_the_authored_text_walker_reaches_nested_schema_models():
    """Phase 3/4 agents carry nested models (`SectorScore.falsifier`, `ScenarioLine.name`). Covering them
    now means those agents inherit the citation gate instead of arriving with a hole in it."""
    from datetime import date

    from firm.schemas.agents import MacroStrategistOutput, SectorScore

    output = MacroStrategistOutput(
        agent="macro_strategist", agent_version="1.0.0", ticker="X", as_of=date(2026, 7, 30),
        disconfirming_search="looked", narrative="text", cycle_position="mid",
        sector_scores=[SectorScore(sector="chemicals", tailwind_score=0.2, horizon_years=5,
                                   falsifier="import parity collapses by 9999")],
    )
    labels = dict(authored_texts(output))
    assert "sector_scores[1].falsifier" in labels
    assert citation.validate(labels["sector_scores[1].falsifier"], set())[0].number == "9999"
    # structured provenance is not read as prose — a Citation is made of ids and versions full of digits
    assert not any(label.endswith(".fact_id") or ".citations" in label for label in labels)


@pytest.mark.parametrize(
    ("agent", "field", "value"),
    [
        # every one of these lands in the published report (§3 business model, §8 anti-thesis,
        # §10 open questions, §2 load-bearing points) and so must be citation-checked
        ("business_analyst", "what_it_does",
         "It holds 73.4% of the domestic amines market and earned 9,999 crore of revenue."),
        ("business_analyst", "moat",
         "Pricing power is worth about 45.6% of gross margin, sustained for 8 years."),
        ("financial_statement_analyst", "disconfirming_search",
         "I checked whether the 88.2% gross margin could be real and concluded it was."),
        ("forensic_accountant", "open_questions",
         ["The promoter sold 12.5% of the company last year and did not explain why."]),
    ],
)
def test_a_fabricated_number_in_any_rendered_agent_field_fails_the_run(store, agent, field, value):
    """The hole this closes: the first version of the citation gate read only `narrative` and the claim
    texts, so a figure invented in any other rendered field reached a published report unchecked."""
    answers = clean_answers("SMUGGLE")
    payload = json.loads(answers[agent])
    payload[field] = value
    answers[agent] = json.dumps(payload)

    with pytest.raises(AgentDisciplineError) as err:
        _run(store, "SMUGGLE", clean_series(roic_boost=1.6), answers=answers,
             filing=filing_for("SMUGGLE"))
    assert "no_citation" in str(err.value)
    assert field.split("[")[0] in str(err.value)


def test_an_uncited_number_in_agent_prose_fails_the_run(store):
    answers = clean_answers("UNCITED")
    bad = json.loads(answers["financial_statement_analyst"])
    bad["narrative"] = "Operating margin improved to 21.0% this year."      # no [fact:...] token
    answers["financial_statement_analyst"] = json.dumps(bad)

    with pytest.raises(AgentDisciplineError) as err:
        _run(store, "UNCITED", clean_series(roic_boost=1.6), answers=answers,
             filing=filing_for("UNCITED"))
    assert "no_citation" in str(err.value)


def test_an_agent_authored_number_fails_the_run(store):
    """Law 1: an agent filling a numeric field the compute layer did not produce is a build failure.

    The field under test used to be `working_capital_days`; it stopped being a valid example once the
    filing walk made the cash-conversion cycle derivable (ADR-0037), because it now has a computed
    source and an agent quoting it wrongly falls under the *arithmetic* check instead (tested below).
    `customer_concentration` needs the segment note, which nothing reads, so it is still a field an
    agent could only fill by inventing.
    """
    answers = clean_answers("MADEUP", business_analyst={"customer_concentration": 0.42})
    with pytest.raises(AgentDisciplineError) as err:
        _run(store, "MADEUP", clean_series(roic_boost=1.6), answers=answers,
             filing=filing_for("MADEUP"))
    assert "customer_concentration" in str(err.value)
    assert "Law 1" in str(err.value)


def test_an_agent_quoting_a_wrong_value_fails_the_arithmetic_check(store):
    answers = clean_answers("WRONGNUM", financial_statement_analyst={"cfo_to_ebitda": 0.99})
    with pytest.raises(AgentDisciplineError) as err:
        _run(store, "WRONGNUM", clean_series(roic_boost=1.6), answers=answers,
             filing=filing_for("WRONGNUM"))
    assert "cfo_to_ebitda" in str(err.value)


def test_a_citation_to_a_nonexistent_fact_fails_the_run(store):
    answers = clean_answers("FAKEFACT")
    bad = json.loads(answers["business_analyst"])
    bad["observations"][0]["citations"][0]["fact_id"] = "derived:invented_metric"
    bad["observations"][0]["text"] = "Cash conversion is fine [fact:derived:invented_metric]."
    answers["business_analyst"] = json.dumps(bad)

    with pytest.raises(AgentDisciplineError) as err:
        _run(store, "FAKEFACT", clean_series(roic_boost=1.6), answers=answers,
             filing=filing_for("FAKEFACT"))
    assert "unknown_fact_id" in str(err.value) or "unknown fact" in str(err.value)


def test_a_number_cited_to_a_real_fact_but_misquoted_fails_the_run(store):
    """The subtlest corruption: keep the citation, change the digits. The value check is what catches it."""
    answers = clean_answers("MISQUOTE")
    payload = json.loads(answers["forensic_accountant"])
    payload["narrative"] = (
        "Cumulative cash conversion is 0.42 [fact:derived:cum_cfo_pat], which would be a serious "
        "earnings-quality problem."
    )
    answers["forensic_accountant"] = json.dumps(payload)

    with pytest.raises(AgentDisciplineError) as err:
        _run(store, "MISQUOTE", clean_series(roic_boost=1.6), answers=answers,
             filing=filing_for("MISQUOTE"))
    assert "value_mismatch" in str(err.value)

    # ... and quoting it correctly (rounded) passes
    payload["narrative"] = (
        "Cumulative cash conversion is 1.11 [fact:derived:cum_cfo_pat], comfortably above the floor."
    )
    answers["forensic_accountant"] = json.dumps(payload)
    result = _run(store, "MISQUOTE2", clean_series(roic_boost=1.6), answers=answers,
                  filing=filing_for("MISQUOTE2"))
    assert "1.11 [fact:derived:cum_cfo_pat]" in result.report.forensic_narrative


# ---- run identity + point-in-time ----------------------------------------------------------------
def test_same_inputs_produce_the_same_run_id(store, tmp_path):
    first = _run(store, "IDEM", clean_series(roic_boost=1.6), answers=clean_answers("IDEM"),
                 filing=filing_for("IDEM"), tmp_path=tmp_path)
    second = run_deep_dive(
        store, "IDEM", AS_OF, answers=clean_answers("IDEM"), filing=filing_for("IDEM"),
        reports_root=tmp_path, write=False)
    assert first.run_id == second.run_id


def test_point_in_time_hides_a_filing_published_after_as_of(store):
    """Law 3 covers the document, not just its figures: an unpublished filing is not read at all.

    Run the same company as-of a date between the screener snapshot (1 Apr) and the annual report
    (15 Jun). The report's notes, Schedule III rows and receivables figures must all be absent — which
    also means the business model cannot be detected from inventory, so the run honestly falls back to the
    universal playbook and returns INSUFFICIENT_DISCLOSURE instead of a thesis.
    """
    from datetime import date

    seed_store(store, "PIT", clean_series(roic_boost=1.6))
    early = run_deep_dive(
        store, "PIT", date(2026, 5, 1), answers=clean_answers("PIT"),
        filing=filing_for("PIT"), write=False)     # the filing is disseminated 2026-06-15

    assert early.notes.notes_total == 0 and early.notes.scanned is False
    assert early.models == ()                                   # inventory unknown -> no model claimed
    # Stock-flow checks are UNIVERSAL (PC Jeweller taught this — a company matching no model must still
    # be asked the receivables question), so the check is EXPECTED but honestly UNAVAILABLE: its
    # receivables input does not exist before the filing publishes.
    early_outcomes = {r.name: r.outcome for r in early.evaluation.records}
    assert early_outcomes["receivables_divergent"] is CheckOutcome.UNAVAILABLE
    assert early.report.verdict is Verdict.INSUFFICIENT_DISCLOSURE

    # ... and as-of a date after dissemination the same filing IS read.
    later = run_deep_dive(
        store, "PIT", AS_OF, answers=clean_answers("PIT"), filing=filing_for("PIT"), write=False)
    assert later.notes.notes_total > 0
    later_outcomes = {r.name: r.outcome for r in later.evaluation.records}
    assert later_outcomes["receivables_divergent"] is not CheckOutcome.UNAVAILABLE


def test_a_published_report_logs_its_kill_criteria_to_the_prediction_ledger(store, tmp_path):
    """ADR-0023: the dated criteria stop being prose in a markdown file and become scoreable rows.

    Also pins the isolation that matters: the ledger goes where the caller says, never to the repo's real
    memory/ directory, or a test run would corrupt the calibration record with synthetic companies.
    """
    result = _run(store, "LEDGERCO", clean_series(roic_boost=1.6),
                  answers=clean_answers("LEDGERCO"), filing=filing_for("LEDGERCO"), tmp_path=tmp_path)

    assert result.published
    ledger = tmp_path / "predictions.jsonl"
    assert ledger.exists(), "a published report must log its predictions"
    rows = read_jsonl(ledger)
    assert {r.metric for r in rows} == {c.metric for c in result.report.kill_criteria}
    assert all(r.run_id == result.run_id and r.ticker == "LEDGERCO" for r in rows)
    assert any(r.load_bearing for r in rows)


def test_a_blocked_report_logs_nothing_because_it_was_never_a_forecast(store, tmp_path):
    """A run that fails a publication gate did not publish, so the firm never stood behind it.

    Logging it would let the calibration record fill with theses that were withheld.
    """
    result = _run(store, "NOPUBCO", clean_series(roic_boost=1.6),
                  answers=clean_answers("NOPUBCO"), filing=filing_for("NOPUBCO"), tmp_path=None)

    assert not result.published
    assert result.predictions == ()
    assert not (tmp_path / "predictions.jsonl").exists()
