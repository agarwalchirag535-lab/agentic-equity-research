"""Test the deterministic company metric computation against a synthetic store."""

from datetime import date

from firm.core.facts.store import Document, FactStore
from firm.core.pipeline.metrics import compute_company_metrics


def _seed(store: FactStore) -> None:
    doc = Document("d1", "u", "s", date(2026, 6, 1), date(2026, 6, 1), "B", "v1")
    store.add_document(doc)
    # 12 years FY15-FY26 of a clean, growing, cash-generating company.
    fid = 0
    for i, fy in enumerate(range(15, 27)):
        sales = 1000 * (1.15**i)
        pat = 100 * (1.15**i)
        cfo = pat * 1.1
        for metric, val in [
            ("pnl:Sales", sales), ("pnl:Net Profit", pat), ("pnl:Operating Profit", pat * 1.6),
            ("pnl:Depreciation", pat * 0.2), ("pnl:Tax %", 0.25), ("pnl:Interest", pat * 0.1),
            ("cashflow:Cash from Operating Activity", cfo), ("cashflow:Free Cash Flow", cfo * 0.7),
            ("balance_sheet:Borrowings", 200), ("balance_sheet:Equity Capital", 50),
            ("balance_sheet:Reserves", 400 * (1.15**i)), ("balance_sheet:CWIP", 30),
            ("balance_sheet:Total Assets", 1500 * (1.15**i)),
        ]:
            store.add_fact(f"f{fid}", "d1", "TEST", metric, f"FY{fy:02d}", val, "INR_cr", "x")
            fid += 1


def test_compute_company_metrics():
    with FactStore() as store:
        _seed(store)
        m = compute_company_metrics(store, "TEST", as_of=date(2026, 7, 23))
    assert m["history"] == "FY15-FY26"
    assert m["revenue_cagr"] == __import__("pytest").approx(0.15, abs=0.005)
    assert m["cum_cfo_pat"] > 1.0                       # cash-generating
    assert m["forensic_verdict"] == "PASS"
    assert "4x/6y" in m["feasibility"]
    assert m["roic_latest"] is not None
