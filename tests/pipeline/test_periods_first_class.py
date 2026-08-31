"""ADR-0049, the consumer half: the three places FY-label arithmetic silently lied once a company's
year-end was not 31 March — CAGR exponents, `resolve_by` dates, and peer windows."""

from __future__ import annotations

from datetime import date

import pytest

from firm.core.facts.store import Document, FactStore
from firm.core.pipeline import derive as D
from firm.core.pipeline import peers as PE
from firm.core.report.criteria import resolve_by

PERIODS_POLICY = {"label_span_tolerance_days": 45.0, "peer_close_tolerance_days": 7.0}


def _store(rows: dict[tuple[str, str], float], ends: dict[str, date] | None = None,
           ticker: str = "T") -> FactStore:
    store = FactStore(":memory:")
    doc, pub = f"AR-{ticker}", date(2018, 8, 31)
    store.add_document(Document(doc_id=doc, source_url="u", sha256="", published_at=pub,
                                fetched_at=pub, grade="A", extractor_version="t@1"))
    for (metric, period), value in rows.items():
        store.add_fact(fact_id=f"{doc}:{metric}:{period}", doc_id=doc, ticker=ticker, metric=metric,
                       period=period, value=value, unit="INR_cr", locator="p.1",
                       period_end=(ends or {}).get(period))
    return store


# ---- the store carries what the filing stated -----------------------------------------------------

def test_a_stored_fact_round_trips_its_stated_close():
    store = _store({(D.SALES, "FY15"): 531.61}, {"FY15": date(2015, 6, 30)})
    fact = store.query_fact("T", D.SALES, "FY15", as_of=date(2018, 12, 31))
    assert fact is not None and fact.period_end == date(2015, 6, 30)


