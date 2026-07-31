"""Tests for forensic/earnings-quality metrics. Aims for full coverage of firm.core.compute.quality."""

import pytest

from firm.core.compute.quality import (
    BeneishYear,
    ForensicMetrics,
    ForensicThresholds,
    ForensicVerdict,
    SectorClass,
    Severity,
    accrual_ratio,
    ageing_cwip_flag,
    ageing_reconciliation_gap,
    ageing_tail_share,
    disputed_balance_share,
    suspended_capex_share,
    beneish_m_score,
    cash_debt_paradox,
    cash_interest_consistency,
    cfo_pat_ratio,
    cumulative_cfo_pat_ratio,
    disclosure_completeness,
    forensic_screen,
    adjusted_ebitda_bridge_gap,
    capitalised_cost_share,
    contract_asset_divergence,
    gain_on_sale_reliance,
    gnpa_drift_flag,
    guarantees_to_net_worth,
    held_for_sale_reserve_flag,
    other_income_share,
    promoter_loan_share,
    provision_book_divergence,
    provision_coverage_flag,
    provision_rate,
    reserve_suppression_flag,
    restructured_book_flag,
    revenue_inflation_tell,
    stock_flow_divergence,
)

TH = ForensicThresholds(
    cfo_pat_min=0.70, cumulative_cfo_pat_min=0.70, sloan_accrual_flag=0.10, beneish_m_threshold=-1.78
)


# ---- cash-reality checks (ADR-0006) ------------------------------------------------------------
def test_accrual_ratio():
    assert accrual_ratio(120, 100, 1000) == pytest.approx(0.02)
    with pytest.raises(ValueError):
        accrual_ratio(120, 100, 0)


def test_cfo_pat_ratio():
    assert cfo_pat_ratio(110, 120) == pytest.approx(110 / 120)
    with pytest.raises(ValueError):
        cfo_pat_ratio(110, 0)


def test_cumulative_cfo_pat_ratio():
    assert cumulative_cfo_pat_ratio([100, 110, 120], [90, 100, 120]) == pytest.approx(330 / 310)
    with pytest.raises(ValueError):
        cumulative_cfo_pat_ratio([1, 2], [1])          # length mismatch
    with pytest.raises(ValueError):
        cumulative_cfo_pat_ratio([], [])               # empty
    with pytest.raises(ValueError):
        cumulative_cfo_pat_ratio([10, -10], [10, -10])  # cumulative pat zero


def test_cash_interest_consistency():
    implied, flag = cash_interest_consistency(1, 1000, 0.065, 0.40)
    assert implied == pytest.approx(0.001) and flag is True
    _, ok = cash_interest_consistency(40, 1000, 0.065, 0.40)
    assert ok is False
    with pytest.raises(ValueError):
        cash_interest_consistency(1, 0, 0.065, 0.40)


def test_cash_debt_paradox():
    assert cash_debt_paradox(200, 1000, 300, 0.12, 0.15, 0.10) is True
    assert cash_debt_paradox(200, 1000, 300, 0.05, 0.15, 0.10) is False
    with pytest.raises(ValueError):
        cash_debt_paradox(200, 0, 300, 0.12, 0.15, 0.10)


def test_ageing_cwip_flag():
    assert ageing_cwip_flag(200, 1000, 3, 0.10, 3) is True
    assert ageing_cwip_flag(200, 1000, 1, 0.10, 3) is False
    with pytest.raises(ValueError):
        ageing_cwip_flag(200, 0, 3, 0.10, 3)


# ---- Schedule III ageing schedules (ADR-0039) --------------------------------------------------
# Each returns (share, flagged) rather than a bare bool, because the published checklist prints the
# value it compared against the policy number — a reader must be able to disagree with the threshold
# without re-running anything.


def test_suspended_capex_share():
    # Alkyl Amines FY26: 1,629.16 lakh of 13,048.12 suspended.
    share, flagged = suspended_capex_share(16.2916, 130.4812, 0.10)
    assert share == pytest.approx(0.1249, abs=1e-4) and flagged is True
    assert suspended_capex_share(1.0, 130.4812, 0.10) == (pytest.approx(0.00766, abs=1e-4), False)
    with pytest.raises(ValueError):
        suspended_capex_share(16.29, 0, 0.10)


