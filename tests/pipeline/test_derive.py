"""Tests for the point-in-time facts view and provenance-locked derivations (ADR-0021)."""

from __future__ import annotations

from datetime import date

import pytest

from firm.core.facts.store import Document
from firm.core.pipeline import derive as D
from firm.schemas._base import Grade
from tests.conftest import AS_OF, clean_series, fraud_series, seed_store


def test_fiscal_years_respects_the_indian_march_year_end():
    assert D.fiscal_years(date(2026, 7, 30), 2024) == ("FY24", "FY25", "FY26")
    # January is still inside FY25 — FY26 has not closed yet
    assert D.fiscal_years(date(2026, 1, 15), 2024) == ("FY24", "FY25")


def test_loads_only_what_was_published_as_of_the_run_date(store):
    seed_store(store, "ACME", clean_series())
    facts = D.load_company_facts(store, "ACME", AS_OF)
    assert facts.periods == ("FY21", "FY22", "FY23", "FY24", "FY25", "FY26")
    assert facts.value(D.SALES, "FY26") == 1050.0
    assert facts.latest_period(D.SALES) == "FY26"

    before = D.load_company_facts(store, "ACME", date(2026, 3, 1))
    assert before.periods == () and before.all_fact_ids() == ()


def test_derivation_citation_carries_formula_inputs_and_the_worst_grade(store):
    # PBT is withheld from the screener snapshot so the grade-C investor deck is its ONLY source. Since
    # ADR-0029 the resolver prefers the best grade available, so a C fact alongside a B fact would simply
    # never be selected — to prove that a derived figure inherits its WORST input grade, that input has to
    # be the only one there is.
    series = clean_series()
    del series["pnl:Profit before tax"]
    seed_store(store, "ACME", series)
    store.add_document(Document(
        "deck-ACME", "https://example.test/deck", "0", date(2026, 4, 1), date(2026, 4, 1), "C",
        "deck-parser@1.0.0"))
    store.add_fact("deck-ACME:pbt", "deck-ACME", "ACME", D.PBT, "FY26", 173.0, "INR_cr", "slide 4")

    facts = D.load_company_facts(store, "ACME", AS_OF)
    derived = D.derive_metrics(facts)
    other_income = derived.get("other_income_share")
    assert other_income is not None
    citation = other_income.citation
    assert citation.fact_id == "derived:other_income_share"
    assert "pnl:Other Income" in citation.doc_id           # the formula is the document
    assert citation.locator.startswith("inputs ")          # every input id is named
    assert citation.grade is Grade.C                        # weakest input wins
    assert citation.published_at == date(2026, 4, 1)


def test_missing_inputs_are_recorded_not_zero_filled(store):
    series = clean_series()
    del series["cashflow:Cash from Operating Activity"]
    seed_store(store, "NOCASH", series)
    derived = D.derive_metrics(D.load_company_facts(store, "NOCASH", AS_OF))

    assert derived.get("cum_cfo_pat") is None
    assert derived.get("cfo_pat_latest") is None
    assert "cashflow:Cash from Operating Activity" in " ".join(derived.missing["cfo_pat_latest"])
    # and nothing pretended to be zero
    assert "cum_cfo_pat" not in derived.values


def test_no_history_at_all_returns_an_explicit_gap(store):
    derived = D.derive_metrics(D.load_company_facts(store, "GHOST", AS_OF))
    assert derived.values == {} and "no Sales/PAT history" in derived.missing["*"][0]
    assert derived.years == 0


def test_derives_the_ratios_the_financial_agent_is_allowed_to_quote(store):
    seed_store(store, "ACME", clean_series())
    derived = D.derive_metrics(D.load_company_facts(store, "ACME", AS_OF))

    assert derived.value("cfo_to_ebitda_latest") == pytest.approx(145 / 220)
    assert derived.value("fcf_to_pat_cum") == pytest.approx(400 / 565)
    # ΔNOPAT/ΔInvested over the latest 4-year window, not average ROIC
    assert derived.value("incremental_roic_3y") is not None
    assert derived.value("roic_latest") == pytest.approx((220 - 30) * 0.75 / (40 + 10 + 650))


