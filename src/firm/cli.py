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

    found = discover_filings(html, ticker, base_url=url)
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


@app.command("discover-documents")
def discover_documents_cmd(
    ticker: str = typer.Option(..., "--ticker", help="NSE/BSE symbol, e.g. CUB"),
    url: list[str] = typer.Option(..., "--url", help="an IR page; repeat for several sections"),
    out: str = typer.Option("", "--out", help="default data/manifests/{TICKER}-documents.json"),
) -> None:
    """Find the governance documents on a company's IR pages and write a documents manifest.

    THE GAP THIS CLOSES. `discover_documents()` existed in `adapters/india/ir_pages.py` and no command
    called it — the one documents manifest in the repo had been assembled by hand in an earlier session.
    So the pipeline "worked" on one company because a human built its manifest once, and there was no path
    at all for a second company. That is the definition of an overfit: the demo generalises and the
    product does not.

    Shareholding patterns, concall transcripts, voting results and credit ratings are what staff
    `management_analyst`, `transcript_analyst` and `ownership_flows_analyst`. Downloads nothing —
    retrieval is `fetch-filings`, deliberately separate (ADR-0026).
    """
    import json
    import ssl
    import urllib.request
    from collections import Counter
    from pathlib import Path

    from firm.adapters.india.ir_pages import discover_documents

    try:
        import certifi

        context = ssl.create_default_context(cafile=certifi.where())
    except ImportError:  # pragma: no cover
        context = ssl.create_default_context()

    found: dict[str, object] = {}
    for page in url:
        request = urllib.request.Request(page, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(request, timeout=60, context=context) as response:  # noqa: S310
                html = response.read().decode("utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001 - an unreachable section is reported, not fatal
            typer.echo(f"  FAIL {page}: {exc}")
            continue
        for doc in discover_documents(html, ticker, base_url=page):
            found.setdefault(doc.url, doc)
        typer.echo(f"  read {page} -> {len(found)} documents so far")

    if not found:
        typer.echo("no recognised documents found")
        raise typer.Exit(1)

    documents = sorted(found.values(), key=lambda d: (d.doc_class, d.period or "", d.url))  # type: ignore[union-attr]
    manifest = {
        "ticker": ticker,
        "source": list(url),
        "retrieved_at": date.today().isoformat(),
        "documents": [
            {"file": d.suggested_file, "doc_class": d.doc_class, "period": d.period,  # type: ignore[union-attr]
             "source_url": d.url, "sha256": "", "bytes": 0}  # type: ignore[union-attr]
            for d in documents
        ],
    }
    path = Path(out or f"data/manifests/{ticker}-documents.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2) + "\n")

    counts = Counter(d.doc_class for d in documents)  # type: ignore[union-attr]
    typer.echo(f"{len(documents)} document(s) -> {path}")
    for name, n in counts.most_common():
        typer.echo(f"  {n:4d}  {name}")
    typer.echo(f"\nNext: firm fetch-filings --manifest {path} --bronze data/bronze/{ticker}")


@app.command("fetch-filings")
def fetch_filings_cmd(
    manifest: str = typer.Option(..., "--manifest", help="a filings or documents manifest"),
    bronze: str = typer.Option("data/bronze", "--bronze", help="where to write the PDFs"),
    only: str = typer.Option("", "--only", help="comma-separated periods to fetch, e.g. FY23,FY24,FY25"),
    limit: int = typer.Option(0, "--limit", help="stop after N files (0 = all)"),
) -> None:
    """Download the PDFs a manifest names, into the immutable bronze store, and record their hashes.

    Discovery and retrieval are separate steps on purpose (ADR-0026): pulling tens of megabytes off a
    company's servers is a decision a human makes per company. This is that step made repeatable, which
    is what a PEER set needs — the whole point of a peer comparison is that the peer's figures come from
    the peer's own audited filings, computed by the same code, and that is only true if we actually
    fetched them.

    Bronze is content-addressed and immutable (Law 7): a file already present with the right size is not
    re-fetched, so an interrupted run resumes rather than restarts.
    """
    import hashlib
    import json
    import ssl
    import urllib.request
    from pathlib import Path

    try:
        import certifi

        context = ssl.create_default_context(cafile=certifi.where())
    except ImportError:  # pragma: no cover
        context = ssl.create_default_context()

    path = Path(manifest)
    data = json.loads(path.read_text())
    entries = data.get("filings") or data.get("documents") or []
    wanted = {p.strip().upper() for p in only.split(",") if p.strip()}
    if wanted:
        entries = [e for e in entries if str(e.get("period", "")).upper() in wanted]
    if limit:
        entries = entries[:limit]

    out_dir = Path(bronze)
    out_dir.mkdir(parents=True, exist_ok=True)
    fetched = skipped = failed = 0
    for entry in entries:
        target = out_dir / str(entry["file"])
        if target.exists() and target.stat().st_size > 0:
            typer.echo(f"  have  {target.name} ({target.stat().st_size:,} bytes)")
            skipped += 1
            continue
        request = urllib.request.Request(
            str(entry["source_url"]), headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(request, timeout=120, context=context) as response:  # noqa: S310
                payload = response.read()
        except Exception as exc:  # noqa: BLE001 - a failed fetch is reported, never fatal
            typer.echo(f"  FAIL  {entry['file']}: {exc}")
            failed += 1
            continue
        target.write_bytes(payload)
        entry["sha256"] = hashlib.sha256(payload).hexdigest()
        entry["bytes"] = len(payload)
        typer.echo(f"  got   {target.name} ({len(payload):,} bytes)")
        fetched += 1

    path.write_text(json.dumps(data, indent=2) + "\n")
    typer.echo(f"{fetched} fetched, {skipped} already present, {failed} failed -> {out_dir}")
    if failed:
        raise typer.Exit(1)


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
    phase: int = typer.Option(
        2, "--phase",
        help="build phase (SPEC §11). Selects the agent roster from config/roster.yaml; agents above this "
             "phase are refused, so the build order is enforced rather than remembered (ADR-0030)."),
    documents: str = typer.Option(
        "", "--documents",
        help="path to a documents manifest (data/manifests/{TICKER}-documents.json). Determines which "
             "roster prerequisites are satisfied, so agent coverage is derived from what is actually "
             "ingested rather than asserted (ADR-0031)."),
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
            from firm.core.ingest.filings import (
                filing_from_manifest,
                ingest_manifest,
                load_manifest,
            )

            manifest = load_manifest(filings)
            ingested = ingest_manifest(store, manifest, bronze=bronze, as_of=run_date)
            typer.echo(f"  filings: ingested {len(ingested)} annual report(s) as grade-A facts")
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
        ingested_documents = None
        if documents:
            from firm.core.ingest.documents import ingest_documents, load_documents_manifest
            from firm.core.orchestrator.roster import available_inputs_from

            manifest = load_documents_manifest(documents)
            satisfied |= set(available_inputs_from(manifest))
            # ACTUALLY READ THEM (ADR-0038). Until now the manifest only decided which agents were
            # *planned*: availability was derived from the file list and the documents themselves were
            # never opened, so `management_analyst` and `ownership_flows_analyst` were staffed on the
            # strength of PDFs nobody had parsed. Reading them here is what turns a staffed agent into a
            # working one.
            ingested_documents = ingest_documents(
                store, manifest, bronze=f"{bronze}/{ticker}", as_of=run_date)
            typer.echo(
                f"  documents: {len(ingested_documents.shareholding_series)} shareholding quarters as "
                f"grade-A facts, {len(ingested_documents.usable_transcripts)} concalls read"
                + (f", {len(ingested_documents.refusals)} unreadable"
                   if ingested_documents.refusals else "")
            )
        if latest_filing is not None:
            satisfied |= {"financials", "filing", "segments"}

        # PEERS (ADR-0039). Built from facts already in the store, which for a peer means that peer's own
        # annual reports were discovered, fetched and walked by the identical pipeline. `sector_analyst`
        # is only staffed when a peer actually came out the other end — a declared peer whose filings were
        # never ingested leaves the agent skipped WITH THE REASON, rather than running it on nothing.
        from firm.core.pipeline.peers import build_peer_set

        peer_set = build_peer_set(store, ticker, run_date)
        if peer_set.companies:
            satisfied.add("peers")
            typer.echo(f"  peers: {len(peer_set.companies)} comparable from primary sources "
                       f"({', '.join(p.ticker for p in peer_set.companies)})")
        for missing_ticker, reason in peer_set.missing:
            typer.echo(f"  peer {missing_ticker} unavailable: {reason}")

        available: tuple[str, ...] = tuple(sorted(satisfied))
        roster_agents, coverage_gaps = plan_agents(phase=phase, available_inputs=available)
        if answers:
            prepared = read_answers(answers, agents=roster_agents)
        typer.echo(f"  roster: phase {phase} plans {len(roster_agents)} agent(s); "
                   f"{len(coverage_gaps)} could not be staffed")

        result = run_deep_dive(
            store, ticker, run_date, provider=llm, answers=prepared, filing=latest_filing,
            agents=roster_agents, coverage_gaps=coverage_gaps, documents=ingested_documents,
            peers=peer_set if peer_set.companies else None,
            company_name=company or ticker, model=model, reports_root=reports_root,
            write=not force,
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

    if result.published:
        typer.echo(f"  published: {result.markdown_path}")
        return
    if force:
        md, _ = write_report(result.report, reports_root, force=True)
        typer.echo(f"  ⚠ FORCED draft written (failed gates): {md}")
        return
    typer.echo("  NOT PUBLISHED — fix the violations above (a report that fails a gate never ships)")
    raise typer.Exit(1)


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
    documents: str = typer.Option(
        "", "--documents",
        help="documents manifest. Its shareholding patterns and concall transcripts are PARSED and "
             "distributed to the agents whose mandates need them (ADR-0038), not merely counted."),
    bronze: str = typer.Option("data/bronze", "--bronze", help="where the manifest's PDFs live"),
) -> None:
    """Write the planned agents' prompt packets (computed facts included) for the Claude-in-the-loop path.

    Answer each `{agent}.md` with a single JSON object, save it as `{agent}.json` beside it, then run
    `firm deep-dive --answers <dir>`. This is how agents run on a subscription with no API key (ADR-0010).
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
    ingested_documents = None
    if documents:
        from firm.core.ingest.documents import ingest_documents, load_documents_manifest

        ingested_documents = ingest_documents(
            store, load_documents_manifest(documents), bronze=f"{bronze}/{ticker}", as_of=run_date)
        typer.echo(
            f"  documents: {len(ingested_documents.shareholding_series)} shareholding quarters, "
            f"{len(ingested_documents.usable_transcripts)} concalls read")
    facts = D.load_company_facts(store, ticker, run_date)
    store.close()
    derived = D.derive_metrics(facts)
    models = detect_models(statement_shape(facts, derived), model_detection_thresholds())
    playbook = build_playbook(models, model_playbooks())
    thresholds = load_thresholds()
    evaluation = evaluate_checks(
        playbook, derived, facts, forensic=thresholds["forensic"],
        universal=universal_forensic_thresholds(), model_specific=model_forensic_thresholds(),
    )
    screen = quality.forensic_screen(
        quality.SectorClass.NON_FINANCIAL, evaluation.metrics, forensic_thresholds())

    from firm.core.pipeline.deep_dive import feasibility_at_target

    payload = agent_facts_payload(
        derived, evaluation, screen, feasibility_at_target(derived, report_policy(), thresholds["multibagger"]),
        models, NotesReview())
    # Packets follow the ROSTER, not a fixed trio (ADR-0034): a phase-3 run that plans eight agents needs
    # eight packets, or it can never be staffed and the phase stalls at "wired, not staffed".
    satisfied: set[str] = {"financials", "filing", "segments"}
    if documents:
        import json as _json
        from pathlib import Path as _Path

        from firm.core.orchestrator.roster import available_inputs_from

        satisfied |= set(available_inputs_from(_json.loads(_Path(documents).read_text())))

    from firm.core.pipeline.peers import build_peer_set

    peer_store = FactStore(db)
    peer_set = build_peer_set(peer_store, ticker, run_date)
    peer_store.close()
    if peer_set.companies:
        satisfied.add("peers")
        typer.echo(f"  peers: {len(peer_set.companies)} comparable from primary sources "
                   f"({', '.join(p.ticker for p in peer_set.companies)})")
    roster_agents, _gaps = plan_agents(phase=phase, available_inputs=tuple(sorted(satisfied)))

    # THE PACKET IS WHERE THE EVIDENCE HAS TO ARRIVE. On the Claude-in-the-loop path (ADR-0010) the
    # packet file IS the agent's whole world, so a brief that only reached `run_deep_dive` would leave
    # exactly the agents this work is about answering from nothing.
    from firm.core.pipeline.briefs import EvidenceBundle, build_briefs
    from firm.core.pipeline.deep_dive import agent_requirements

    bundle = EvidenceBundle(
        ticker=ticker, as_of=run_date, derived=derived, evaluation=evaluation, screen=screen,
        feasibility=feasibility_at_target(derived, report_policy(), thresholds["multibagger"]),
        models=models, notes=NotesReview(), documents=ingested_documents,
        peers=peer_set if peer_set.companies else None,
    )
    briefs = build_briefs(agent_requirements(roster_agents), bundle)

    out_dir = out or f"runs/{ticker}-{run_date.isoformat()}/packets"
    written = write_packets(payload, out_dir, agents=roster_agents, briefs=briefs)
    for path in written:
        typer.echo(f"wrote {path}")
    typer.echo(f"answer each as {out_dir}/<agent>.json, then: "
               f"python -m firm deep-dive --ticker {ticker} --as-of {run_date} --answers {out_dir}")


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