def test_ageing_tail_share():
    assert ageing_tail_share(56.0, 210.0, 0.05) == (pytest.approx(0.2667, abs=1e-4), True)
    assert ageing_tail_share(2.0, 118.0, 0.05) == (pytest.approx(0.01695, abs=1e-4), False)
    # Exactly at the limit is not a flag: the threshold is a ceiling the company may sit on.
    assert ageing_tail_share(5.0, 100.0, 0.05)[1] is False
    with pytest.raises(ValueError):
        ageing_tail_share(10.0, 0.0, 0.05)


def test_disputed_balance_share_sums_both_admissions():
    """Disputed and credit-impaired are different admissions and the check wants the total of them."""
    assert disputed_balance_share(8.0, 0.0, 210.0, 0.02) == (pytest.approx(0.0381, abs=1e-4), True)
    assert disputed_balance_share(1.0, 2.0, 210.0, 0.02)[1] is False
    assert disputed_balance_share(1.0, 5.0, 210.0, 0.02)[1] is True     # neither alone would fire
    with pytest.raises(ValueError):
        disputed_balance_share(1.0, 1.0, 0.0, 0.02)


def test_ageing_reconciliation_gap_is_a_measurement_not_a_verdict():
    """It returns the gap and no judgement — the caller decides, and never against the company."""
    assert ageing_reconciliation_gap(118.0, 118.0) == 0.0
    assert ageing_reconciliation_gap(318.0, 118.0) == pytest.approx(200.0 / 118.0)
    assert ageing_reconciliation_gap(117.0, 118.0) == pytest.approx(1.0 / 118.0)   # sign-free
    with pytest.raises(ValueError):
        ageing_reconciliation_gap(118.0, 0.0)


# ---- Beneish M-score (non-financials) ----------------------------------------------------------
def _beneish_pair():
    prior = BeneishYear(
        sales=1000, cogs=600, receivables=150, current_assets=400, ppe_net=500, total_assets=1200,
        depreciation=50, sga=100, income_continuing_ops=120, cfo=110, current_liabilities=200,
        long_term_debt=300,
    )
    current = BeneishYear(
        sales=1300, cogs=800, receivables=260, current_assets=520, ppe_net=560, total_assets=1500,
        depreciation=55, sga=120, income_continuing_ops=150, cfo=90, current_liabilities=260,
        long_term_debt=360,
    )
    return prior, current


def test_beneish_m_score_computes():
    prior, current = _beneish_pair()
    m = beneish_m_score(prior, current)
    assert isinstance(m, float)


def test_beneish_m_score_zero_denominator_raises():
    prior, current = _beneish_pair()
    broken = BeneishYear(**{**current.__dict__, "sales": 0})
    with pytest.raises(ValueError):
        beneish_m_score(prior, broken)


# ---- lender-specific checks (financials) -------------------------------------------------------
def test_gnpa_drift_flag():
    assert gnpa_drift_flag(0.05, 0.03, 0.01) is True
    assert gnpa_drift_flag(0.031, 0.030, 0.01) is False


def test_provision_coverage_flag():
    assert provision_coverage_flag(40, 100, 0.50) is True
    assert provision_coverage_flag(60, 100, 0.50) is False
    assert provision_coverage_flag(0, 0, 0.50) is False  # no GNPA => not flagged


def test_restructured_book_flag():
    assert restructured_book_flag(60, 1000, 0.05) is True
    assert restructured_book_flag(40, 1000, 0.05) is False
    with pytest.raises(ValueError):
        restructured_book_flag(60, 0, 0.05)


# ---- originate-to-sell / lender earnings-quality checks (FORENSIC_METHODOLOGY §7 P7) -----------
import math  # noqa: E402


def test_gain_on_sale_reliance():
    ratio, flag = gain_on_sale_reliance(220, 100, 1.0)  # Carvana-like 2.2x NI
    assert ratio == pytest.approx(2.2) and flag is True
    ratio, flag = gain_on_sale_reliance(50, 100, 1.0)
    assert ratio == pytest.approx(0.5) and flag is False


def test_gain_on_sale_reliance_no_or_negative_income():
    # positive gain but no/negative net income => profit only exists because of the sale => flag
    ratio, flag = gain_on_sale_reliance(50, 0, 1.0)
    assert math.isinf(ratio) and flag is True
    ratio, flag = gain_on_sale_reliance(50, -10, 1.0)
    assert math.isinf(ratio) and flag is True
    # no gain and no income => not flagged
    ratio, flag = gain_on_sale_reliance(0, -10, 1.0)
    assert ratio == 0.0 and flag is False


