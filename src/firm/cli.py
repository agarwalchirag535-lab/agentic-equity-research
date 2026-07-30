"""`firm` CLI — the only entry point (Law 6). Never a notebook.

Phase 0/1: `gate-demo` exercises the §6.3 feasibility gate end-to-end with no data or LLM. `run` is a
stub until the pipeline lands in Phase 3.
"""

from __future__ import annotations

from datetime import date

import typer

from firm.core.compute.multibagger import feasibility_gate, required_earnings_cagr
from firm.core.config import load_thresholds
from firm.core.facts.store import Document, FactStore

app = typer.Typer(add_completion=False, help="Agentic equity research firm — research artifacts only.")


@app.command("gate-demo")
def gate_demo() -> None:
    """Phase 1 acceptance demo: the feasibility gate rejects an under-returning company and passes a
    high-ROIC self-funder — using thresholds from config/thresholds.yaml (no data, no LLM)."""
    mb = load_thresholds()["multibagger"]
    self_fund_ceiling = mb["self_fund_ceiling"]
    high_quality_ceiling = mb["high_quality_ceiling"]

    # 10x over 7 years, no re-rating -> required earnings CAGR (should print ~38.9%).
    g10 = required_earnings_cagr(total_return_multiple=10, years=7, rerating_multiple=1.0)
    typer.echo(f"Required earnings CAGR for 10x/7y, no re-rating: {g10:.1%}")

    typer.echo("\n-- Synthetic company A: ROIC 15%, needs 30% growth, no debt room, no dilution --")
    a = feasibility_gate(
        g_required=0.30, roic=0.15,
        self_fund_ceiling=self_fund_ceiling, high_quality_ceiling=high_quality_ceiling,
        debt_capacity_available=False, thesis_allows_dilution=False,
    )
    typer.echo(f"  verdict: {a.verdict.value}  (required reinvestment {a.required_reinvestment:.2f})")
    typer.echo(f"  {a.rationale}")

    typer.echo("\n-- Synthetic company B: ROIC 40%, needs 26% growth --")
    b = feasibility_gate(
        g_required=0.26, roic=0.40,
        self_fund_ceiling=self_fund_ceiling, high_quality_ceiling=high_quality_ceiling,
        debt_capacity_available=True, thesis_allows_dilution=True,
    )
    typer.echo(f"  verdict: {b.verdict.value}  (required reinvestment {b.required_reinvestment:.2f})")
    typer.echo(f"  {b.rationale}")


@app.command("facts-demo")
def facts_demo() -> None:
    """Phase 0 acceptance demo: point-in-time discipline (Law 3) on synthetic facts, no external data.

    Shows that 'revenue FY24 as-of 2024-08-01' returns the figure with provenance, while the same query
    as-of 2024-04-01 returns nothing — and that a later restatement stays invisible until published."""
    with FactStore() as store:
        store.add_document(Document(
            "AR-FY24", "https://example.test/AR-FY24", "deadbeef",
            date(2024, 8, 1), date(2024, 8, 1), "A", "ar-parser@1.0.0",
        ))
        store.add_fact("f1", "AR-FY24", "ACME", "revenue", "FY24", 1234.0, "INR_cr", "p.112")

        for as_of in (date(2024, 4, 1), date(2024, 8, 1)):
            got = store.query_fact("ACME", "revenue", "FY24", as_of=as_of)
            if got is None:
                typer.echo(f"revenue FY24 as-of {as_of}: <not published yet>")
            else:
                typer.echo(
                    f"revenue FY24 as-of {as_of}: {got.value} {got.unit} "
                    f"[grade {got.grade}, {got.doc_id} {got.locator}, pub {got.published_at}]"
                )


