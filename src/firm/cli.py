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
        ForensicMetrics,
        SectorClass,
        cfo_pat_ratio,
        cumulative_cfo_pat_ratio,
        forensic_screen,
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


@app.command("discover-filings")
def discover_filings_cmd(
    ticker: str = typer.Option(..., "--ticker", help="NSE/BSE symbol, e.g. ALKYLAMINE"),
    url: str = typer.Option(..., "--url", help="the company's investor-relations financials page"),
    out: str = typer.Option("", "--out", help="default data/manifests/{TICKER}-filings.json"),
    company: str = typer.Option("", "--company", help="display name for the manifest"),
) -> None:
    """Find the annual reports on a listed company's own IR page and write a filings manifest.

    Works for any Indian listed company: Reg. 46 of the SEBI LODR requires every one of them to publish its
    annual reports on its own website. Reads the page, recognises the annual reports among the other PDFs,
    and records for each the fiscal year it covers, its URL, and a publication date WITH ITS BASIS —
    `upload-path` where the publisher's own URL evidences the month, `statutory-proxy` where the file was
    re-uploaded later and the AGM deadline is the honest fallback (ADR-0026).

    Downloads nothing. Retrieval is a separate, deliberate step: pulling tens of megabytes from a company's
    servers deserves a human decision per company, which a discovery pass that fetched silently would remove.
    Fill in `sha256`/`bytes` after retrieving, then run `firm deep-dive --filings <manifest>`.
    """
    import json
    import ssl
    import urllib.request
    from pathlib import Path

    # A framework Python on macOS ships no CA bundle for urllib (curl works because it uses the system
    # store), so an IR page over https fails with CERTIFICATE_VERIFY_FAILED. `certifi` is already a
    # declared dependency of the india extra; verification is never disabled — a research firm reading a
    # company's own disclosures must know it reached that company.
    try:
        import certifi

        context = ssl.create_default_context(cafile=certifi.where())
    except ImportError:  # pragma: no cover - falls back to the interpreter's default trust store
        context = ssl.create_default_context()

    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=60, context=context) as response:  # noqa: S310
        html = response.read().decode("utf-8", errors="replace")

    from firm.adapters.india.ir_pages import discover_filings

    found = discover_filings(html, ticker)
    if not found:
        typer.echo(f"no annual reports recognised at {url}")
        raise typer.Exit(1)

    manifest = {
        "ticker": ticker,
        "company_name": company or ticker,
        "source": url,
        "retrieved_at": date.today().isoformat(),
        "filings": [
            {
                "file": c.suggested_file, "period": c.period, "prior_period": c.prior_period,
                "source_url": c.url, "published_at": c.published_at.isoformat(),
                "published_at_basis": c.published_at_basis, "grade": "A", "sha256": "", "bytes": 0,
            }
            for c in found
        ],
    }
    path = Path(out or f"data/manifests/{ticker}-filings.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    typer.echo(f"{len(found)} annual report(s) -> {path}")
    for c in found:
        typer.echo(f"  {c.period}  {c.published_at}  ({c.published_at_basis})  {c.suggested_file}")
    typer.echo("\nNext: download each source_url into data/bronze/ under `file`, fill sha256/bytes, then")
    typer.echo(f"  firm deep-dive --ticker {ticker} --filings {path}")


@app.command("deep-dive")
def deep_dive(
    ticker: str = typer.Option(..., "--ticker", help="NSE/BSE symbol, e.g. ALKYLAMINE"),
    as_of: str = typer.Option("", "--as-of", help="point-in-time date (YYYY-MM-DD); default today"),
    db: str = typer.Option("data/firm.db", "--db"),
    provider: str = typer.Option(
        "local", "--provider",
        help="local | claude_code | anthropic | openai (or use --answers for Claude-in-the-loop)"),
    answers: str = typer.Option(
        "", "--answers", help="directory of {agent}.json answers (ADR-0010 path, no API key needed)"),
    model: str = typer.Option("analysis", "--model", help="model role key from config/models.yaml"),
    company: str = typer.Option("", "--company", help="display name for the report header"),
    reports_root: str = typer.Option("reports", "--reports-root"),
    filings: str = typer.Option(
        "", "--filings",
        help="path to a filings manifest (data/manifests/{TICKER}-filings.json). Ingests every audited "
             "annual report published on/before --as-of as grade-A facts and walks the latest one's notes. "
             "Without this the run rests on a grade-B screener snapshot (ADR-0024)."),
    bronze: str = typer.Option("data/bronze", "--bronze", help="where the manifest's PDFs live"),
    readings: str = typer.Option(
        "", "--readings",
        help="directory of verified reading answers ({file stem}.reading.json, ADR-0046/0055). With "
             "--filings, numeric facts come from the READING path — every figure verified against the "
             "page text, every period dated — and the walker only scans the latest filing's notes. A "
             "filing with no reading is reported, never silently walked."),
    phase: int = typer.Option(
        2, "--phase",
        help="build phase (SPEC §11). Selects the agent roster from config/roster.yaml; agents above this "
             "phase are refused, so the build order is enforced rather than remembered (ADR-0030)."),
    documents: str = typer.Option(
        "", "--documents",
        help="path to a documents manifest (data/manifests/{TICKER}-documents.json). Determines which "
             "roster prerequisites are satisfied, so agent coverage is derived from what is actually "
             "ingested rather than asserted (ADR-0031)."),
    peer: list[str] = typer.Option(
        [], "--peer",
        help="a peer ticker whose facts are already ingested; repeatable. Satisfies the roster's `peers` "
             "prerequisite for sector_analyst. Every comparison is measured on a period BOTH companies "
             "cover, so the subject's newest year is never compared against a peer's older one."),
    force: bool = typer.Option(
        False, "--force", help="write the report even if a publication gate fails (debugging only)"),
) -> None:
    """Phase 2: run the three Tier-2 agents onto the evidence graph and publish the dual-verdict report.

    Deterministic first: facts → derivations → business-model playbook → every check evaluated → Gate-B
    forensic screen → §6.3 feasibility. Then the agents narrate (they never produce a number), their
    claims become evidence-graph fragments checked against R1-R6, and the report ships only if the P1/P2/P3
    publication gates pass. Output: reports/{TICKER}/{run_id}/report.md + report.json.
    """
    import os

    from firm.core.llm.provider import build_provider
    from firm.core.pipeline.deep_dive import plan_agents, read_answers, run_deep_dive
    from firm.core.report.render import write_report

    run_date = date.fromisoformat(as_of) if as_of else date.today()
    # Answers are read AFTER the roster is known (below): `read_answers` defaults to the Phase-2 trio, so
    # reading here would silently ignore the five phase-3 answer files sitting in the same directory and
    # then fail pre-flight claiming they were never written.
    prepared = None
    key_env = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}.get(provider)
    llm = build_provider(provider, os.environ.get(key_env) if key_env else None)

    store = FactStore(db)
    try:
        # PRIMARY SOURCES FIRST (owner directive 1, ADR-0024). Every annual report in the manifest that
        # was published on or before `as_of` is ingested as grade-A facts; the most recent one is then
        # handed to the run so its NOTES are enumerated and dispositioned, which is what the cash and
        # related-party checks read. Without a manifest the run is screener-only and says so.
        latest_filing = None
        if filings:
            from firm.core.config import load_thresholds
            from firm.core.ingest.filings import (
                filing_from_manifest,
                ingest_manifest,
                load_manifest,
                quarantine_extraction_errors,
            )
            from firm.core.pipeline.filing import COMPOSED_ROWS, FILING_ROWS

            manifest = load_manifest(filings)
            if readings:
                # THE READING PATH (ADR-0046/0055): every figure verified against the page text before
                # it may be stored, every period dated by its filing's own words. A manifest filing
                # with no answered reading is a named gap, never a silent fallback to the walker.
                from firm.core.ingest.filings import quarantine_store_contradictions
                from firm.core.ingest.reading import fetch_pdf, ingest_readings_manifest

                results = ingest_readings_manifest(
                    store, manifest, readings_dir=readings, bronze=bronze, as_of=run_date,
                    fetcher=fetch_pdf)
                registered = [r for r in results if r.status == "registered"]
                typer.echo(f"  readings: {len(registered)} of {len(results)} filings registered "
                           f"({sum(len(r.fact_ids) for r in registered)} verified facts)")
                for r in results:
                    for stub in r.skipped_stub_flows[:2]:
                        typer.echo(f"    {r.file}: refused stub flow — {stub}")
                    if r.status == "refused":
                        typer.echo(f"  ✗ {r.file}: reading REFUSED — "
                                   f"{r.violations[0].rule}: {r.violations[0].detail[:100]}")
                    elif r.status in ("no_reading", "pdf_mismatch"):
                        typer.echo(f"  ⚠ {r.file}: {r.status} — {r.detail[:120]}")
                for rec in quarantine_store_contradictions(
                        store, ticker, run_date, load_thresholds()["reconciliation"]):
                    o = rec.overlap
                    typer.echo(
                        f"  ⚠ {rec.kind} {o.metric} {o.period}: {o.against_value:,.2f} vs "
                        f"{o.from_value:,.2f} — neither stored")
                ingested = []
            else:
                ingested = ingest_manifest(store, manifest, bronze=bronze, as_of=run_date)
                typer.echo(f"  filings: ingested {len(ingested)} annual report(s) as grade-A facts")
                # THE FILINGS CHECK EACH OTHER. Each report restates the prior year in its comparative
                # column, so consecutive filings assert the same figure twice from two independent
                # publications. Where they disagree by more than any restatement explains, neither read
                # is trusted and both go (ADR-0036) — the alternative is a misread row sitting in the
                # store at grade A, out-ranking the very screener figure that would have contradicted it.
                dropped = quarantine_extraction_errors(
                    store, ticker, ingested,
                    tuple(FILING_ROWS) + tuple(COMPOSED_ROWS),
                    load_thresholds()["reconciliation"],
                )
                for overlap in dropped:
                    typer.echo(
                        f"  ⚠ quarantined {overlap.metric} {overlap.period}: "
                        f"{overlap.against_filing} says {overlap.against_value:,.2f}, "
                        f"{overlap.from_filing} says {overlap.from_value:,.2f} — neither stored")
            usable = [
                entry for entry in sorted(manifest["filings"], key=lambda e: str(e["period"]))
                if date.fromisoformat(str(entry["published_at"])) <= run_date
            ]
            if usable:
                latest_filing = filing_from_manifest(usable[-1], bronze)
                typer.echo(f"  walking notes from {usable[-1]['file']} ({usable[-1]['period']})")

        # THE ROSTER DECIDES WHO RUNS (ADR-0033). Availability is derived from the documents manifest, so
        # a run cannot claim coverage the ingest does not support — and the agents it could not staff are
        # published as the firm's own gaps rather than dropped.
        # Availability is the UNION of both manifests. The annual reports live in the filings manifest and
        # the governance documents in the documents manifest; reading only one made a phase-2 run plan zero
        # agents because `financials` looked unsatisfied while ten annual reports sat in the store.
        satisfied: set[str] = set()
        if documents:
            import json as _json
            from pathlib import Path as _Path

            from firm.core.orchestrator.roster import available_inputs_from

            manifest_json = _json.loads(_Path(documents).read_text())
            satisfied |= set(available_inputs_from(manifest_json))
            # Register the quarterly shareholding as grade-A governance facts (ADR-0035), so
            # `ownership_flows_analyst` can CITE promoter holding and pledge instead of abstaining.
            from firm.core.ingest.governance import ingest_shareholding_manifest

            governance = ingest_shareholding_manifest(
                store, manifest_json, bronze=f"{bronze}/{ticker}", as_of=run_date)
            registered = [g for g in governance if g.fact_ids]
            if governance:
                typer.echo(f"  governance: {len(registered)} of {len(governance)} shareholding filings "
                           f"registered as facts")
            # And the concall transcripts (ADR-0039), so `transcript_analyst` can quote management's own
            # guided figures instead of scoring a drift it was never shown.
            from firm.core.ingest.transcripts import ingest_transcript_manifest

            calls = ingest_transcript_manifest(
                store, manifest_json, bronze=f"{bronze}/{ticker}", as_of=run_date)
            quoted = [c for c in calls if c.fact_ids]
            if calls:
                typer.echo(f"  guidance: {sum(len(c.fact_ids) for c in quoted)} guided figures from "
                           f"{len(quoted)} of {len(calls)} transcripts registered as facts")
        if latest_filing is not None:
            satisfied |= {"financials", "filing", "segments"}
        # `peers` is satisfied by another company's FACTS, not by a document in this company's manifest,
        # so it is resolved here rather than in `available_inputs_from`. And it counts only when the
        # comparison actually yields a row: naming a peer we hold no data on would otherwise let the
        # roster claim coverage that produces nothing citable — the ADR-0035 mistake in reverse.
        if peer:
            from firm.core.pipeline.peers import load_peer_comparisons

            probe = load_peer_comparisons(store, ticker, peer, run_date)
            usable = [c for c in probe if c.comparable]
            if usable:
                satisfied.add("peers")
            typer.echo(f"  peers: {len(usable)} of {len(probe)} comparable "
                       f"({', '.join(c.peer for c in usable) or 'none'})")
            for gap in (c for c in probe if not c.comparable):
                typer.echo(f"    {gap.peer}: {gap.incomparable[0] if gap.incomparable else 'no data'}")
        available: tuple[str, ...] = tuple(sorted(satisfied))
        roster_agents, coverage_gaps = plan_agents(phase=phase, available_inputs=available)
        if answers:
            prepared = read_answers(answers, agents=roster_agents)
        typer.echo(f"  roster: phase {phase} plans {len(roster_agents)} agent(s); "
                   f"{len(coverage_gaps)} could not be staffed")

        result = run_deep_dive(
            store, ticker, run_date, provider=llm, answers=prepared, filing=latest_filing,
            agents=roster_agents, coverage_gaps=coverage_gaps, peers=peer,
            company_name=company or ticker, model=model, reports_root=reports_root,
            write=not force,
            # A verified reading already covers the numeric rows; the walker re-registering them would
            # put unverified row-locator figures beside verified ones under the same grade (ADR-0055).
            # The latest filing's notes/CARO/section scanning still runs either way.
            walk_numeric_rows=not readings,
        )
    finally:
        store.close()

    typer.echo(f"{ticker} as-of {run_date} · run {result.run_id}")
    typer.echo(f"  models: {[m.value for m in result.models] or 'none matched (universal checks only)'}")
    typer.echo(f"  screen: {result.screen.verdict.value}"
               + (f" — flags: {', '.join(f.name for f in result.screen.flags)}"
                  if result.screen.flags else " — no flags"))
    checked = len(result.evaluation.expected)
    typer.echo(f"  checks: {checked} applicable, "
               f"{result.evaluation.unavailable_share:.0%} unavailable · "
               f"notes {result.notes.notes_total} enumerated, coverage {result.notes.coverage:.0%}, "
               f"substantive {result.notes.substantive_share:.0%}")
    typer.echo(f"  VERDICT: {result.report.verdict.value} — {result.decision.rationale}")

    for violation in result.graph_violations:
        typer.echo(f"  graph violation {violation.rule} @ {violation.node_id}: {violation.detail}")
    for violation in result.publication_violations:
        typer.echo(f"  publication gate {violation.rule} @ {violation.field}: {violation.detail}")

    # ADR-0065: the gates above still refuse what they always refused, but a refusal now degrades the
    # report instead of cancelling it. Say so loudly — an operator who reads "published" and cannot
    # tell a full report from a withheld-verdict one has been misled by omission.
    if result.degraded:
        typer.echo("  ⚠ DEGRADED — the gates refused the report as assembled; a lesser one was published:")
        for note in result.degradation:
            typer.echo(f"      · {note}")
    if result.residual_violations:
        typer.echo(f"  ⚠⚠ the written report STILL fails {', '.join(result.residual_violations)} — "
                   f"this is a firm-side bug, not a finding about the company")

    if force:
        # `--force` runs with write=False and persists the draft here instead, keeping its original
        # meaning: the report AS ASSEMBLED, agents' narration and all, gates not enforced. That draft is
        # the thing worth debugging — the ladder's degraded version is already reproducible from it.
        draft = result.assembled_report if result.assembled_report is not None else result.report
        md, _ = write_report(draft, reports_root, force=True)
        typer.echo(f"  ⚠ FORCED: as-assembled draft written, publication gates NOT enforced: {md}")
        return
    typer.echo(f"  published: {result.markdown_path}")