def test_a_pre_adr_0049_store_gains_the_column_in_place(tmp_path):
    """An on-disk store created before the column existed must open, migrate, and keep its facts."""
    import sqlite3

    path = str(tmp_path / "facts.db")
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE documents (doc_id TEXT PRIMARY KEY, source_url TEXT NOT NULL,
            sha256 TEXT NOT NULL, published_at TEXT NOT NULL, fetched_at TEXT NOT NULL,
            grade TEXT NOT NULL, extractor_version TEXT NOT NULL);
        CREATE TABLE facts (fact_id TEXT PRIMARY KEY, doc_id TEXT NOT NULL REFERENCES
            documents(doc_id), ticker TEXT NOT NULL, metric TEXT NOT NULL, period TEXT NOT NULL,
            value REAL NOT NULL, unit TEXT NOT NULL, locator TEXT NOT NULL);
        INSERT INTO documents VALUES ('d', 'u', '', '2018-08-31', '2018-08-31', 'A', 't@1');
        INSERT INTO facts VALUES ('d:pnl:Sales:FY18', 'd', 'T', 'pnl:Sales', 'FY18',
            798.25, 'INR_cr', 'p.1');
    """)
    conn.commit()
    conn.close()

    store = FactStore(path)
    fact = store.query_fact("T", "pnl:Sales", "FY18", as_of=date(2018, 12, 31))
    assert fact is not None and fact.value == 798.25 and fact.period_end is None
    store.add_fact(fact_id="d:pnl:Sales:FY17", doc_id="d", ticker="T", metric="pnl:Sales",
                   period="FY17", value=764.75, unit="INR_cr", locator="p.1",
                   period_end=date(2017, 3, 31))
    migrated = store.query_fact("T", "pnl:Sales", "FY17", as_of=date(2018, 12, 31))
    assert migrated is not None and migrated.period_end == date(2017, 3, 31)


# ---- CAGRs ----------------------------------------------------------------------------------------

JUNE_TO_MARCH = {
    (D.SALES, "FY15"): 531.61, (D.PAT, "FY15"): 110.02,
    (D.SALES, "FY18"): 798.25, (D.PAT, "FY18"): 192.55,
}
ENDS = {"FY15": date(2015, 6, 30), "FY18": date(2018, 3, 31)}


def test_a_cagr_across_a_year_end_change_compounds_over_the_true_elapsed_years():
    """FY15 closed 30 June 2015 and FY18 closed 31 March 2018 — 2.75 years lived, 3 counted by the
    labels. The label exponent understates growth on every such window."""
    facts = D.load_company_facts(_store(JUNE_TO_MARCH, ENDS), "T", date(2018, 12, 31),
                                 start_year=2015)
    derived = D.derive_metrics(facts, forensic={}, periods_policy=PERIODS_POLICY)
    got = derived.values["revenue_cagr"]
    assert got.value == pytest.approx((798.25 / 531.61) ** (1 / 2.7516) - 1, abs=1e-4)
    assert got.value == pytest.approx(0.1592, abs=0.002)   # the label exponent would say 14.5%
    # the formula prints the exponent the computation used, so a reader can replicate it
    assert "1/2.7516" in got.formula
    assert derived.fy_close == date(2018, 3, 31)


def test_labels_alone_keep_the_status_quo_exponent():
    facts = D.load_company_facts(_store(JUNE_TO_MARCH), "T", date(2018, 12, 31), start_year=2015)
    derived = D.derive_metrics(facts, forensic={}, periods_policy=PERIODS_POLICY)
    assert "1/3" in derived.values["revenue_cagr"].formula
    assert derived.fy_close is None


# ---- resolve_by -----------------------------------------------------------------------------------

def test_a_june_closers_criterion_resolves_against_a_june_filing():
    # next close after 31 Dec 2015 for a 30-June closer is 30 June 2016; +210-day filing lag
    deadline = resolve_by(date(2015, 12, 31), 1, 210, fy_close=date(2015, 6, 30))
    assert deadline == date(2017, 1, 26)


def test_the_march_default_is_unchanged_for_an_undated_company():
    # 31 March 2027 close + 210 days — byte-identical to the pre-ADR-0049 behaviour
    assert resolve_by(date(2026, 8, 1), 1, 210) == date(2027, 10, 27)


# ---- peers ----------------------------------------------------------------------------------------

PEER_ROWS = {
    (D.SALES, "FY15"): 400.0, (D.PAT, "FY15"): 40.0,
    (D.SALES, "FY18"): 600.0, (D.PAT, "FY18"): 66.0,
}


def test_one_label_two_year_ends_is_not_one_window():
    """Both companies file a 'FY15', but one closes 31 March and the other 30 June — different
    twelve-month windows through different price environments. Refused with the reason, not compared."""
    subject = D.load_company_facts(
        _store(JUNE_TO_MARCH, {"FY15": date(2015, 3, 31), "FY18": date(2018, 3, 31)}, "SUBJ"),
        "SUBJ", date(2018, 12, 31), start_year=2015)
    peer = D.load_company_facts(
        _store(PEER_ROWS, {"FY15": date(2015, 6, 30), "FY18": date(2018, 3, 31)}, "PEER"),
        "PEER", date(2018, 12, 31), start_year=2015)
    result = PE.compare(subject, peer, periods_policy=PERIODS_POLICY)
    # FY18 aligns, so point measures compare there; the growth window's FY15 bound does not
    assert any(m.metric == "sales" and m.period == "FY18" for m in result.metrics)
    growth_reasons = [r for r in result.incomparable if r.startswith("sales_cagr")]
    assert growth_reasons and "not the same twelve-month window" in growth_reasons[0]
    assert "2015-03-31" in growth_reasons[0] and "2015-06-30" in growth_reasons[0]


def test_aligned_closes_compare_exactly_as_before():
    ends = {"FY15": date(2015, 3, 31), "FY18": date(2018, 3, 31)}
    subject = D.load_company_facts(_store(JUNE_TO_MARCH, ends, "SUBJ"), "SUBJ",
                                   date(2018, 12, 31), start_year=2015)
    peer = D.load_company_facts(_store(PEER_ROWS, ends, "PEER"), "PEER",
                                date(2018, 12, 31), start_year=2015)
    result = PE.compare(subject, peer, periods_policy=PERIODS_POLICY)
    growth = next(m for m in result.metrics if m.metric == "sales_cagr")
    assert growth.period == "FY15-FY18"
    assert growth.subject.value == pytest.approx((798.25 / 531.61) ** (1 / 3) - 1, abs=1e-6)


def test_a_side_with_no_stated_closes_is_not_refused_for_our_own_gap():
    """A screener-only peer has no stated closes; charging the comparison for the firm's own missing
    extractor would violate the capability-vs-disclosure rule. It compares as before, at its grade."""
    subject = D.load_company_facts(
        _store(JUNE_TO_MARCH, {"FY15": date(2015, 3, 31), "FY18": date(2018, 3, 31)}, "SUBJ"),
        "SUBJ", date(2018, 12, 31), start_year=2015)
    peer = D.load_company_facts(_store(PEER_ROWS, None, "PEER"), "PEER",
                                date(2018, 12, 31), start_year=2015)
    result = PE.compare(subject, peer, periods_policy=PERIODS_POLICY)
    assert any(m.metric == "sales_cagr" for m in result.metrics)
