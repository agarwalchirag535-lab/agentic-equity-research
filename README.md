# equity-firm

An **agentic equity research firm** — complete, auditable, standalone research reports on Indian listed
companies (ADR-0063). A report covers the full investment case — business quality, growth, financials,
earnings quality, valuation, management/governance, forensic red flags, risks, industry/peers — and
arrives at an evidence-backed verdict, positive or negative. One section keeps its teeth: *can this
business plausibly compound into a 5–10x over 5–8 years, self-funded, under honest management?* — an
important component of every report, not the sole purpose of the system. Discovery sweeps target
micro/small/mid-caps (₹300cr–₹30,000cr); a deep dive runs on **any company the owner names**. It
produces research artifacts only: **no orders, no broker, never "buy this."**

**👉 New here (new session, new agent, new platform)? Read [`docs/STATUS.md`](docs/STATUS.md) first** —
what is built, what is not, standing owner directives, and hard-won gotchas.

Full constitution: [`docs/SPEC.md`](docs/SPEC.md). Build plan + corrections: [`docs/PLAN.md`](docs/PLAN.md).
Decisions: [`docs/DECISIONS.md`](docs/DECISIONS.md). Short rules: [`CLAUDE.md`](CLAUDE.md).

## Status
Phases 0–5 complete; Phase 6 (the golden set) is live and awaiting human sign-off.
**995 tests; 100% coverage on the compute layer.**
The firm now publishes: `python -m firm deep-dive --ticker X --as-of D` runs the deterministic layer,
lets three agents narrate it, checks their claims against the evidence-graph invariants, and writes
`reports/{TICKER}/{run_id}/report.md` + `.json` only if the three publication gates pass. Full detail:
[`docs/STATUS.md`](docs/STATUS.md).
- **Compute (Phase 1, done):** multibagger + §6 feasibility gate, forensic quality (Beneish,
  cash-reality, lender checks), ratios, DuPont, ROIC + incremental ROIC, DCF, reverse DCF, scenarios,
  sensitivity.
- **Infra (Phase 0, done):** schema contracts, config, the **point-in-time fact store** (Laws 2 & 3),
  the **emerging-company router** (ADR-0008 — short-history businesses routed, never dropped).
- **Phase 2 (done, ADR-0021):** `financial_statement_analyst`, `forensic_accountant` and
  `business_analyst` are wired onto the evidence graph and the dual-verdict report. Derived numbers carry
  their formula, their input facts and the *worst* grade they rest on; every playbook check is recorded as
  PASS / FLAG / UNAVAILABLE(reason) / NOT_APPLICABLE(reason) so a check that never ran can never read as a
  pass; the verdict and the dated kill/rehabilitation criteria are computed, not written. An agent that
  authors a number, cites a fact that does not exist, or tries to narrate past a deterministic HARD_FAIL
  fails the run.
- **Harness (Phase 0–3 scaffolding, done):** LLM provider abstraction + disk cache (Laws 5/6), the four
  blocking validators (citation, arithmetic, consistency, hedge), the orchestrator (stages/gates/DAG/
  budget), the memory loop (predictions/Brier/resolver), **all 14 agent output schemas**, **all 14 agent
  prompt files**, and the **agent runner**.
- **Live data ingestion (done, ADR-0009/0018):** `adapters/india/screener.py` pulls 10-yr financials from
  screener.in (grade-B cross-check); BSE archives are the point-in-time spine, with OCR fallback and a
  notes-walker that enumerates and dispositions every note.
- **Agents run with NO API key (ADR-0010):** `python -m firm packets --ticker X` writes each agent's
  prompt packet with the computed facts; answer them, then
  `python -m firm deep-dive --ticker X --answers <dir>`. First artifact through the new pipeline:
  `reports/ALKYLAMINE/2026-07-23-433c94208117/` — verdict `INSUFFICIENT_DISCLOSURE`, because four of seven
  checks had no inputs in a screener-only run and a thesis would have been the dishonest answer.
- **Remaining:** human sign-off on the golden set (8 cases, 7 in band, positives 2/2); SPEC §7.5's
  calibration dashboard; the last of the old-charter narrowness in code (ADR-0063 flags #1–#4 — chiefly
  `thesis_synthesizer`'s mandate, still written as the multibagger decomposition alone); dated
  reference-rate rows (ADR-0078); and `make lint`'s ~180 ruff version-drift findings.

Commands: `gate-demo` · `facts-demo` · `ingest --ticker X` · `ingest-prices --ticker X --scrip N` ·
`forensic --ticker X` · `analyze --ticker X` · `discover-filings --ticker X --url U` ·
`packets --ticker X` · `read-packets --ticker X` · `deep-dive --ticker X` · `questions --ticker X` ·
`resolve --ticker X --as-of D` · `evolve` · `eval` · `register` · `triage` · `run`

## Quickstart
```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"

make cov          # runs the suite; FAILS if core/compute isn't 100% covered
python -m firm gate-demo   # §6.3 feasibility gate on two synthetic companies (no data, no LLM)
```

## Layout (corrected from SPEC §3 — see PLAN §2)
```
config/    thresholds/models/universe/sectors — every magic number lives here
agents/    markdown prompts (Law 6); _shared/ holds the house standards
src/firm/  the package (python -m firm)
  core/compute/    Law 1 pure-Python math (multibagger, forensic quality) — 100% tested
  core/{facts,orchestrator,validators,screen,monitoring,evolution,llm,eval,ingest,graph,pipeline,report,agents}/
  adapters/{base,india}/   market-agnostic core; India logic isolated
  schemas/   Pydantic output contracts (Law 4); _base.py holds shared provenance types
tests/     mirrors core/compute
data/      bronze -> silver -> gold medallion layers + firm.db
memory/    predictions, lessons, calibration, per-company notes (the §7 loop)
evals/     golden_set + rubrics (the only honest measure — SPEC §9)
```

## The seven laws (see CLAUDE.md)
Deterministic compute / LLM narration split · provenance or it doesn't exist · point-in-time discipline ·
structured output contracts · idempotent+resumable+cached · portability · agents never see raw HTML.