@app.command("read-packets")
def read_packets(
    ticker: str = typer.Option(..., "--ticker"),
    filings: str = typer.Option(..., "--filings",
                                help="filings manifest (data/manifests/{TICKER}-filings.json)"),
    as_of: str = typer.Option("", "--as-of", help="Law 3: no packet for a filing after this date"),
    bronze: str = typer.Option("data/bronze", "--bronze",
                               help="PDF cache; missing files are fetched from the manifest's "
                                    "source_url and refused unless they hash to its sha256"),
    readings: str = typer.Option("", "--readings",
                                 help="where answered readings live; default "
                                      "data/manifests/{TICKER}-readings"),
    out: str = typer.Option("", "--out", help="default runs/{TICKER}-reading-packets"),
) -> None:
    """Write one reading packet per manifest filing that has no answered reading yet (ADR-0046/0055).

    The packet is the complete proposer prompt — instructions, metric vocabulary, and the filing's
    numbered page text. Answer each as `{file stem}.reading.json` in the readings directory, then run
    `firm deep-dive --readings` (or re-run this command to see what is still unanswered).
    """
    from firm.core.ingest.filings import load_manifest
    from firm.core.ingest.reading import fetch_pdf, write_reading_packets

    manifest = load_manifest(filings)
    readings_dir = readings or f"data/manifests/{ticker}-readings"
    written = write_reading_packets(
        manifest, bronze=bronze, out_dir=out or f"runs/{ticker}-reading-packets",
        readings_dir=readings_dir,
        as_of=date.fromisoformat(as_of) if as_of else None, fetcher=fetch_pdf)
    if not written:
        typer.echo(f"nothing to do: every filing in {filings} already has a reading in {readings_dir}")
    for path in written:
        typer.echo(f"wrote {path}")