def test_provision_rate():
    assert provision_rate(12, 100) == pytest.approx(0.12)
    with pytest.raises(ValueError):
        provision_rate(12, 0)


def test_provision_book_divergence():
    prov_g, book_g, flag = provision_book_divergence(230, 100, 106, 100, 0.50)  # Sezzle-like
    assert prov_g == pytest.approx(1.30) and book_g == pytest.approx(0.06) and flag is True
    prov_g, book_g, flag = provision_book_divergence(110, 100, 108, 100, 0.50)
    assert flag is False
    with pytest.raises(ValueError):
        provision_book_divergence(100, 0, 100, 100, 0.50)   # provisions_prior <= 0
    with pytest.raises(ValueError):
        provision_book_divergence(100, 100, 100, 0, 0.50)   # loans_prior <= 0


def test_reserve_suppression_flag():
    assert reserve_suppression_flag(0.012, 0.035, 0.010) is True   # Sezzle 3.5% -> 1.2%
    assert reserve_suppression_flag(0.033, 0.035, 0.010) is False


def test_held_for_sale_reserve_flag():
    assert held_for_sale_reserve_flag(553, 0, 368, 0.005) is True     # growing book, ~zero allowance
    assert held_for_sale_reserve_flag(553, 100, 368, 0.005) is False  # material allowance
    assert held_for_sale_reserve_flag(300, 0, 368, 0.005) is False    # book shrinking
    assert held_for_sale_reserve_flag(0, 0, 368, 0.005) is False      # no on-book loans


def test_disclosure_completeness():
    missing, flag = disclosure_completeness(["related_party", "pledges", "auditor"], ["related_party", "auditor"])
    assert missing == ["pledges"] and flag is True
    missing, flag = disclosure_completeness(["a", "b"], ["a", "b", "c"])
    assert missing == [] and flag is False


# ---- universal SPEC §5 checks (ADAPTIVE_FORENSICS §4 step 1) -----------------------------------
def test_stock_flow_divergence_receivables_tell():
    # receivables +60% while revenue +10% -> gap 0.50 > 0.25 -> the channel-stuffing tell
    sg, fg, flag = stock_flow_divergence(160, 100, 110, 100, 0.25)
    assert sg == pytest.approx(0.60) and fg == pytest.approx(0.10) and flag is True
    # destocking (stock shrinking faster than flow) must NOT flag
    _, _, flag = stock_flow_divergence(60, 100, 110, 100, 0.25)
    assert flag is False
    with pytest.raises(ValueError):
        stock_flow_divergence(100, 0, 100, 100, 0.25)
    with pytest.raises(ValueError):
        stock_flow_divergence(100, 100, 100, 0, 0.25)


def test_other_income_share():
    share, flag = other_income_share(40, 100, 0.25)
    assert share == pytest.approx(0.40) and flag is True
    share, flag = other_income_share(10, 100, 0.25)
    assert flag is False
    # loss-making pre-other-income: infinite dependence -> flag
    share, flag = other_income_share(40, 0, 0.25)
    assert math.isinf(share) and flag is True
    share, flag = other_income_share(0, -5, 0.25)
    assert share == 0.0 and flag is False


def test_revenue_inflation_tell():
    assert revenue_inflation_tell(0.80, 0.01, 0.50, 0.03) is True     # trader signature
    assert revenue_inflation_tell(0.80, 0.20, 0.50, 0.03) is False    # real margin -> fine
    assert revenue_inflation_tell(0.10, 0.01, 0.50, 0.03) is False    # slow growth -> fine


# ---- model-specific checks (ADAPTIVE_FORENSICS §2 matrix) ---------------------------------------
def test_contract_asset_divergence():
    # EPC: unbilled revenue +80% while billed revenue +10% -> profit is increasingly an estimate
    ca_g, rev_g, flag = contract_asset_divergence(180, 100, 110, 100, 0.30)
    assert ca_g == pytest.approx(0.80) and rev_g == pytest.approx(0.10) and flag is True
    _, _, ok = contract_asset_divergence(115, 100, 110, 100, 0.30)
    assert ok is False