def test_incremental_roic_needs_a_long_enough_run(store):
    short = {metric: values[-3:] for metric, values in clean_series().items()}
    seed_store(store, "YOUNG", short, periods=("FY24", "FY25", "FY26"))
    derived = D.derive_metrics(D.load_company_facts(store, "YOUNG", AS_OF))
    assert derived.get("incremental_roic_3y") is None
    assert "rolling 3-year incremental ROIC" in derived.missing["incremental_roic_3y"][0]


def test_cwip_persistence_counts_consecutive_large_years(store):
    series = clean_series()
    # CWIP parked above 10% of assets for the last three years, never commissioning
    series["balance_sheet:CWIP"] = [20, 22, 18, 120, 140, 160]
    seed_store(store, "CWIPCO", series)
    years, used = D.cwip_persistence_years(D.load_company_facts(store, "CWIPCO", AS_OF), 0.10)
    assert years == 3.0 and used

    seed_store(store, "SMALLCWIP", clean_series())
    small = D.load_company_facts(store, "SMALLCWIP", AS_OF)
    assert D.cwip_persistence_years(small, 0.10)[0] == 0.0   # CWIP is small today: nothing is ageing


# ------------------------------------------------------------------------------------------------
# The causal derivations (ADR-0022): "why did this line move", not just "what is it".


def test_dilution_drag_separates_aggregate_growth_from_per_share_growth(store):
    """The firm's question is a 5-10x PER SHARE, so growth bought with equity must be visible.

    `clean_series` holds the share count flat (EPS tracks PAT), so the wedge is ~0. The fraud fixture
    issues equity to plug its cash gap, so the wedge is material — and it is a fact about shareholders
    that no cash-conversion test can see.
    """
    seed_store(store, "NODILUTE", clean_series())
    clean = D.derive_metrics(D.load_company_facts(store, "NODILUTE", AS_OF))
    assert clean.value("dilution_drag") == pytest.approx(0.0, abs=0.01)

    seed_store(store, "DILUTED", fraud_series())
    diluted = D.derive_metrics(D.load_company_facts(store, "DILUTED", AS_OF))
    assert diluted.value("dilution_drag") > 0.05     # PAT compounds well ahead of EPS


def test_dilution_drag_is_absent_rather_than_zero_when_eps_is_not_disclosed(store):
    """A missing EPS series must not be reported as "no dilution" — that would invent a clean finding."""
    series = clean_series()
    del series["pnl:EPS in Rs"]
    seed_store(store, "NOEPS", series)
    derived = D.derive_metrics(D.load_company_facts(store, "NOEPS", AS_OF))

    assert derived.get("dilution_drag") is None
    assert "pnl:EPS in Rs" in " ".join(derived.missing["dilution_drag"])


def test_self_funding_ratio_answers_whether_operations_paid_for_growth(store):
    """The premise of the whole firm: a compounder funds its own growth.

    Clean fixture: ΣCFO 628 against a 405 investing programme -> comfortably self-funded. Fraud fixture:
    ΣCFO 128 against 760 invested -> the shortfall is what the rising borrowings are actually funding.
    """
    seed_store(store, "SELFFUND", clean_series())
    clean = D.derive_metrics(D.load_company_facts(store, "SELFFUND", AS_OF))
    assert clean.value("self_funding_ratio") > 1.0

    seed_store(store, "EXTFUND", fraud_series())
    external = D.derive_metrics(D.load_company_facts(store, "EXTFUND", AS_OF))
    assert external.value("self_funding_ratio") < 0.3


