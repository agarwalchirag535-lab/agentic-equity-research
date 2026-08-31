"""Compute the full deterministic metric set for a company from the fact store (Law 1, Law 3).

This is the 'numbers' half of a full analysis — everything the financial / forensic / valuation agents
reason over, computed purely from stored facts as-of a date. No LLM, no network.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from firm.core.compute import multibagger, quality
from firm.core.compute import ratios as R
from firm.core.compute import roic as RO
from firm.core.facts.store import FactStore


def _series(store: FactStore, ticker: str, metric: str, years: list[str], as_of: date) -> dict[str, float]:
    out: dict[str, float] = {}
    for p in years:
        f = store.query_fact(ticker, metric, p, as_of=as_of)
        if f is not None:
            out[p] = f.value
    return out


def _cagr(first: float, last: float, n: int) -> float | None:
    if n <= 0 or first <= 0 or last <= 0:
        return None
    return (last / first) ** (1.0 / n) - 1.0


def compute_company_metrics(
    store: FactStore, ticker: str, as_of: date, start_year: int | None = None
) -> dict[str, Any]:
    latest_fy = as_of.year if as_of.month >= 4 else as_of.year - 1
    if start_year is None:  # the window is what the evidence covers (ADR-0055)
        start_year = store.earliest_annual_year(ticker, as_of) or latest_fy
    years = [f"FY{y % 100:02d}" for y in range(start_year, latest_fy + 1)]

    def S(metric: str) -> dict[str, float]:
        return _series(store, ticker, metric, years, as_of)

    sales, pat, op = S("pnl:Sales"), S("pnl:Net Profit"), S("pnl:Operating Profit")
    dep, tax, interest = S("pnl:Depreciation"), S("pnl:Tax %"), S("pnl:Interest")
    cfo, fcf = S("cashflow:Cash from Operating Activity"), S("cashflow:Free Cash Flow")
    borrow, eqcap = S("balance_sheet:Borrowings"), S("balance_sheet:Equity Capital")
    res, cwip, ta = S("balance_sheet:Reserves"), S("balance_sheet:CWIP"), S("balance_sheet:Total Assets")

    common = [p for p in years if p in sales and p in pat and p in cfo]
    if not common:
        return {"ticker": ticker, "error": "no ingested data"}
    f0, fN = common[0], common[-1]
    n = int(fN[2:]) - int(f0[2:])

    def ebit(p: str) -> float:
        return op.get(p, 0.0) - dep.get(p, 0.0)

    def nopat(p: str) -> float:
        return RO.nopat(ebit(p), tax.get(p, 0.25))

    def invested(p: str) -> float:
        return borrow.get(p, 0.0) + eqcap.get(p, 0.0) + res.get(p, 0.0)

    roic_N = RO.roic(nopat(fN), invested(fN)) if invested(fN) else None
    ic_series = [invested(p) for p in common]
    nop_series = [nopat(p) for p in common]
    inc_roic = RO.rolling_incremental_roic(nop_series, ic_series, window=3) if len(common) > 3 else []

    cash_common = [p for p in common if p in cfo and pat.get(p)]
    cum_cfo_pat = quality.cumulative_cfo_pat_ratio([cfo[p] for p in cash_common], [pat[p] for p in cash_common])
    cfo_pat_N = quality.cfo_pat_ratio(cfo[fN], pat[fN]) if pat.get(fN) else None
    fcf_common = [p for p in common if p in fcf and pat.get(p)]
    cum_fcf_pat = (sum(fcf[p] for p in fcf_common) / sum(pat[p] for p in fcf_common)) if fcf_common else None

    metrics: dict[str, Any] = {
        "ticker": ticker,
        "as_of": as_of.isoformat(),
        "history": f"{f0}-{fN}",
        "years": n,
        "stale": int(fN[2:]) < (latest_fy % 100) - 1,  # data-quality guard (see ADR-0009)
        "revenue_cagr": _cagr(sales[f0], sales[fN], n),
        "revenue_cagr_5y": _cagr(sales.get(f"FY{int(fN[2:]) - 5:02d}", 0), sales[fN], 5),
        "pat_cagr": _cagr(pat[f0], pat[fN], n),
        "opm_latest": op.get(fN, 0) / sales[fN] if sales.get(fN) else None,
        "opm_first": op.get(f0, 0) / sales[f0] if sales.get(f0) else None,
        "roic_latest": roic_N,
        "incremental_roic_3y": [round(x, 3) for x in inc_roic],
        "cum_cfo_pat": round(cum_cfo_pat, 2),
        "cfo_pat_latest": round(cfo_pat_N, 2) if cfo_pat_N is not None else None,
        "cum_fcf_pat": round(cum_fcf_pat, 2) if cum_fcf_pat is not None else None,
        "interest_coverage_latest": R.interest_coverage(ebit(fN), interest[fN]) if interest.get(fN) else None,
        "borrowings_first": borrow.get(f0),
        "borrowings_latest": borrow.get(fN),
        "cwip_pct_assets_first": (cwip.get(f0, 0) / ta[f0]) if ta.get(f0) else None,
        "cwip_pct_assets_latest": (cwip.get(fN, 0) / ta[fN]) if ta.get(fN) else None,
        "sales_latest_cr": sales.get(fN),
        "pat_latest_cr": pat.get(fN),
        "fcf_latest_cr": fcf.get(fN),
    }

    # Forensic (deterministic Gate-B) verdict on the cash-reality signals.
    fmetrics = quality.ForensicMetrics(cfo_pat=cfo_pat_N, cumulative_cfo_pat=cum_cfo_pat)
    from firm.core.config import forensic_thresholds

    screen = quality.forensic_screen(quality.SectorClass.NON_FINANCIAL, fmetrics, forensic_thresholds())
    metrics["forensic_verdict"] = screen.verdict.value
    metrics["forensic_flags"] = [f.name for f in screen.flags]

    # Feasibility gate for target multiples, at the company's own ROIC.
    if roic_N and roic_N > 0:
        feas = {}
        for label, mult, yrs in [("4x/6y", 4, 6), ("5x/7y", 5, 7)]:
            g = multibagger.required_earnings_cagr(mult, yrs, 1.0)
            gate = multibagger.feasibility_gate(
                g_required=g, roic=roic_N, self_fund_ceiling=1.0, high_quality_ceiling=0.6,
                debt_capacity_available=True, thesis_allows_dilution=False,
            )
            feas[label] = {"required_cagr": round(g, 3), "verdict": gate.verdict.value,
                           "required_reinvestment": round(gate.required_reinvestment, 2)}
        metrics["feasibility"] = feas
    return metrics