def test_guarantees_to_net_worth():
    ratio, flag = guarantees_to_net_worth(600, 1000, 0.50)
    assert ratio == pytest.approx(0.60) and flag is True
    ratio, flag = guarantees_to_net_worth(200, 1000, 0.50)
    assert flag is False
    # negative/zero net worth with guarantees outstanding = unbounded exposure
    ratio, flag = guarantees_to_net_worth(100, 0, 0.50)
    assert math.isinf(ratio) and flag is True
    ratio, flag = guarantees_to_net_worth(0, -50, 0.50)
    assert ratio == 0.0 and flag is False


def test_capitalised_cost_share():
    share, flag = capitalised_cost_share(45, 100, 0.30)
    assert share == pytest.approx(0.45) and flag is True
    _, ok = capitalised_cost_share(10, 100, 0.30)
    assert ok is False
    with pytest.raises(ValueError):
        capitalised_cost_share(10, 0, 0.30)


def test_adjusted_ebitda_bridge_gap():
    # ₹12cr of add-backs on ₹100cr revenue = 12% of revenue "adjusted" away
    gap, flag = adjusted_ebitda_bridge_gap(10, -2, 100, 0.05)
    assert gap == pytest.approx(0.12) and flag is True
    gap, flag = adjusted_ebitda_bridge_gap(10, 9, 100, 0.05)
    assert flag is False
    with pytest.raises(ValueError):
        adjusted_ebitda_bridge_gap(10, 5, 0, 0.05)


def test_promoter_loan_share():
    share, flag = promoter_loan_share(30, 100, 0.10)
    assert share == pytest.approx(0.30) and flag is True
    _, ok = promoter_loan_share(5, 100, 0.10)
    assert ok is False
    # no advances at all -> nothing to divert, not a flag
    assert promoter_loan_share(0, 0, 0.10) == (0.0, False)


def test_screen_model_specific_flags():
    m = ForensicMetrics(
        promoter_lending=True, guarantees_heavy=True, contract_asset_divergent=True,
        capitalised_cost_heavy=True, adjusted_ebitda_gap=True,
    )
    r = forensic_screen(SectorClass.NON_FINANCIAL, m, TH)
    names = {f.name for f in r.flags}
    assert {"promoter_lending", "guarantees_heavy", "contract_asset_divergent",
            "capitalised_cost_heavy", "adjusted_ebitda_gap"} == names
    # promoter lending is SEVERE on its own -> hard fail
    assert r.verdict is ForensicVerdict.HARD_FAIL and r.hard_fail is True


def test_screen_promoter_lending_alone_is_severe():
    r = forensic_screen(SectorClass.NON_FINANCIAL, ForensicMetrics(promoter_lending=True), TH)
    assert r.verdict is ForensicVerdict.HARD_FAIL


# ---- aggregator: the deterministic Gate-B verdict ----------------------------------------------
def test_screen_clean_non_financial_passes():
    m = ForensicMetrics(cfo_pat=1.1, cumulative_cfo_pat=1.0, accrual_ratio=0.02, beneish_m=-2.5)
    r = forensic_screen(SectorClass.NON_FINANCIAL, m, TH)
    assert r.verdict is ForensicVerdict.PASS
    assert r.hard_fail is False
    assert r.flags == []


def test_screen_dirty_non_financial_hard_fails_on_severe():
    m = ForensicMetrics(
        cfo_pat=0.5, cumulative_cfo_pat=0.4, accrual_ratio=0.30, beneish_m=-1.0,
        cash_interest_inconsistent=True, cash_debt_paradox=True, ageing_cwip=True,
    )
    r = forensic_screen(SectorClass.NON_FINANCIAL, m, TH)
    assert r.verdict is ForensicVerdict.HARD_FAIL
    assert r.hard_fail is True
    names = {f.name for f in r.flags}
    assert {"cumulative_cfo_pat_low", "cfo_pat_low", "high_accruals", "beneish_manipulator",
            "cash_interest_inconsistent", "cash_debt_paradox", "ageing_cwip"} <= names


