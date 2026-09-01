"""Tests for playbook check evaluation (ADR-0021).

The property under test throughout: a check that did not run must never look like a check that passed.
"""

from __future__ import annotations

from firm.core.compute.models import BusinessModel, build_playbook
from firm.core.config import (
    load_thresholds,
    model_forensic_thresholds,
    model_playbooks,
    universal_forensic_thresholds,
)
from firm.core.pipeline import derive as D
from firm.core.pipeline.checks import ExternalInputs, evaluate_checks
from firm.schemas.report import CheckOutcome
from tests.conftest import AS_OF, clean_series, seed_store

TH = load_thresholds()
PB = model_playbooks()


def _evaluate(store, ticker, series, models, external=None, periods=None):
    seed_store(store, ticker, series, **({"periods": periods} if periods else {}))
    facts = D.load_company_facts(store, ticker, AS_OF)
    derived = D.derive_metrics(facts)
    playbook = build_playbook(models, PB)
    return evaluate_checks(
        playbook, derived, facts, forensic=TH["forensic"],
        universal=universal_forensic_thresholds(), model_specific=model_forensic_thresholds(),
        external=external or ExternalInputs(),
    ), derived


def test_every_applicable_check_gets_exactly_one_record(store):
    evaluation, _ = _evaluate(store, "ACME", clean_series(), [BusinessModel.MANUFACTURER])
    names = [r.name for r in evaluation.records]
    for expected in evaluation.expected:
        assert names.count(expected) == 1, f"{expected} recorded {names.count(expected)} times"


def test_a_pass_shows_the_value_and_the_threshold_it_was_compared_against(store):
    evaluation, _ = _evaluate(store, "ACME", clean_series(), [BusinessModel.MANUFACTURER])
    record = evaluation.record("cumulative_cfo_pat")
    assert record.outcome is CheckOutcome.PASS
    assert "ΣCFO/ΣPAT 1.11" in record.detail and "floor 0.70" in record.detail
    assert record.fact_ids                      # and the facts it consumed


def test_absent_inputs_produce_unavailable_with_the_inputs_named(store):
    evaluation, _ = _evaluate(store, "ACME", clean_series(), [BusinessModel.MANUFACTURER])
    record = evaluation.record("receivables_divergent")
    assert record.outcome is CheckOutcome.UNAVAILABLE
    assert "receivables (current, prior)" in record.reason
    assert record.detail == ""                  # nothing is asserted about a check that did not run


def test_unavailable_never_reads_as_a_pass_in_the_screen_inputs(store):
    """The ForensicMetrics booleans must stay False *and* the record must say UNAVAILABLE, so the Gate-B
    verdict cannot silently rest on an input nobody had."""
    evaluation, _ = _evaluate(store, "ACME", clean_series(), [BusinessModel.MANUFACTURER])
    assert evaluation.metrics.receivables_divergent is False
    assert evaluation.outcome("receivables_divergent") is CheckOutcome.UNAVAILABLE
    assert evaluation.unavailable_share > 0


def test_suppressed_checks_are_recorded_as_not_applicable_with_a_reason(store):
    evaluation, _ = _evaluate(store, "NBFC", clean_series(), [BusinessModel.LENDER])
    record = evaluation.record("beneish_manipulator")
    assert record.outcome is CheckOutcome.NOT_APPLICABLE
    assert "LENDER" in record.reason and "invalid for this business model" in record.reason
    # a suppressed check is NOT part of the applicable set used for the unavailable share
    assert "beneish_manipulator" not in evaluation.expected


def test_receivables_running_away_from_revenue_flags(store):
    external = ExternalInputs(
        receivables=(210.0, 100.0), inventory=(140.0, 90.0), revenue=(1050.0, 1000.0),
        source_locators={"receivables_divergent": "AR p.1 l.3"},
        fact_ids={"receivables_divergent": ("AR:recv:FY26", "AR:recv:FY25")},
    )
    evaluation, _ = _evaluate(store, "STUFFED", clean_series(), [BusinessModel.MANUFACTURER], external)
    record = evaluation.record("receivables_divergent")
    assert record.outcome is CheckOutcome.FLAG
    assert "+110.0%" in record.detail and "AR p.1 l.3" in record.detail
    assert evaluation.metrics.receivables_divergent is True


