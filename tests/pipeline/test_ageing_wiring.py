"""The Schedule III ageing schedules, from the printed page to a published finding (ADR-0039).

ADR-0038 built the parser and said so plainly in its own text: the tables were parsed and consumed by
nothing. That is the failure this module is here to make impossible to reintroduce — a parser with no
caller passes every test it has and changes no verdict, which is indistinguishable from not having
written it. So the assertions here follow the figure, not the function: a number printed in a filing's
ageing table has to arrive as a grade-A fact, become a derived share with provenance, decide a check,
disposition a note, and reach the packet an agent can quote from.
"""

from __future__ import annotations

from datetime import date

from pytest import approx

from firm.core.compute.models import BusinessModel, build_playbook
from firm.core.config import (
    ageing_thresholds,
    load_thresholds,
    model_forensic_thresholds,
    model_playbooks,
    universal_forensic_thresholds,
)
from firm.core.pipeline import derive as D
from firm.core.pipeline.checks import AgeingEvidence, ExternalInputs, evaluate_checks
from firm.core.pipeline.deep_dive import ageing_series
from firm.core.pipeline.filing import disposition_notes, register_ageing_facts, walk_filing
from firm.schemas.report import CheckOutcome
from tests.conftest import (
    AS_OF,
    CLEAN_AR_PAGES,
    FRAUD_AR_PAGES,
    clean_series,
    filing_for,
    fraud_series,
    seed_store,
)

TH = load_thresholds()
PB = model_playbooks()

#: The real Alkyl Amines FY26 capital-work-in-progress schedule, verbatim from the filing (ADR-0038).
#: ₹16.29cr of it sits in projects the company reports as temporarily suspended — the finding this whole
#: chain exists to publish, and the reason this fixture is the real table rather than a convenient one.
ALKYL_CWIP_PAGE = """3.3a. Ageing of Capital Work in progress as on March 31, 2026 ` In Lakhs
Particulars Amounts in capital work-in-progress for a period of
Less than 1 year 1-2 years 2-3 years More than 3 years Total
Projects in progress  9,585.08  1,195.46  280.17  358.25  11,418.96
Projects temporarily suspended  13.33  292.11  1,256.54  67.18  1,629.16
Total  9,598.41  1,487.57  1,536.71  425.43  13,048.12
"""


def _run(store, ticker, series, pages, models):
    """Seed the screener snapshot, walk a filing over ``pages``, evaluate. Returns everything."""
    seed_store(store, ticker, series)
    walk = walk_filing(store, ticker, filing_for(ticker, pages))
    facts = D.load_company_facts(store, ticker, AS_OF)
    derived = D.derive_metrics(facts)
    evaluation = evaluate_checks(
        build_playbook(models, PB), derived, facts, forensic=TH["forensic"],
        universal=universal_forensic_thresholds(), model_specific=model_forensic_thresholds(),
        external=walk.external,
    )
    return walk, facts, derived, evaluation


# --------------------------------------------------------------------------------------------------
# 1. The figures become facts, under the parser's alignment contract.
# --------------------------------------------------------------------------------------------------


def test_the_suspended_capex_finding_becomes_a_grade_a_citable_fact(store):
    """₹16.29cr of suspended capital work in progress, off the real filing page, with a locator on it."""
    _, ids, evidence = register_ageing_facts(
        store, "ALKYL", filing_for("ALKYL", (ALKYL_CWIP_PAGE,)))
    fact = store.query_fact("ALKYL", D.CWIP_AGEING_SUSPENDED, "FY26", as_of=AS_OF)
    assert fact is not None
    assert fact.value == approx(16.2916, abs=1e-4)
    assert fact.grade == "A" and "cwip ageing schedule" in fact.locator
    assert fact.fact_id in ids
    assert evidence["cwip"].located and evidence["cwip"].aligned