@app.command("packets")
def packets(
    ticker: str = typer.Option(..., "--ticker"),
    as_of: str = typer.Option("", "--as-of"),
    db: str = typer.Option("data/firm.db", "--db"),
    out: str = typer.Option("", "--out", help="default runs/{ticker}-{as_of}/packets"),
    phase: int = typer.Option(
        2, "--phase",
        help="build phase; selects the roster from config/roster.yaml (ADR-0030). Packets are written for "
             "every agent the roster plans, so a phase-3 run can actually be staffed."),
    documents: str = typer.Option("", "--documents", help="documents manifest, for roster availability"),
    peer: list[str] = typer.Option(
        [], "--peer",
        help="peer ticker(s) to compare against; repeatable. Must match the --peer set the run will use, "
             "or the packet an agent answers is not the packet the run validates it against."),
    filings: str = typer.Option(
        "", "--filings",
        help="filings manifest. Pass the SAME one `deep-dive` will get: without it the packet tells the "
             "agents no annual report was walked, while the run walks one."),
    bronze: str = typer.Option("data/bronze", "--bronze", help="where the manifest's PDFs live"),
    readings: str = typer.Option(
        "", "--readings",
        help="directory of verified reading answers (ADR-0055). Pass the SAME one `deep-dive` will "
             "get: the packet's numeric facts then come from the reading path and the walker only "
             "scans notes — the same rule that keeps the packet the run's evidence, not a variant."),
) -> None:
    """Write the planned agents' prompt packets (computed facts included) for the Claude-in-the-loop path.

    Answer each `{agent}.md` with a single JSON object, save it as `{agent}.json` beside it, then run
    `firm deep-dive --answers <dir>`. This is how agents run on a subscription with no API key (ADR-0010).

    THE PACKET MUST BE THE RUN'S EVIDENCE, NOT A SUBSET OF IT. Before `--filings` existed here, this
    command built its checklist with no filing at all: the packet handed to every agent said the notes
    were unenumerated, `promoter_lending` and `disclosure_gap` were UNAVAILABLE, and 0% of the notes had
    been read — while `deep-dive`, given the same ticker minutes later, walked the annual report and had
    all of it. The agents were reasoning about a poorer company than the one being published on, and
    nothing in the pipeline could notice, because both halves were individually correct.
    """
    from firm.core.compute import quality
    from firm.core.compute.models import build_playbook, detect_models
    from firm.core.config import (
        forensic_thresholds,
        load_thresholds,
        model_detection_thresholds,
        model_forensic_thresholds,
        model_playbooks,
        report_policy,
        universal_forensic_thresholds,
    )
    from firm.core.pipeline import derive as D
    from firm.core.pipeline.checks import evaluate_checks
    from firm.core.pipeline.deep_dive import (
        agent_facts_payload,
        plan_agents,
        statement_shape,
        write_packets,
    )
    from firm.core.report.assemble import NotesReview

    run_date = date.fromisoformat(as_of) if as_of else date.today()
    store = FactStore(db)
    from firm.core.pipeline.peers import load_peer_comparisons

    walk = None
    if filings:
        from firm.core.ingest.filings import filing_from_manifest, load_manifest
        from firm.core.pipeline.filing import walk_filing

        manifest = load_manifest(filings)
        if readings:
            # Same ingest `deep-dive --readings` performs (idempotent), so the packet's facts ARE the
            # run's facts — and the walker must not re-register unverified numeric rows beside them.
            from firm.core.config import load_thresholds as _load_thresholds
            from firm.core.ingest.filings import quarantine_store_contradictions
            from firm.core.ingest.reading import fetch_pdf, ingest_readings_manifest

            results = ingest_readings_manifest(
                store, manifest, readings_dir=readings, bronze=bronze, as_of=run_date,
                fetcher=fetch_pdf)
            typer.echo(f"  readings: {sum(1 for r in results if r.status == 'registered')} of "
                       f"{len(results)} filings registered")
            quarantine_store_contradictions(
                store, ticker, run_date, _load_thresholds()["reconciliation"])
        usable = [
            entry for entry in sorted(manifest["filings"], key=lambda e: str(e["period"]))
            if date.fromisoformat(str(entry["published_at"])) <= run_date
        ]
        if usable:
            walk = walk_filing(store, ticker, filing_from_manifest(usable[-1], bronze),
                               numeric_rows=not readings)
            typer.echo(f"  walked {usable[-1]['file']}: {len(walk.notes)} notes enumerated")
    facts = D.load_company_facts(store, ticker, run_date)
    guidance = store.query_metric_prefix(ticker, "guidance:", run_date)
    peer_comparisons = load_peer_comparisons(store, ticker, peer, run_date)
    store.close()
    derived = D.derive_metrics(facts)
    models = detect_models(statement_shape(facts, derived), model_detection_thresholds())
    playbook = build_playbook(models, model_playbooks())
    thresholds = load_thresholds()
    evaluation = evaluate_checks(
        playbook, derived, facts, forensic=thresholds["forensic"],
        universal=universal_forensic_thresholds(), model_specific=model_forensic_thresholds(),
        **({"external": walk.external} if walk is not None else {}),
    )
    screen = quality.forensic_screen(
        quality.SectorClass.NON_FINANCIAL, evaluation.metrics, forensic_thresholds(),
        checks_ran=evaluation.ran, checks_expected=len(evaluation.applicable),
                                    min_ran_share=float(thresholds["forensic"].get("screen_min_ran_share", 0)))

    from firm.core.pipeline.deep_dive import feasibility_at_target
    from firm.core.pipeline.filing import disposition_notes

    notes_review = NotesReview()
    if walk is not None:
        notes_review, _ = disposition_notes(
            walk.notes, evaluation, disclosure_gaps_found=walk.missing_disclosures,
            reconciliations=walk.reconciliations)
    payload = agent_facts_payload(
        derived, evaluation, screen, feasibility_at_target(derived, report_policy(), thresholds["multibagger"]),
        models, notes_review, guidance=guidance, peers=peer_comparisons)
    # Packets follow the ROSTER, not a fixed trio (ADR-0034): a phase-3 run that plans eight agents needs
    # eight packets, or it can never be staffed and the phase stalls at "wired, not staffed".
    satisfied: set[str] = {"financials", "filing", "segments"}
    if any(c.comparable for c in peer_comparisons):
        satisfied.add("peers")
    if documents:
        import json as _json
        from pathlib import Path as _Path

        from firm.core.orchestrator.roster import available_inputs_from

        satisfied |= set(available_inputs_from(_json.loads(_Path(documents).read_text())))
    roster_agents, _gaps = plan_agents(phase=phase, available_inputs=tuple(sorted(satisfied)))

    out_dir = out or f"runs/{ticker}-{run_date.isoformat()}/packets"
    written = write_packets(payload, out_dir, agents=roster_agents)
    for path in written:
        typer.echo(f"wrote {path}")
    typer.echo(f"answer each as {out_dir}/<agent>.json, then: "
               f"python -m firm deep-dive --ticker {ticker} --as-of {run_date} --answers {out_dir}")