def test_cash_yield_check_names_only_the_input_that_is_actually_missing(store):
    external = ExternalInputs(cash=40.0)        # cash known, interest income on it is not
    evaluation, _ = _evaluate(store, "ACME", clean_series(), [BusinessModel.MANUFACTURER], external)
    reason = evaluation.record("cash_interest_inconsistent").reason
    assert "interest income" in reason
    assert D.CASH not in reason                 # do not claim cash is missing when it is not


def test_disclosure_gap_flags_only_when_a_filing_was_actually_scanned(store):
    unscanned, _ = _evaluate(store, "A", clean_series(), [])
    assert unscanned.record("disclosure_gap").outcome is CheckOutcome.UNAVAILABLE
    assert "no filing was walked" in unscanned.record("disclosure_gap").reason

    scanned, _ = _evaluate(store, "B", clean_series(), [], ExternalInputs(
        disclosure_scanned=True, disclosure_gaps=("benami_property",)))
    record = scanned.record("disclosure_gap")
    assert record.outcome is CheckOutcome.FLAG and "benami_property" in record.detail

    clean, _ = _evaluate(store, "C", clean_series(), [], ExternalInputs(disclosure_scanned=True))
    assert clean.record("disclosure_gap").outcome is CheckOutcome.PASS


def test_promoter_lending_uses_the_schedule_iii_row(store):
    external = ExternalInputs(promoter_loans=(30.0, 100.0), disclosure_scanned=True)
    evaluation, _ = _evaluate(store, "SIPHON", clean_series(), [], external)
    record = evaluation.record("promoter_lending")
    assert record.outcome is CheckOutcome.FLAG and "30.0%" in record.detail
    assert evaluation.metrics.promoter_lending is True


def test_the_cash_yield_check_fires_when_reported_cash_earns_almost_nothing(store):
    """ADR-0006's sharpest test: ₹200cr of cash earning ₹1cr implies the cash is not really there."""
    external = ExternalInputs(cash=200.0, interest_income=1.0)
    evaluation, _ = _evaluate(store, "GHOSTCASH", clean_series(), [], external)
    record = evaluation.record("cash_interest_inconsistent")
    assert record.outcome is CheckOutcome.FLAG
    assert "implied yield on cash 0.50%" in record.detail
    assert evaluation.metrics.cash_interest_inconsistent is True

    honest = ExternalInputs(cash=200.0, interest_income=13.0)      # ~6.5%, at the risk-free
    ok, _ = _evaluate(store, "REALCASH", clean_series(), [], honest)
    assert ok.record("cash_interest_inconsistent").outcome is CheckOutcome.PASS


def test_cash_and_high_cost_debt_together_flag(store):
    series = clean_series()
    series["pnl:Interest"] = [8, 8, 7, 6, 5, 60]          # 150% cost of debt on ₹40cr of borrowings
    evaluation, _ = _evaluate(store, "PARADOX", series, [], ExternalInputs(cash=400.0))
    record = evaluation.record("cash_debt_paradox")
    assert record.outcome is CheckOutcome.FLAG and "44.4%" in record.detail
    assert evaluation.metrics.cash_debt_paradox is True


def test_cwip_parked_above_the_threshold_for_years_flags(store):
    series = clean_series()
    series["balance_sheet:CWIP"] = [20, 22, 18, 120, 140, 160]     # never commissions to PP&E
    evaluation, _ = _evaluate(store, "SIPHON", series, [BusinessModel.MANUFACTURER])
    record = evaluation.record("ageing_cwip")
    assert record.outcome is CheckOutcome.FLAG
    assert "large for 3y" in record.detail
    assert evaluation.metrics.ageing_cwip is True


