"""Screener parser tested against a saved real HTML fixture (no network)."""

from datetime import date
from pathlib import Path

from firm.adapters.base.ingest import ingest_financials
from firm.adapters.india.screener import parse_financials, parse_shareholding
from firm.core.facts.store import FactStore

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "screener_reliance.html"
HTML = FIXTURE.read_text()


def test_parse_financials_extracts_known_values():
    rows = parse_financials(HTML, "RELIANCE")
    sales_fy15 = [r for r in rows if r.statement == "pnl" and r.metric == "Sales" and r.period == "FY15"]
    assert len(sales_fy15) == 1
    r = sales_fy15[0]
    assert r.value == 374372.0
    assert r.unit == "INR_cr"
    assert r.consolidated is True
    assert r.source == "screener"

    statements = {r.statement for r in rows}
    assert statements == {"pnl", "balance_sheet", "cashflow"}
    # periods are fiscal-year tokens, never the TTM column
    assert all(r.period.startswith("FY") for r in rows)


def test_parse_shareholding():
    sh = parse_shareholding(HTML, "RELIANCE")
    promoters = [s for s in sh if s.category == "promoter"]
    assert promoters, "expected promoter shareholding rows"
    assert all(0.0 <= s.pct <= 100.0 for s in sh)


def test_ingest_into_fact_store_is_queryable_point_in_time():
    rows = parse_financials(HTML, "RELIANCE")
    with FactStore() as store:
        n = ingest_financials(
            store, rows, doc_id="screener-RELIANCE-2026-07-23",
            source_url="https://www.screener.in/company/RELIANCE/consolidated/",
            published_at=date(2026, 7, 23), raw_html=HTML,
        )
        assert n == len(rows)
        got = store.query_fact("RELIANCE", "pnl:Sales", "FY15", as_of=date(2026, 7, 23))
        assert got is not None and got.value == 374372.0 and got.grade == "B"