@app.command("eval")
def eval_golden(
    cases: str = typer.Option("evals/golden_set", "--cases", help="directory of golden-set case files"),
    bronze: str = typer.Option("data/bronze", "--bronze"),
    case: list[str] = typer.Option([], "--case", help="run only these case ids; repeatable"),
) -> None:
    """Phase 6: replay the golden set and report EXTRACTION and JUDGMENT failures separately.

    Not part of `make test`, deliberately (docs/GOLDEN_SET.md §7): it needs the filings and takes minutes,
    and a slow default suite stops being run. Exits non-zero if any case REGRESSES — a case recorded as
    failing with an open question does not block, and a recorded failure that starts passing DOES,
    because a stale red case is how a calibration debt gets quietly forgotten.
    """
    from firm.core.eval.run import run_golden_set

    report = run_golden_set(cases, bronze=bronze, only=tuple(case))
    typer.echo(report.render())
    if report.regressions:
        raise typer.Exit(code=1)


@app.command("register")
def register(
    since: str = typer.Option(..., "--since", help="start date, YYYY-MM-DD"),
    until: str = typer.Option(..., "--until", help="end date, YYYY-MM-DD"),
    kind: list[str] = typer.Option(["auditor_resignation"], "--kind", help="repeatable"),
    out: str = typer.Option("evals/golden_set/_register.jsonl", "--out"),
) -> None:
    """Enumerate adverse governance events from BSE's announcement register (golden set, ADR-0057).

    A COMPLETE enumeration for the window, not a search and not a memory: the golden set's positives have
    to come from a register, or the selection quietly picks the famous cases everybody already knows.
    Writes one JSON object per company-event; the caller filters to the universe and records exclusions.
    """
    import json as _json
    import time
    from pathlib import Path as _Path

    from firm.adapters.india.register import adverse_events, deduplicate, fetch_url

    def polite(url: str) -> str:
        # Slow on purpose: measured live, the endpoint degrades SILENTLY under a sustained stream —
        # partial pages, no error — and a lossy register defeats its own point (ADR-0061).
        time.sleep(0.6)
        return fetch_url(url)

    events = deduplicate(adverse_events(
        date.fromisoformat(since), date.fromisoformat(until), kinds=tuple(kind), fetch=polite,
        passes=2))
    path = _Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(_json.dumps(e.as_dict()) for e in events) + "\n")
    typer.echo(f"{len(events)} distinct company-event(s) {since}..{until} -> {path}")