def test_the_trader_revenue_tell_needs_both_growth_and_a_dead_margin(store):
    fired = ExternalInputs(revenue=(1600.0, 1000.0), gross_margin=0.02)     # +60% at 2% margin
    evaluation, _ = _evaluate(store, "CIRCULAR", clean_series(), [BusinessModel.TRADER], fired)
    assert evaluation.record("revenue_inflation").outcome is CheckOutcome.FLAG
    assert evaluation.metrics.revenue_inflation is True

    healthy = ExternalInputs(revenue=(1600.0, 1000.0), gross_margin=0.35)   # same growth, real margin
    ok, _ = _evaluate(store, "REALGROWTH", clean_series(), [BusinessModel.TRADER], healthy)
    assert ok.record("revenue_inflation").outcome is CheckOutcome.PASS

    # margin undisclosed is not the same as margin zero
    blind, _ = _evaluate(store, "NOMARGIN", clean_series(), [BusinessModel.TRADER],
                         ExternalInputs(revenue=(1600.0, 1000.0)))
    assert blind.record("revenue_inflation").outcome is CheckOutcome.UNAVAILABLE


def test_other_income_carrying_the_profit_flags(store):
    series = clean_series()
    series["pnl:Other Income"] = [6, 7, 8, 9, 10, 120]             # 69% of PBT
    evaluation, _ = _evaluate(store, "NOTABUSINESS", series, [])
    record = evaluation.record("other_income_heavy")
    assert record.outcome is CheckOutcome.FLAG and "69.4% of PBT" in record.detail


def test_a_missing_derivation_makes_the_cash_checks_unavailable_not_clean(store):
    series = clean_series()
    del series["cashflow:Cash from Operating Activity"]
    del series["balance_sheet:Total Assets"]
    evaluation, _ = _evaluate(store, "BLIND", series, [BusinessModel.MANUFACTURER])

    for check in ("cumulative_cfo_pat", "cfo_pat", "high_accruals", "ageing_cwip",
                  "cash_debt_paradox"):
        record = evaluation.record(check)
        assert record.outcome is CheckOutcome.UNAVAILABLE, check
        assert record.reason.strip(), check
    assert evaluation.metrics.cumulative_cfo_pat is None
    assert evaluation.metrics.cfo_pat is None


def test_a_playbook_check_with_no_evaluator_is_visible_not_dropped(store):
    """A check named in config that nothing implements would otherwise imply a check that never ran."""
    playbook = build_playbook([], {"UNIVERSAL": {"applies": ["some_future_check"]}})
    seed_store(store, "FUTURE", clean_series())
    facts = D.load_company_facts(store, "FUTURE", AS_OF)
    evaluation = evaluate_checks(
        playbook, D.derive_metrics(facts), facts, forensic=TH["forensic"],
        universal=universal_forensic_thresholds(), model_specific=model_forensic_thresholds())
    record = evaluation.record("some_future_check")
    assert record.outcome is CheckOutcome.UNAVAILABLE
    # An UNDECLARED unwired check says so in the plainest terms available: it is a wiring bug, not a
    # fact about the company (ADR-0050/0051).
    assert "no evaluator is wired" in record.reason
    assert "not even declared in UNIMPLEMENTED_CHECKS" in record.reason
    assert "wiring bug, not a fact about the company" in record.reason


def test_unavailable_share_is_one_when_nothing_is_applicable(store):
    playbook = build_playbook([], {})
    seed_store(store, "EMPTY", clean_series())
    facts = D.load_company_facts(store, "EMPTY", AS_OF)
    evaluation = evaluate_checks(
        playbook, D.derive_metrics(facts), facts, forensic=TH["forensic"],
        universal=universal_forensic_thresholds(), model_specific=model_forensic_thresholds())
    assert evaluation.records == () and evaluation.unavailable_share == 1.0


# ------------------------------------------------------------------------------------------------
# Input plausibility for the deterministic checks (ADR-0025).
#
# These exist because the first primary-source run published a FORENSIC_CAUTION on a real listed company
# from two degenerate inputs. A check may not accuse a company on a number that means nothing.