def test_screen_raises_the_ageing_signals_at_the_severity_they_were_calibrated_at():
    """No uncalibrated ageing signal is HIGH unless it rests on the company's OWN classification.

    Two HIGH flags hard-fail a company. Nothing in `config/thresholds.yaml:ageing` has been tested
    against a known fraud yet (Phase 6), so a tail share — a policy number applied to a bucket sum —
    stays MEDIUM, while `receivables_disputed` is HIGH because the company itself said the balance is
    contested. That distinction is the whole severity argument, and it is asserted rather than trusted.
    """
    m = ForensicMetrics(
        stalled_capex=True, receivables_ageing_tail=True, payables_ageing_tail=True,
        receivables_disputed=True,
    )
    r = forensic_screen(SectorClass.NON_FINANCIAL, m, TH)
    severities = {f.name: f.severity for f in r.flags}
    assert severities["receivables_disputed"] is Severity.HIGH
    assert severities["stalled_capex"] is Severity.MEDIUM
    assert severities["receivables_ageing_tail"] is Severity.MEDIUM
    assert severities["payables_ageing_tail"] is Severity.MEDIUM
    # One HIGH plus three MEDIUMs is a REVIEW — an invitation to investigate, not an accusation.
    assert r.verdict is ForensicVerdict.REVIEW and r.hard_fail is False

    # The receivable/payable tails are meaningless for a lender, exactly as `receivables_divergent` is
    # (ADR-0002), while capital work in progress is real for anyone who builds.
    lender = forensic_screen(SectorClass.FINANCIAL, m, TH)
    lender_flags = {f.name for f in lender.flags}
    assert "stalled_capex" in lender_flags
    assert {"receivables_disputed", "receivables_ageing_tail", "payables_ageing_tail"} & lender_flags == set()


def test_screen_two_highs_hard_fail_without_severe():
    m = ForensicMetrics(cfo_pat=0.5, beneish_m=-1.0)  # two HIGH, no SEVERE
    r = forensic_screen(SectorClass.NON_FINANCIAL, m, TH)
    assert r.verdict is ForensicVerdict.HARD_FAIL


def test_screen_single_medium_is_review():
    m = ForensicMetrics(accrual_ratio=0.30)  # one MEDIUM flag only
    r = forensic_screen(SectorClass.NON_FINANCIAL, m, TH)
    assert r.verdict is ForensicVerdict.REVIEW
    assert r.hard_fail is False


def test_screen_financial_uses_lender_checks():
    m = ForensicMetrics(
        gnpa_drift=True, provision_coverage_low=True, restructured_book_high=True,
    )
    r = forensic_screen(SectorClass.FINANCIAL, m, TH)
    assert r.verdict is ForensicVerdict.HARD_FAIL  # two HIGH lender flags
    names = {f.name for f in r.flags}
    assert {"gnpa_drift", "provision_coverage_low", "restructured_book_high"} <= names


def test_screen_originate_to_sell_flags_hard_fail():
    # The Carvana/Sezzle profile: originate-to-sell earnings tricks + a disclosure gap.
    m = ForensicMetrics(
        gain_on_sale_reliant=True, reserve_suppression=True, held_for_sale_no_reserve=True,
        provision_book_divergent=True, disclosure_gap=True,
    )
    r = forensic_screen(SectorClass.NON_FINANCIAL, m, TH)
    assert r.verdict is ForensicVerdict.HARD_FAIL  # three HIGH originate-to-sell flags
    names = {f.name for f in r.flags}
    assert {"gain_on_sale_reliant", "reserve_suppression", "held_for_sale_no_reserve",
            "provision_book_divergent", "disclosure_gap"} <= names


def test_screen_universal_flags_fire_for_non_financial_only():
    m = ForensicMetrics(
        receivables_divergent=True, inventory_divergent=True,
        other_income_heavy=True, revenue_inflation=True,
    )
    r = forensic_screen(SectorClass.NON_FINANCIAL, m, TH)
    names = {f.name for f in r.flags}
    assert {"receivables_divergent", "inventory_divergent",
            "other_income_heavy", "revenue_inflation"} == names
    assert r.verdict is ForensicVerdict.HARD_FAIL     # two HIGH (receivables + revenue_inflation)
    # suppressed for FINANCIAL — a lender has no trade receivables/inventory in this sense
    r_fin = forensic_screen(SectorClass.FINANCIAL, m, TH)
    assert r_fin.flags == [] and r_fin.verdict is ForensicVerdict.PASS


def test_screen_originate_to_sell_applies_regardless_of_sector():
    # Model-based, not sector-label-based: a single lender flag fires even on a NON_FINANCIAL "dealer".
    r = forensic_screen(SectorClass.NON_FINANCIAL, ForensicMetrics(gain_on_sale_reliant=True), TH)
    assert r.verdict is ForensicVerdict.REVIEW  # one HIGH flag => REVIEW, not hard fail
    assert {f.name for f in r.flags} == {"gain_on_sale_reliant"}