@app.command("triage")
def triage_cmd(
    register_file: str = typer.Option("evals/golden_set/_register.jsonl", "--register"),
    candidates_file: str = typer.Option("evals/golden_set/_candidates.jsonl", "--candidates"),
    excluded_file: str = typer.Option("evals/golden_set/_excluded.jsonl", "--excluded"),
    kind: list[str] = typer.Option([], "--kind", help="triage only these kinds (default: all)"),
) -> None:
    """Split register events into golden-set candidates and recorded exclusions by the universe band.

    Append-only and idempotent: an event whose (scrip, kind) already sits in either file is skipped, so
    re-running after a new enumeration triages only what is new. Only the mcap band is applied — for the
    golden set a company under CIRP is not an exclusion, it is the label (docs/GOLDEN_SET.md §3).
    """
    import json as _json
    import time
    from pathlib import Path as _Path

    from firm.adapters.india.register import AdverseEvent, fetch_url, market_cap_cr, triage
    from firm.core.config import load_yaml

    band = load_yaml("universe.yaml")["mcap_band_cr"]

    def seen(path: _Path) -> set[tuple[str, str]]:
        if not path.exists():
            return set()
        return {(r["scrip_code"], r["kind"]) for r in map(_json.loads, path.read_text().splitlines()) if r}

    cand_path, excl_path = _Path(candidates_file), _Path(excluded_file)
    already = seen(cand_path) | seen(excl_path)
    events = []
    for line in _Path(register_file).read_text().splitlines():
        row = _json.loads(line)
        if kind and row["kind"] not in kind:
            continue
        if (row["scrip_code"], row["kind"]) in already:
            continue
        events.append(AdverseEvent(kind=row["kind"], on=date.fromisoformat(row["date"]),
                                   scrip_code=row["scrip_code"], company=row["company"],
                                   headline=row["headline"], source=row["source"]))

    def polite_mcap(scrip: str) -> float | None:
        time.sleep(0.4)
        return market_cap_cr(scrip, fetch_url)

    candidates, excluded = triage(events, polite_mcap,
                                  floor_cr=float(band["min"]), ceiling_cr=float(band["max"]))
    with cand_path.open("a") as f:
        for row in candidates:
            f.write(_json.dumps(row) + "\n")
    with excl_path.open("a") as f:
        for row in excluded:
            f.write(_json.dumps(row) + "\n")
    typer.echo(f"triaged {len(events)} new event(s): {len(candidates)} candidate(s), "
               f"{len(excluded)} excluded -> {cand_path}, {excl_path}")


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
