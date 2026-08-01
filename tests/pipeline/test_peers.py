"""Comparing a company against a peer on a common period (Phase 3).

The defect this module exists to prevent is not a crash — it is a comparison that looks entirely normal
and measures two different years. The subject usually files before its peer, so "each company's latest"
silently compares FY26 against FY25 across a period in which prices, input costs and demand all moved.
"""

from __future__ import annotations

from datetime import date

import pytest

from firm.core.pipeline.derive import load_company_facts
from firm.core.pipeline.peers import (
    citable_values,
    compare,
    load_peer_comparisons,
    payload_rows,
)
from tests.conftest import AS_OF, seed_store

#: A peer whose record is SHORTER than the subject's and stops a year earlier — the ordinary case, and
#: the one that produces the cross-year comparison if periods are not aligned.
PEER_PERIODS = ("FY21", "FY22", "FY23", "FY24", "FY25")


def _facts(store, ticker, series, periods, grade="A"):
    seed_store(store, ticker, series, periods=periods, doc_id=f"ar-{ticker}", grade=grade)
    return load_company_facts(store, ticker, AS_OF)


def _subject(store, **overrides):
    series = {
        "pnl:Sales": [600, 700, 800, 900, 1000, 1050],
        "pnl:Net Profit": [60, 72, 85, 100, 118, 130],
        "balance_sheet:Trade Receivables": [60, 70, 80, 90, 100, 105],
    }
    series.update(overrides)
    return _facts(store, "SUBJ", series, ("FY21", "FY22", "FY23", "FY24", "FY25", "FY26"))


def _peer(store, **overrides):
    series = {
        "pnl:Sales": [500, 520, 540, 560, 580],
        "pnl:Net Profit": [40, 41, 42, 43, 44],
        "balance_sheet:Trade Receivables": [90, 95, 100, 105, 110],
    }
    series.update(overrides)
    return _facts(store, "PEER", series, PEER_PERIODS)


def test_every_row_is_measured_on_one_period_both_companies_cover(store):
    """The subject has FY26 and the peer does not, so every row must land on FY25 — for BOTH sides."""
    result = compare(_subject(store), _peer(store))
    assert result.comparable

    point_rows = [m for m in result.metrics if m.metric != "sales_cagr"]
    assert {m.period for m in point_rows} == {"FY25"}

    sales = next(m for m in point_rows if m.metric == "sales")
    assert sales.subject.value == 1000    # FY25, NOT the FY26 figure of 1050
    assert sales.peer.value == 580


def test_growth_uses_the_window_both_companies_cover(store):
    """Measuring each company over its own record compares a full cycle against a partial one."""
    cagr = next(m for m in compare(_subject(store), _peer(store)).metrics if m.metric == "sales_cagr")
    assert cagr.period == "FY21-FY25"
    # 600 -> 1000 over four years, not 600 -> 1050 over five.
    assert cagr.subject.value == pytest.approx((1000 / 600) ** (1 / 4) - 1)
    assert cagr.peer.value == pytest.approx((580 / 500) ** (1 / 4) - 1)


def test_a_measure_with_no_common_period_says_so_instead_of_disappearing(store):
    """A silently absent row reads as "these companies are alike here". It must read as "not compared"."""
    result = compare(_subject(store), _peer(store, **{"balance_sheet:Trade Receivables": []}))
    assert all(m.metric != "receivable_days" for m in result.metrics)
    reason = next(r for r in result.incomparable if r.startswith("receivable_days"))
    assert "share no period" in reason and "Trade Receivables" in reason


def test_a_comparison_is_only_as_good_as_its_worst_side(store):
    """A grade-A subject measured against a grade-B peer is a grade-B comparison."""
    subject = _subject(store)
    peer = _facts(store, "WEAK", {"pnl:Sales": [500, 520, 540, 560, 580]}, PEER_PERIODS, grade="B")
    sales = next(m for m in compare(subject, peer).metrics if m.metric == "sales")
    assert sales.grade == "B"


def test_an_undefined_measure_is_not_reported_as_a_number(store):
    """Zero sales makes a margin undefined. That is a real state of the world, not a reason to print 0."""
    result = compare(_subject(store), _peer(store, **{"pnl:Sales": [500, 520, 540, 560, 0]}))
    margin = next((m for m in result.metrics if m.metric == "net_margin"), None)
    # FY25 is unusable for the peer, so the latest common period with usable sales is earlier — never a
    # zero-division, and never a fabricated figure.
    assert margin is None or margin.period != "FY25"


def test_a_named_peer_with_no_facts_is_a_stated_coverage_gap(store):
    """"We have no data on the peer we named" is a finding about the firm, not a row to omit."""
    _subject(store)
    result = load_peer_comparisons(store, "SUBJ", ["GHOST"], AS_OF)[0]
    assert result.comparable is False
    assert "no facts for GHOST" in result.incomparable[0]


def test_point_in_time_applies_to_the_peer_too(store):
    """A peer's filing published after as_of must not inform the comparison (Law 3)."""
    _subject(store)
    seed_store(store, "LATE", {"pnl:Sales": [500, 520, 540, 560, 580]}, periods=PEER_PERIODS,
               doc_id="ar-LATE", published_at=date(2026, 12, 1))
    assert load_peer_comparisons(store, "SUBJ", ["LATE"], AS_OF)[0].comparable is False


def test_both_sides_of_every_row_are_citable(store):
    """An agent must be able to quote the peer's number, which means a real id holding that exact value."""
    comparisons = [compare(_subject(store), _peer(store))]
    values = citable_values(comparisons)
    assert values["peer:SUBJ:sales:FY25"] == 1000
    assert values["peer:PEER:sales:FY25"] == 580

    rows = payload_rows(comparisons)
    sales = next(m for m in rows[0]["metrics"] if m["metric"] == "sales")
    assert sales["SUBJ"]["cite_as"] == "[fact:peer:SUBJ:sales:FY25]"
    assert sales["PEER"]["cite_as"] == "[fact:peer:PEER:sales:FY25]"
