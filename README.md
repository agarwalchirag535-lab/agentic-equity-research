# equity-firm

An **agentic equity research firm** — auditable multibagger discovery for Indian micro/small/mid-caps
(₹300cr–₹30,000cr). It answers one question with an evidence chain: *can this business plausibly compound
into a 5–10x over 5–8 years, self-funded, under honest management?* — and **rejects** everything that
can't prove it. It produces research artifacts only: **no orders, no broker, never "buy this."**

Full constitution: [`docs/SPEC.md`](docs/SPEC.md). Build plan + corrections: [`docs/PLAN.md`](docs/PLAN.md).
Decisions: [`docs/DECISIONS.md`](docs/DECISIONS.md). Short rules: [`CLAUDE.md`](CLAUDE.md).

## Status
**Everything buildable offline is built** — 105 tests; 100% coverage on the compute layer.
- **Compute (Phase 1, done):** multibagger + §6 feasibility gate, forensic quality (Beneish,
  cash-reality, lender checks), ratios, DuPont, ROIC + incremental ROIC, DCF, reverse DCF, scenarios,
  sensitivity.
- **Infra (Phase 0, done):** schema contracts, config, the **point-in-time fact store** (Laws 2 & 3),
  the **emerging-company router** (ADR-0008 — short-history businesses routed, never dropped).
- **Harness (Phases 2–3 scaffolding, done):** LLM provider abstraction + disk cache (Laws 5/6), the four
  blocking validators (citation, arithmetic, consistency, hedge), the orchestrator (stages/gates/DAG/
  budget), the memory loop (predictions/Brier/resolver), **all 14 agent output schemas**, **all 14 agent
  prompt files**, and the **agent runner** (loads a prompt, calls the provider, validates the output with
  retry — runnable end-to-end offline with the stub provider).
- **Live data ingestion (done, ADR-0009):** `adapters/india/screener.py` pulls 10-yr financials +
  shareholding from screener.in (verified end-to-end — 336 real facts for RELIANCE into the fact store).
  `python -m firm ingest --ticker RELIANCE` then `python -m firm forensic --ticker RELIANCE` runs the
  cash-reality forensic screen on real data.
- **Agents run with NO API key (ADR-0010):** on a Claude Code subscription. `ClaudeCodeAdapter` shells
  to `claude -p`; or Claude-in-the-loop answers a computed prompt packet (`core/agents/packet.py`) and
  the output is schema-validated. First real artifact: `reports/RELIANCE.md` / `.json` — financial +
  forensic + thesis outputs grounded in live FY26 data, each validated (Law 4).
- **Remaining:** wire the 14 agents onto the gate pipeline for arbitrary tickers; add concall/AR
  ingestion and quarterly data; build the golden-set eval (Phase 6). A broker API key (in `.env`) is
  optional, for live prices/liquidity.

Demos: `python -m firm gate-demo` · `python -m firm facts-demo` · `python -m firm ingest --ticker X` ·
`python -m firm forensic --ticker X`. 112 tests; compute 100%.

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
  core/{facts,orchestrator,validators,screen,monitoring,evolution,llm}/  (to build)
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
