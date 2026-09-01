"""Persistent per-company memory, and the leak it must never spring (ADR-0079, SPEC §7.4).

`memory/company_notes/{ticker}.md` records what the firm concluded about a company, so a re-run starts
from that rather than re-deriving it — and so an agent can be confronted with a verdict the firm
reached before, including one it now disagrees with.

THE TEST THAT MATTERS MOST is the point-in-time one. The golden set replays historical `as_of` dates.
A notes file that let a 2026 conclusion be read during a 2019 replay would hand every replay the
answer, and the eval would measure the firm's ability to read its own notes while reporting it as
foresight. That is the single most expensive bug this file could contain, because the result would look
like success.
"""

from __future__ import annotations

from datetime import date

from firm.core.monitoring.company_notes import (
    append_run,
    notes_path,
    read_notes,
    render_entry,
)
from firm.core.pipeline import derive as D
from firm.core.pipeline.deep_dive import run_deep_dive
from tests.conftest import AS_OF, clean_answers, clean_series, filing_for, seed_store
from tests.pipeline.test_valuation_wiring import valuable_series


def _published(store, tmp_path, ticker="ACME", as_of=AS_OF):
    seed_store(store, ticker, valuable_series())
    return run_deep_dive(store, ticker, as_of, answers=clean_answers(ticker),
                         filing=filing_for(ticker), company_name=f"{ticker} Limited",
                         reports_root=tmp_path, write=True, memory_root=tmp_path)


# ---- the point-in-time rule ------------------------------------------------------------------------
def test_a_later_conclusion_is_invisible_to_an_earlier_replay(store, tmp_path):
    """The leak that would make the golden set measure the wrong thing entirely."""
    result = _published(store, tmp_path)                       # written at AS_OF (2026-07-30)
    assert notes_path("ACME", tmp_path).exists()

    assert read_notes("ACME", tmp_path, date(2019, 3, 31)) == []
    assert read_notes("ACME", tmp_path, AS_OF)                 # visible at its own date
    assert read_notes("ACME", tmp_path, date(2030, 1, 1))      # and after it
    assert result.report.run_id in read_notes("ACME", tmp_path, AS_OF)[0].run_id


def test_entries_are_returned_oldest_first(store, tmp_path):
    _published(store, tmp_path, as_of=date(2026, 7, 30))
    entries = read_notes("ACME", tmp_path, date(2030, 1, 1))
    assert entries == sorted(entries, key=lambda e: (e.as_of, e.run_id))


def test_an_unread_company_has_no_memory_rather_than_an_error(tmp_path):
    assert read_notes("NOBODY", tmp_path, AS_OF) == []


# ---- append-only, idempotent -----------------------------------------------------------------------
def test_the_same_run_is_not_recorded_twice(store, tmp_path):
    """A re-run with identical inputs produces an identical run_id (Law 5); a memory that duplicates
    itself on every replay stops being readable and becomes noise."""
    first = _published(store, tmp_path)
    before = notes_path("ACME", tmp_path).read_text()
    append_run(first.report, tmp_path)
    assert notes_path("ACME", tmp_path).read_text() == before


def test_the_file_says_what_it_is_and_is_not(store, tmp_path):
    _published(store, tmp_path)
    text = notes_path("ACME", tmp_path).read_text()
    assert "not evidence" in text
    assert "nothing here carries a fact id" in text
    assert "filtered by `as_of`" in text


# ---- what an entry records -------------------------------------------------------------------------
def test_an_entry_records_the_verdict_the_flags_and_what_the_firm_staked_itself_on(store, tmp_path):
    result = _published(store, tmp_path)
    entry = render_entry(result.report)
    assert result.report.outcome.value in entry
    assert result.report.verdict.value in entry
    assert "Flagged:" in entry and "Could not evaluate:" in entry
    if result.report.kill_criteria:
        assert "Staked on" in entry
    if result.report.management_questions:
        assert "Asked of management" in entry


def test_a_degraded_report_is_still_remembered(store, tmp_path, monkeypatch):
    """A withheld verdict is still something the firm decided, and it should face that next time."""
    from firm.core.pipeline import deep_dive as dd
    from firm.core.report import publish as pub
    from firm.core.validators.publication import PublicationViolation

    def refuse(report, **kwargs):
        return [PublicationViolation("P2_asymmetric", "thesis", "forced for the test")]

    monkeypatch.setattr(dd, "validate_report", refuse)
    monkeypatch.setattr(pub, "validate_report", refuse)

    result = _published(store, tmp_path, ticker="BLOCKED")
    assert result.degraded
    assert read_notes("BLOCKED", tmp_path, AS_OF)


# ---- the agents see it, and cannot lean on it ------------------------------------------------------
def test_prior_conclusions_reach_the_agent_payload_labelled_as_not_evidence(store, tmp_path):
    from firm.core.compute.quality import ForensicMetrics, ForensicScreenResult, ForensicVerdict
    from firm.core.pipeline.checks import CheckEvaluation
    from firm.core.pipeline.deep_dive import agent_facts_payload
    from firm.core.report.assemble import NotesReview

    _published(store, tmp_path)
    prior = read_notes("ACME", tmp_path, AS_OF)
    facts = D.load_company_facts(store, "ACME", AS_OF)

    payload = agent_facts_payload(
        D.derive_metrics(facts), CheckEvaluation((), ForensicMetrics(), ()),
        ForensicScreenResult(ForensicVerdict.PASS, False, []), None, [], NotesReview(),
        prior_notes=prior)

    block = payload["prior_conclusions"]
    assert len(block["entries"]) == len(prior) == 1
    assert "not evidence" in block["rule"] and "Do not " in block["rule"]


def test_a_company_with_no_history_gets_an_empty_block_not_a_missing_key(store, tmp_path):
    """An absent key would read to an agent as "this question was not asked"."""
    from firm.core.compute.quality import ForensicMetrics, ForensicScreenResult, ForensicVerdict
    from firm.core.pipeline.checks import CheckEvaluation
    from firm.core.pipeline.deep_dive import agent_facts_payload
    from firm.core.report.assemble import NotesReview

    seed_store(store, "FRESH", clean_series())
    facts = D.load_company_facts(store, "FRESH", AS_OF)
    payload = agent_facts_payload(
        D.derive_metrics(facts), CheckEvaluation((), ForensicMetrics(), ()),
        ForensicScreenResult(ForensicVerdict.PASS, False, []), None, [], NotesReview())
    assert payload["prior_conclusions"]["entries"] == []