def test_debt_funded_investment_share_answers_why_the_debt_moved(store):
    """Owner directive: rising debt is not a finding — what the debt BOUGHT is the finding.

    Clean fixture deleverages while investing, so the share is negative (operations paid). Fraud fixture
    borrows ~40% of a programme its operations cannot cover.
    """
    seed_store(store, "DELEVER", clean_series())
    clean = D.derive_metrics(D.load_company_facts(store, "DELEVER", AS_OF))
    assert clean.value("debt_delta_window") < 0
    assert clean.value("debt_funded_investment_share") < 0

    seed_store(store, "LEVERUP", fraud_series())
    levered = D.derive_metrics(D.load_company_facts(store, "LEVERUP", AS_OF))
    assert levered.value("debt_delta_window") == pytest.approx(300.0)
    assert levered.value("debt_funded_investment_share") > 0.30


def test_investment_ratios_are_absent_when_the_window_shows_no_net_investment(store):
    """A net divestor has no "investment programme", so the ratios are missing with a reason, not zero."""
    series = clean_series()
    series["cashflow:Cash from Investing Activity"] = [50, 40, 30, 20, 10, 5]   # net inflow: asset sales
    seed_store(store, "DIVESTOR", series)
    derived = D.derive_metrics(D.load_company_facts(store, "DIVESTOR", AS_OF))

    assert derived.get("self_funding_ratio") is None
    assert derived.get("debt_funded_investment_share") is None
    assert "no net investment" in " ".join(derived.missing["self_funding_ratio"])


def test_payout_share_of_cfo_uses_the_stored_unit_not_a_magnitude_guess(store):
    """`Dividend Payout %` arrives as 20 (percent) from the AR and 0.20 (ratio) from the screener.

    The shortcut `v/100 if v > 1` silently mangles a >100% payout — a company paying out of reserves,
    which is precisely the anomaly a forensic report exists to surface. `unit` removes the guess.
    """
    seed_store(store, "PAYER", clean_series())
    percent_scale = D.derive_metrics(D.load_company_facts(store, "PAYER", AS_OF))
    # 20% of ΣPAT(565) = 113 against ΣCFO(628)
    assert percent_scale.value("dividend_cum_window") == pytest.approx(113.0)
    assert percent_scale.value("payout_share_of_cfo") == pytest.approx(113.0 / 628.0, rel=1e-3)


def test_effective_tax_rate_normalises_a_ratio_unit_without_dividing_twice(store):
    """A `ratio`-unit tax row is already 0.25; dividing again would report a 0.25% tax rate."""
    seed_store(store, "TAXCO", clean_series())
    facts = D.load_company_facts(store, "TAXCO", AS_OF)
    assert facts.fact(D.TAX_PCT, "FY26").unit == "INR_cr"      # fixture stores the printed percentage
    assert D.derive_metrics(facts).value("effective_tax_rate_latest") == pytest.approx(0.25)


def test_a_ratio_unit_tax_row_is_not_rescaled(store):
    """The other half of the same contract, using the screener's own convention."""
    seed_store(store, "RATIOCO", clean_series())
    # Overwrite the FY26 tax row in place with the screener's own `ratio` convention.
    store.add_fact("screener-RATIOCO:pnl:Tax %:FY26", "screener-RATIOCO", "RATIOCO", D.TAX_PCT,
                   "FY26", 0.25, "ratio", "tax row")
    facts = D.load_company_facts(store, "RATIOCO", AS_OF)
    assert D.derive_metrics(facts).value("effective_tax_rate_latest") == pytest.approx(0.25)


def test_expense_and_margin_trajectory_give_the_deterministic_half_of_why_margins_moved(store):
    seed_store(store, "MARGINCO", clean_series())
    derived = D.derive_metrics(D.load_company_facts(store, "MARGINCO", AS_OF))

    assert derived.value("expense_cagr") is not None
    # OPM rose from 110/600 to 220/1050
    assert derived.value("opm_delta_window") == pytest.approx((220 / 1050) - (110 / 600), rel=1e-3)
