"""The valuation reaches the report (ADR-0069).

ADR-0062 built the valuation layer and the `DerivedSet.extended` seam it was meant to plug into, and
then nothing connected them: `run_deep_dive` never called `value_company`, so no published report has
ever carried a valuation. These tests cover the wiring and the two properties that make it safe.

**No look-ahead.** A price series is the easiest place in the system to leak the future — one careless
`series[-1]` in a replay of 2019 values the company at today's price and turns a backtest into a
fantasy. The close is read through the ordinary point-in-time query AND pinned to the latest period at
or before the run date.

**Missing is named, never defaulted.** A run with no price still produces a valuation section; it just
says what it lacked. A section that silently disappears is indistinguishable from one that passed.
"""

from __future__ import annotations

from datetime import date

from firm.core.config import load_thresholds
from firm.core.facts.store import Document
from firm.core.pipeline import derive as D
from firm.core.pipeline.deep_dive import run_deep_dive
from firm.core.pipeline.valuation import load_valuation, valuation_derivations
from firm.core.report.render import render_markdown
from tests.conftest import AS_OF, clean_answers, clean_series, filing_for, seed_store

POLICY = load_thresholds()["valuation"]


def valuable_series(**overrides) -> dict:
    """`clean_series` plus the balance-sheet cash rows a net-debt figure needs (mirrors
    test_valuation.py). Without these the valuation correctly refuses, which would let every
    assertion below pass against the `unavailable` branch and test nothing."""
    return {
        **clean_series(),
        "balance_sheet:Cash Equivalents": [50, 60, 70, 80, 90, 100],
        "balance_sheet:Other Bank Balances": [10, 10, 10, 10, 10, 10],
        **overrides,
    }


def seed_price(store, ticker: str, price: float, on: date, *, published: date | None = None) -> None:
    """Register a settled close the way `ingest_prices` does: period = the trading date."""
    doc_id = f"BSE-CLOSE-{ticker}-{on:%Y%m%d}"
    store.add_document(Document(doc_id=doc_id, source_url="https://bse", sha256="",
                                published_at=published or on, fetched_at=published or on, grade="A",
                                extractor_version="test@1.0.0"))
    store.add_fact(fact_id=f"{doc_id}:market:Close:{on.isoformat()}", doc_id=doc_id, ticker=ticker,
                   metric="market:Close", period=on.isoformat(), value=price, unit="INR",
                   locator=f"BSE settled close {on:%Y-%m-%d}", period_end=on)


def _load(store, ticker="ACME", as_of=AS_OF):
    facts = D.load_company_facts(store, ticker, as_of)
    derived = D.derive_metrics(facts)
    return load_valuation(store, ticker, as_of, facts, derived, policy=POLICY)


def test_the_close_is_read_point_in_time_and_a_later_one_does_not_exist(store):
    """The invariant that makes a historical replay honest rather than hindsight theatre."""
    seed_store(store, "ACME", valuable_series())
    seed_price(store, "ACME", 1000.0, date(2026, 7, 28))            # before the run date
    seed_price(store, "ACME", 9999.0, date(2026, 12, 31))           # after it — must be invisible

    result = _load(store)
    assert result.price == 1000.0
    assert result.price_on == date(2026, 7, 28)


def test_the_latest_close_at_or_before_the_run_date_wins(store):
    seed_store(store, "ACME", valuable_series())
    seed_price(store, "ACME", 900.0, date(2026, 7, 20))
    seed_price(store, "ACME", 1100.0, date(2026, 7, 29))
    assert _load(store).price == 1100.0


def test_no_price_is_a_named_missing_input_not_a_silent_skip(store):
    seed_store(store, "ACME", valuable_series())
    result = _load(store)
    assert not result.valued
    assert any("market:Close" in item for item in result.missing)


def test_the_valuations_numbers_become_derivations_the_law_1_validator_can_police(store):
    """ADR-0062's whole point: an agent restating a scenario value is checked against the priced grid."""
    seed_store(store, "ACME", valuable_series())
    seed_price(store, "ACME", 1000.0, date(2026, 7, 28))
    result = _load(store)
    assert result.valued, result.missing
    derivations = valuation_derivations(result)

    assert "base_case_value_per_share" in derivations
    for derivation in derivations.values():
        assert derivation.formula and derivation.inputs            # provenance, per Law 2

    # An unvalued run contributes nothing rather than zeroes.
    assert valuation_derivations(_load(store, as_of=date(2000, 1, 1))) == {}


def test_the_report_carries_the_valuation_and_renders_it(store, tmp_path):
    """End to end: the section a published report has never had until now."""
    seed_store(store, "CLEANCO", valuable_series())
    seed_price(store, "CLEANCO", 1500.0, date(2026, 7, 28))

    result = run_deep_dive(
        store, "CLEANCO", AS_OF, answers=clean_answers("CLEANCO"), filing=filing_for("CLEANCO"),
        company_name="Cleanco Limited", reports_root=tmp_path, write=True, memory_root=tmp_path)

    valuation = result.report.valuation
    assert valuation is not None and valuation.status == "valued", valuation.missing
    assert valuation.scenarios and {s.name for s in valuation.scenarios} == {
        "disaster", "bear", "base", "bull"}

    markdown = render_markdown(result.report)
    assert "## Valuation — what the price already assumes" in markdown
    assert "₹1,500.00" in markdown and "Reverse DCF" in markdown
    # The policy block is printed in every report that rests on it — a discount rate is a demand, not
    # a measurement, and burying it in config would hide the biggest assumption in the section.
    assert "discount_rate 0.13" in markdown
    assert "No exit multiple is assumed anywhere above" in markdown


def test_an_unvaluable_company_still_gets_the_section_with_its_gaps_named(store, tmp_path):
    seed_store(store, "CLEANCO", valuable_series())                # deliberately no price
    result = run_deep_dive(
        store, "CLEANCO", AS_OF, answers=clean_answers("CLEANCO"), filing=filing_for("CLEANCO"),
        company_name="Cleanco Limited", reports_root=tmp_path, write=True, memory_root=tmp_path)

    valuation = result.report.valuation
    assert valuation is not None and valuation.status == "unavailable"
    assert valuation.missing
    markdown = render_markdown(result.report)
    assert "**UNAVAILABLE**" in markdown
    assert "worse than none" in markdown          # the section explains why it refuses to default