def _paradox_setup(store, *, cash_cr: float, borrowings_cr: float, assets_cr: float = 1896.0,
                   interest_cr: float = 1.0):
    """A minimal company plus a filing whose only job is to supply a cash figure."""
    from firm.core.pipeline.checks import ExternalInputs

    series = clean_series()
    series["balance_sheet:Borrowings"] = [borrowings_cr] * 6
    series["balance_sheet:Total Assets"] = [assets_cr] * 6
    series["pnl:Interest"] = [interest_cr] * 6
    seed_store(store, "PARADOX", series)
    facts = D.load_company_facts(store, "PARADOX", AS_OF)
    derived = D.derive_metrics(facts)
    evaluation = evaluate_checks(
        build_playbook([], model_playbooks()), derived, facts,
        forensic=TH["forensic"], universal=universal_forensic_thresholds(),
        model_specific=model_forensic_thresholds(),
        external=ExternalInputs(cash=cash_cr),
    )
    return evaluation


def test_immaterial_borrowings_make_the_paradox_check_unavailable_not_a_flag(store):
    """ALKYLAMINE: Interest ₹1cr / Borrowings ₹1cr = a "100% cost of debt" that fired FORENSIC_CAUTION.

    Both are rounded screener figures. A cost-of-debt ratio on ₹1cr of year-end debt is an artefact of
    rounding, not a rate the company pays, so the check must decline to run.
    """
    evaluation = _paradox_setup(store, cash_cr=94.15, borrowings_cr=1.0)
    record = next(r for r in evaluation.records if r.name == "cash_debt_paradox")

    assert record.outcome is CheckOutcome.UNAVAILABLE
    assert "artefact of rounding" in record.reason


def test_an_impossible_cash_to_assets_ratio_is_reported_as_our_fault_not_theirs(store):
    """cash/assets above 1 is arithmetically impossible, so it is a unit or extraction fault here.

    This read 496.6% when a lakh cash figure met a crore asset base, and flagged the company for it.
    """
    evaluation = _paradox_setup(store, cash_cr=9415.34, borrowings_cr=100.0)
    record = next(r for r in evaluation.records if r.name == "cash_debt_paradox")

    assert record.outcome is CheckOutcome.UNAVAILABLE
    assert "impossible" in record.reason
    assert "different scales" in record.reason or "misread" in record.reason


def test_a_real_paradox_still_flags_when_the_inputs_are_material(store):
    """The guard must not disarm the check: material debt at a high rate on a large cash pile still fires."""
    # ₹60cr of interest on ₹500cr of debt is a real 12% rate, held alongside ₹600cr of cash.
    evaluation = _paradox_setup(store, cash_cr=600.0, borrowings_cr=500.0, interest_cr=60.0)
    record = next(r for r in evaluation.records if r.name == "cash_debt_paradox")

    assert record.outcome is CheckOutcome.FLAG
    assert "cash/assets" in record.detail


def test_a_check_reports_the_provenance_span_it_rests_on(store):
    """ADR-0028: a check drawing on grade A and grade B must say so.

    `cash_debt_paradox` divides cash from the audited filing by total assets from the screener. Reported as
    one number it launders the weaker source — a reader sees a filing-backed check and cannot tell half the
    denominator came from an aggregator.
    """
    seed_store(store, "GRADED", clean_series())
    facts = D.load_company_facts(store, "GRADED", AS_OF)
    derived = D.derive_metrics(facts)
    evaluation = evaluate_checks(
        build_playbook([], model_playbooks()), derived, facts,
        forensic=TH["forensic"], universal=universal_forensic_thresholds(),
        model_specific=model_forensic_thresholds(),
    )
    ran = [r for r in evaluation.records if r.outcome is CheckOutcome.PASS and r.fact_ids]
    assert ran, "expected at least one check to run on the seeded company"
    # Every screener-sourced check is grade B and must name it.
    assert all("(grade B)" in r.detail for r in ran)
    assert not any("mixed provenance" in r.detail for r in ran)


def _cash_series(cash: list[float], other_bank: list[float], interest_income: list[float]) -> dict:
    """`clean_series` plus the three rows the cash-yield check needs to run at all."""
    return {
        **clean_series(),
        "balance_sheet:Cash Equivalents": cash,
        "balance_sheet:Other Bank Balances": other_bank,
        "cashflow:Interest Income": interest_income,
    }


