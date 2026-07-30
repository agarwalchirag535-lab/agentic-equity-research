"""Tests for the point-in-time facts view and provenance-locked derivations (ADR-0021)."""

from __future__ import annotations

from datetime import date

import pytest

from firm.core.facts.store import Document
from firm.core.pipeline import derive as D
from firm.schemas._base import Grade
from tests.conftest import AS_OF, clean_series, seed_store


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
    seed_store(store, "ACME", clean_series())
    # a grade-C source for one input must drag the derived figure down to C
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