def test_a_table_whose_columns_do_not_add_up_yields_its_totals_and_withholds_its_buckets(store):
    """The alignment contract, carried into the fact store rather than left in the parser.

    A row total is read whole and survives a misaligned table; a "beyond one year" figure is a sum
    ACROSS columns and cannot survive it. Storing the second anyway would put the filing's grade-A stamp
    on a guess — the single worst outcome available in this module.
    """
    broken = ALKYL_CWIP_PAGE.replace("  280.17  358.25  11,418.96", "  11,418.96")
    _, _, evidence = register_ageing_facts(store, "BROKEN", filing_for("BROKEN", (broken,)))
    assert evidence["cwip"].located and not evidence["cwip"].aligned

    assert store.query_fact("BROKEN", D.CWIP_AGEING_TOTAL, "FY26", as_of=AS_OF) is not None
    assert store.query_fact("BROKEN", D.CWIP_AGEING_SUSPENDED, "FY26", as_of=AS_OF) is not None
    assert store.query_fact("BROKEN", D.CWIP_AGEING_BEYOND_1Y, "FY26", as_of=AS_OF) is None
    assert store.query_fact("BROKEN", D.CWIP_AGEING_BEYOND_3Y, "FY26", as_of=AS_OF) is None


# --------------------------------------------------------------------------------------------------
# 2. The facts become shares, and the shares decide checks.
# --------------------------------------------------------------------------------------------------


def test_a_clean_filing_publishes_passes_that_show_what_was_looked_at(store):
    """Owner directive 4: "we found nothing" is worthless unless the report shows what it read."""
    _, _, derived, evaluation = _run(
        store, "CLEANCO", clean_series(), CLEAN_AR_PAGES, [BusinessModel.MANUFACTURER])

    assert derived.value("receivables_beyond_1y_share") == approx(2.0 / 118.0)
    assert derived.value("cwip_suspended_share") == approx(0.0)

    for check in ("receivables_ageing_tail", "receivables_disputed", "payables_ageing_tail",
                  "stalled_capex", "ageing_reconciliation"):
        record = evaluation.record(check)
        assert record is not None and record.outcome is CheckOutcome.PASS, f"{check}: {record}"
        assert record.detail, f"{check} passed without saying what it compared"

    # A pass has to name the figures, not just assert cleanliness.
    assert "₹2.00cr of ₹118.00cr receivables" in evaluation.record("receivables_ageing_tail").detail
    assert "temporarily suspended" in evaluation.record("stalled_capex").detail


def test_the_receivable_tail_and_the_disputed_balance_both_fire_on_the_fraud_filing(store):
    """The same fraud, seen in a table the stock-flow check never looks at."""
    _, _, derived, evaluation = _run(
        store, "STUFFED", fraud_series(), FRAUD_AR_PAGES, [BusinessModel.MANUFACTURER])

    assert derived.value("receivables_beyond_1y_share") == approx(56.0 / 210.0)
    assert derived.value("receivables_disputed_share") == approx(8.0 / 210.0)

    tail = evaluation.record("receivables_ageing_tail")
    assert tail.outcome is CheckOutcome.FLAG and "26.7%" in tail.detail
    assert evaluation.metrics.receivables_ageing_tail is True

    disputed = evaluation.record("receivables_disputed")
    assert disputed.outcome is CheckOutcome.FLAG and "₹8.00cr disputed" in disputed.detail
    assert evaluation.metrics.receivables_disputed is True

    # ...while the schedules that are clean say so, rather than being swept along by the verdict.
    assert evaluation.record("stalled_capex").outcome is CheckOutcome.PASS
    assert evaluation.record("payables_ageing_tail").outcome is CheckOutcome.PASS