@app.command("ingest")
def ingest(
    ticker: str = typer.Option(..., "--ticker", help="NSE/BSE symbol, e.g. RELIANCE"),
    basis: str = typer.Option("default", help="default (screener's best) | consolidated | standalone"),
    db: str = typer.Option("data/firm.db", "--db"),
) -> None:
    """Fetch a company's 10-year financials from screener.in and load them into the fact store (LIVE).

    Raw HTML is saved immutably to data/bronze (Law 7); facts land in the point-in-time store with a
    screener provenance (grade B). Snapshot is honest for as-of=today. Warns if the data looks stale."""
    from pathlib import Path

    from firm.adapters.base.ingest import ingest_financials
    from firm.adapters.india.screener import fetch, parse_financials
    from firm.core.facts.store import FactStore

    today = date.today()
    html = fetch(ticker, basis=basis)
    Path("data/bronze").mkdir(parents=True, exist_ok=True)
    Path(f"data/bronze/screener-{ticker}-{today}.html").write_text(html)

    rows = parse_financials(html, ticker, consolidated=(basis != "standalone"))
    latest_period = max((r.period for r in rows), default="FY00")
    latest_fy = today.year if today.month >= 4 else today.year - 1
    if int(latest_period[2:]) < (latest_fy % 100) - 1:
        typer.echo(f"  ⚠ STALE: latest data is {latest_period} but current FY is FY{latest_fy % 100:02d} "
                   f"— try a different --basis (this page may be limited).")
    store = FactStore(db)
    n = ingest_financials(
        store, rows, doc_id=f"screener-{ticker}-{today}",
        source_url=f"https://www.screener.in/company/{ticker}/", published_at=today, raw_html=html,
    )
    typer.echo(f"ingested {n} facts for {ticker} -> {db}")
    latest_fy = today.year if today.month >= 4 else today.year - 1
    recent = [f"FY{y % 100:02d}" for y in range(latest_fy, latest_fy - 3, -1)]  # newest first
    for metric in ("pnl:Sales", "pnl:Net Profit", "cashflow:Cash from Operating Activity", "balance_sheet:CWIP"):
        for period in recent:
            f = store.query_fact(ticker, metric, period, as_of=today)
            if f is not None:
                typer.echo(f"  {metric} {period}: {f.value} {f.unit} [grade {f.grade}]")
                break
    store.close()


@app.command("forensic")
def forensic(
    ticker: str = typer.Option(..., "--ticker"),
    db: str = typer.Option("data/firm.db", "--db"),
) -> None:
    """Run the deterministic cash-reality forensic screen on ingested data (the 'is the cash real?' test).

    Reads Net Profit and CFO series from the fact store, computes cumulative ΣCFO/ΣPAT (does a decade of
    profit become cash?) and the latest CFO/PAT, and prints the Gate-B forensic verdict."""
    from firm.core.compute.quality import (
        ForensicMetrics, SectorClass, cfo_pat_ratio, cumulative_cfo_pat_ratio, forensic_screen,
    )
    from firm.core.config import forensic_thresholds
    from firm.core.facts.store import FactStore

    today = date.today()
    # Indian FY ends 31 Mar; a date after March is already past that year's FY close.
    latest_fy = today.year if today.month >= 4 else today.year - 1
    store = FactStore(db)
    years = [f"FY{y % 100:02d}" for y in range(2010, latest_fy + 1)]
    pat, cfo = {}, {}
    for p in years:
        np_fact = store.query_fact(ticker, "pnl:Net Profit", p, as_of=today)
        cfo_fact = store.query_fact(ticker, "cashflow:Cash from Operating Activity", p, as_of=today)
        if np_fact:
            pat[p] = np_fact.value
        if cfo_fact:
            cfo[p] = cfo_fact.value
    store.close()

    common = [p for p in years if p in pat and p in cfo]
    if not common:
        typer.echo(f"no ingested data for {ticker} — run `firm ingest --ticker {ticker}` first")
        raise typer.Exit(1)

    cum = cumulative_cfo_pat_ratio([cfo[p] for p in common], [pat[p] for p in common])
    latest = common[-1]
    cur = cfo_pat_ratio(cfo[latest], pat[latest])
    res = forensic_screen(
        SectorClass.NON_FINANCIAL,
        ForensicMetrics(cfo_pat=cur, cumulative_cfo_pat=cum),
        forensic_thresholds(),
    )
    typer.echo(f"{ticker}: {len(common)}y history  ΣCFO/ΣPAT={cum:.2f}  CFO/PAT({latest})={cur:.2f}")
    typer.echo(f"  forensic verdict: {res.verdict.value}")
    for f in res.flags:
        typer.echo(f"  flag: {f.name} [{f.severity.name}] {f.detail}")
    if not res.flags:
        typer.echo("  no cash-reality flags: reported profit is converting to cash")


@app.command("analyze")
def analyze(
    ticker: str = typer.Option(..., "--ticker"),
    db: str = typer.Option("data/firm.db", "--db"),
) -> None:
    """Compute the full deterministic metric set for an ingested company (Law 1 — numbers only)."""
    import json

    from firm.core.facts.store import FactStore
    from firm.core.pipeline.metrics import compute_company_metrics

    store = FactStore(db)
    m = compute_company_metrics(store, ticker, date.today())
    store.close()
    typer.echo(json.dumps(m, indent=2, default=str))


@app.command("run")
def run(ticker: str = typer.Option(..., "--ticker"), as_of: str = typer.Option(..., "--as-of")) -> None:
    """Run the full pipeline for a ticker as-of a date. Not implemented until Phase 3."""
    raise typer.Exit(  # pragma: no cover
        typer.echo(
            f"[not implemented] pipeline for {ticker} as-of {as_of} lands in Phase 3 "
            "(orchestrator + gates). See docs/PLAN.md."
        )
    )


if __name__ == "__main__":  # pragma: no cover
    app()