def test_cash_yield_below_the_floor_is_unavailable_when_the_balance_moved(store):
    """ADR-0059, on the shape of ALKYLAMINE FY23: a 71% drawdown, a 2.55% point estimate, no claim.

    The point estimate is below the floor and the endpoints are equally consistent with a yield well
    above it. The check must say it cannot tell — not flag, and emphatically not pass.
    """
    series = _cash_series(
        cash=[60, 60, 60, 60, 62.5712, 18.2321],
        other_bank=[0, 0, 0, 0, 0, 0],
        interest_income=[4, 4, 4, 4, 4, 1.0286],
    )
    evaluation, derived = _evaluate(store, "ACME", series, [BusinessModel.MANUFACTURER])
    record = evaluation.record("cash_interest_inconsistent")
    assert derived.value("cash_yield_latest") < TH["forensic"]["cash_yield_floor_ratio"] * TH[
        "forensic"]["risk_free_rate"]
    assert record.outcome is CheckOutcome.UNAVAILABLE
    assert "1.64% to 5.64%" in record.reason and "71%" in record.reason
    assert "half-yearly" in record.reason        # and it names what would resolve it


def test_cash_yield_still_flags_a_stable_balance_that_earns_nothing(store):
    """The claim the check exists to make survives: money that sat still and did not earn."""
    series = _cash_series(
        cash=[500, 500, 500, 500, 500, 500],
        other_bank=[0, 0, 0, 0, 0, 0],
        interest_income=[2, 2, 2, 2, 2, 2],
    )
    evaluation, _ = _evaluate(store, "ACME", series, [BusinessModel.MANUFACTURER])
    record = evaluation.record("cash_interest_inconsistent")
    assert record.outcome is CheckOutcome.FLAG
    assert "0.40%" in record.detail and "endpoints support 0.40%-0.40%" in record.detail


def test_cash_yield_passes_a_healthy_stable_balance_and_shows_the_band(store):
    series = _cash_series(
        cash=[100, 100, 100, 100, 204.0558, 201.7030],
        other_bank=[0, 0, 0, 0, 0, 0],
        interest_income=[7, 7, 7, 7, 7, 15.7788],
    )
    evaluation, _ = _evaluate(store, "ACME", series, [BusinessModel.MANUFACTURER])
    record = evaluation.record("cash_interest_inconsistent")
    assert record.outcome is CheckOutcome.PASS
    assert "endpoints support 7.73%-7.82%" in record.detail


def test_a_row_this_firm_could_not_read_is_never_charged_to_the_company(store):
    """ADR-0059, live on ALKYLAMINE FY23: our row-locator's miss was published as their disclosure gap.

    The check must PASS on the company — it published everything the law asks — while still naming the
    row we failed to read, because a capability gap that vanishes is how the backlog stops generating
    itself.
    """
    external = ExternalInputs(
        disclosure_scanned=True,
        disclosure_gaps=(),
        extraction_gaps=(("balance_sheet:Total Assets: the row labelled for this metric read 49,881.61 "
                         "against 1,59,008.74 on the balancing line at p.86"),),
    )
    evaluation, _ = _evaluate(store, "ACME", clean_series(), [BusinessModel.MANUFACTURER],
                              external=external)
    record = evaluation.record("disclosure_gap")
    assert record.outcome is CheckOutcome.PASS
    assert "could not read (ours, not the company's)" in record.detail
    assert "balance_sheet:Total Assets" in record.detail


def test_a_genuinely_absent_mandated_row_still_flags(store):
    external = ExternalInputs(
        disclosure_scanned=True,
        disclosure_gaps=("related-party transactions (Ind AS 24)",),
        extraction_gaps=("balance_sheet:Total Assets: unreadable",),
    )
    evaluation, _ = _evaluate(store, "ACME", clean_series(), [BusinessModel.MANUFACTURER],
                              external=external)
    record = evaluation.record("disclosure_gap")
    assert record.outcome is CheckOutcome.FLAG
    assert "mandated disclosures absent: related-party transactions" in record.detail