def test_the_age_of_cwip_comes_from_the_schedule_when_the_filing_carries_one(store):
    """The proxy is replaced by the disclosure, and the detail line says which one it used.

    This is the substantive upgrade, not a refactor: `cwip_persistence_years` counts year-ends the
    BALANCE stayed large, which cannot tell a company that finishes one project and starts another from
    one whose capital has not moved in three years. The schedule answers directly.
    """
    series = clean_series()
    series["balance_sheet:CWIP"] = [20, 22, 18, 120, 140, 130.4812]
    _, _, _, evaluation = _run(
        store, "SIPHON2", series, (ALKYL_CWIP_PAGE,), [BusinessModel.MANUFACTURER])
    record = evaluation.record("ageing_cwip")
    assert "filing's own ageing schedule" in record.detail
    assert "inferred from snapshots" not in record.detail
    # ₹4.25cr sits beyond three years but that is 3.3% of the block, under the materiality floor, so the
    # oldest MATERIAL bucket is 2-3 years. A rounding-dust tail must not date the whole block at three.
    assert "aged 2y" in record.detail


def test_an_unread_schedule_says_which_of_the_three_states_it_is_in(store):
    """Not found, found-but-unreadable and found-and-clean are different findings, and stay different."""
    absent = ExternalInputs()
    located_broken = ExternalInputs(ageing={"receivables": AgeingEvidence(
        kind="receivables", located=True, aligned=False, locator="AR-X p.99",
        reason="a row's buckets do not sum to its printed total")})

    assert "no filing was walked" in absent.ageing_reason("receivables", "the tail")
    reason = located_broken.ageing_reason("receivables", "the tail")
    assert "AR-X p.99" in reason and "withheld rather than" in reason


def test_a_walked_filing_with_no_schedule_does_not_claim_no_filing_was_walked(store):
    """The three states have to survive the WIRING, not just the helper that formats them.

    Found by running the real Alkyl Amines FY26 filing through this chain: `walk_filing` built the
    evidence and never handed it to `ExternalInputs`, so a filing that had been read end to end would
    report "no filing was walked in this run" for any table it could not parse. Every ageing check
    still passed its unit test, because a check only consults the evidence on the path where the
    derivation is absent — which is exactly the path a clean fixture never takes.
    """
    bare = tuple(p for p in CLEAN_AR_PAGES if "Schedule III disclosures" not in p)
    walk, _, _, evaluation = _run(
        store, "NOSCHED", clean_series(), bare, [BusinessModel.MANUFACTURER])

    assert set(walk.external.ageing) == {"receivables", "payables", "cwip"}
    assert not any(e.located for e in walk.external.ageing.values())

    reason = evaluation.record("receivables_ageing_tail").reason
    assert "was not found in the filing" in reason
    assert "no filing was walked" not in reason


def test_a_screener_only_run_reports_the_ageing_checks_unavailable_not_clean(store):
    seed_store(store, "NOFILING", clean_series())
    facts = D.load_company_facts(store, "NOFILING", AS_OF)
    derived = D.derive_metrics(facts)
    evaluation = evaluate_checks(
        build_playbook([BusinessModel.MANUFACTURER], PB), derived, facts, forensic=TH["forensic"],
        universal=universal_forensic_thresholds(), model_specific=model_forensic_thresholds(),
        external=ExternalInputs(),
    )
    for check in ("receivables_ageing_tail", "receivables_disputed", "payables_ageing_tail",
                  "stalled_capex", "ageing_reconciliation"):
        record = evaluation.record(check)
        assert record.outcome is CheckOutcome.UNAVAILABLE, f"{check} claimed an outcome with no filing"
        assert record.reason and record.detail == ""
    # And nothing reached the screen: an absent table must not read as a clean one.
    assert evaluation.metrics.receivables_ageing_tail is False
    assert evaluation.metrics.stalled_capex is False


def test_a_schedule_that_disagrees_with_the_balance_sheet_is_our_fault_not_an_accusation(store):
    """A reconciliation failure reports an extraction fault, never a finding against the company."""
    pages = tuple(
        p.replace("Total  112.00  4.00  1.50  0.50  -    118.00",
                  "Total  312.00  4.00  1.50  0.50  -    318.00")
         .replace("i) Undisputed Trade receivables - considered good  112.00  4.00  1.50  0.50  -    118.00",
                  "i) Undisputed Trade receivables - considered good  312.00  4.00  1.50  0.50  -    318.00")
        for p in CLEAN_AR_PAGES
    )
    _, _, _, evaluation = _run(
        store, "MISMATCH", clean_series(), pages, [BusinessModel.MANUFACTURER])
    record = evaluation.record("ageing_reconciliation")
    assert record.outcome is CheckOutcome.UNAVAILABLE
    assert "NOT as a finding against the company" in record.reason
    assert "receivables ₹318.00cr vs the balance sheet's ₹118.00cr" in record.reason


