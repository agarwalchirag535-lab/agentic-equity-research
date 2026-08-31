"""Two defects the Symphony Ltd run surfaced, both of which produce confident wrong numbers on a
company doing nothing unusual (ADR-0048)."""

from __future__ import annotations

from datetime import date

import pytest

from firm.core.facts.store import Document, FactStore
from firm.core.pipeline import derive as D


def _store(rows: dict[tuple[str, str], float]) -> FactStore:
    store = FactStore(":memory:")
    doc, pub = "AR-X", date(2018, 8, 31)
    store.add_document(Document(doc_id=doc, source_url="u", sha256="", published_at=pub,
                                fetched_at=pub, grade="A", extractor_version="t@1"))
    for (metric, period), value in rows.items():
        store.add_fact(fact_id=f"{doc}:{metric}:{period}", doc_id=doc, ticker="T", metric=metric,
                       period=period, value=value, unit="INR_cr", locator="p.1")
    return store


#: Symphony FY18 consolidated, in Rs crore: an outsourced-manufacturing model where goods BOUGHT
#: finished (293.14) dwarf materials consumed (93.89).
SYMPHONY_FY18 = {
    (D.SALES, "FY18"): 798.25, (D.PAT, "FY18"): 192.55,
    (D.MATERIALS, "FY18"): 93.89, (D.PURCHASES_STOCK_IN_TRADE, "FY18"): 293.14,
    (D.INVENTORY_CHANGE, "FY18"): -1.70,
    (D.INVENTORY, "FY18"): 79.57, (D.PAYABLES, "FY18"): 58.35, (D.RECEIVABLES, "FY18"): 61.51,
    (D.TOTAL_ASSETS, "FY18"): 756.55, (D.CFO, "FY18"): 106.86,
}


def test_the_cost_base_includes_goods_bought_for_resale():
    """Materials-only put Symphony's inventory at 315 days against a true 75 — a 4x error on turnover
    ratios for every company that outsources its manufacturing."""
    facts = D.load_company_facts(_store(SYMPHONY_FY18), "T", date(2018, 12, 31), start_year=2018)
    derived = D.derive_metrics(facts)
    assert derived.values["inventory_days"].value == pytest.approx(75.4, abs=0.5)
    assert derived.values["payable_days"].value == pytest.approx(55.3, abs=0.5)
    # the formula names every line summed, so a reader can redo it from the page
    assert "Purchases of Stock-in-Trade" in derived.values["inventory_days"].formula


def test_a_filing_that_prints_no_purchases_line_is_unaffected():
    rows = {k: v for k, v in SYMPHONY_FY18.items() if k[0] != D.PURCHASES_STOCK_IN_TRADE}
    derived = D.derive_metrics(
        D.load_company_facts(_store(rows), "T", date(2018, 12, 31), start_year=2018))
    assert derived.values["inventory_days"].value == pytest.approx(314.9, abs=0.5)
    assert "Purchases" not in derived.values["inventory_days"].formula


def test_a_cumulative_ratio_needs_a_window_long_enough_to_mean_something():
    """The false positive: over the two years readable from one filing, Symphony's cash conversion is
    0.56 and the screen returned SEVERE on a clean compounder. A cumulative claim is a claim about a
    cycle; below the floor it is refused with the reason, never flagged."""
    rows = dict(SYMPHONY_FY18)
    rows.update({(D.SALES, "FY17"): 764.75, (D.PAT, "FY17"): 166.28, (D.CFO, "FY17"): 94.65})
    facts = D.load_company_facts(_store(rows), "T", date(2018, 12, 31), start_year=2017)

    short = D.derive_metrics(facts, forensic={"cumulative_cfo_pat_min_periods": 3})
    assert "cum_cfo_pat" not in short.values
    reason = short.missing["cum_cfo_pat"][0]
    assert "only 2 annual period(s)" in reason and "at least 3" in reason

    # with the floor satisfied the metric is computed exactly as before — the guard adds no bias
    ok = D.derive_metrics(facts, forensic={"cumulative_cfo_pat_min_periods": 2})
    assert ok.values["cum_cfo_pat"].value == pytest.approx((106.86 + 94.65) / (192.55 + 166.28), abs=1e-4)