# --------------------------------------------------------------------------------------------------
# 3. The checks disposition the notes, and the facts reach the agents.
# --------------------------------------------------------------------------------------------------


def test_the_payables_note_is_finally_read_rather_than_merely_counted(store):
    """`payables` had NO check against it, so every trade-payables note in every report was `unknown`.

    That is exactly the theatre `substantive_share` exists to expose — 100% coverage, nothing read — and
    it is why the note taxonomy and `NOTE_CHECKS` have to be kept in step.
    """
    from firm.adapters.india.notes import Note

    notes = (
        Note(number=24, title="Trade Payables", page=40, line=1),
        Note(number=26, title="Capital work-in-progress", page=42, line=1),
    )
    assert [n.category for n in notes] == ["payables", "ppe_cwip"]   # the taxonomy routes them
    _, _, _, evaluation = _run(
        store, "NOTESCO", clean_series(), CLEAN_AR_PAGES, [BusinessModel.MANUFACTURER])
    review, dispositions = disposition_notes(notes, evaluation)

    assert {d.status for d in dispositions} == {"clean"}
    assert review.substantive_share == 1.0
    assert "payables_ageing_tail" in dispositions[0].rationale
    assert "stalled_capex" in dispositions[1].rationale


def test_an_agent_can_see_and_cite_every_ageing_figure(store):
    """A fact an agent cannot see is a fact the firm does not have (ADR-0036, applied to tables).

    The packet is the agent's entire world: a forensic accountant asked about capital work in progress
    cannot report that ₹16.29cr of it is suspended unless that figure AND a citable id are in front of it.
    """
    register_ageing_facts(store, "PACKET", filing_for("PACKET", (ALKYL_CWIP_PAGE,)))
    facts = D.load_company_facts(store, "PACKET", AS_OF)
    rendered = ageing_series(facts)

    entry = rendered[f"{D.CWIP_AGEING_SUSPENDED} FY26"]
    assert entry["value"] == approx(16.2916, abs=1e-4)
    assert entry["cite_as"] == f"[fact:{entry['fact_id']}]" and entry["grade"] == "A"
    assert entry["locator"]
    # The citation validator holds an agent to ids that exist; the packet must offer the same ones.
    assert entry["fact_id"] in facts.all_fact_ids()

    assert ageing_series(None) == {}


# --------------------------------------------------------------------------------------------------
# 4. Point-in-time discipline is inherited, not re-implemented (Law 3).
# --------------------------------------------------------------------------------------------------


def test_an_ageing_schedule_is_invisible_before_the_filing_that_carries_it_is_published(store):
    register_ageing_facts(store, "PIT", filing_for("PIT", (ALKYL_CWIP_PAGE,)))
    before = date(2026, 5, 1)          # the filing publishes 2026-06-15
    assert store.query_fact("PIT", D.CWIP_AGEING_SUSPENDED, "FY26", as_of=before) is None
    assert store.query_fact("PIT", D.CWIP_AGEING_SUSPENDED, "FY26", as_of=AS_OF) is not None


def test_the_thresholds_that_decide_these_checks_all_live_in_config():
    """CLAUDE.md: every hardcoded number lives in `config/thresholds.yaml`, nowhere else."""
    keys = set(ageing_thresholds())
    assert keys == {
        "suspended_cwip_share_max", "cwip_bucket_materiality", "receivables_beyond_1y_max",
        "receivables_disputed_max", "payables_beyond_1y_max", "reconciliation_tolerance",
    }
    assert all(isinstance(v, (int, float)) for v in ageing_thresholds().values())
