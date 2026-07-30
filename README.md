# equity-firm

An **agentic equity research firm** — auditable multibagger discovery for Indian micro/small/mid-caps
(₹300cr–₹30,000cr). It answers one question with an evidence chain: *can this business plausibly compound
into a 5–10x over 5–8 years, self-funded, under honest management?* — and **rejects** everything that
can't prove it. It produces research artifacts only: **no orders, no broker, never "buy this."**

**👉 New here (new session, new agent, new platform)? Read [`docs/STATUS.md`](docs/STATUS.md) first** —
what is built, what is not, standing owner directives, and hard-won gotchas.

Full constitution: [`docs/SPEC.md`](docs/SPEC.md). Build plan + corrections: [`docs/PLAN.md`](docs/PLAN.md).
Decisions: [`docs/DECISIONS.md`](docs/DECISIONS.md). Short rules: [`CLAUDE.md`](CLAUDE.md).

## Status
Phases 0–2 complete. **368 tests; 100% coverage on the compute layer.**
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
- **Remaining:** get the cash / receivables / inventory rows out of the audited AR so real companies can
  reach a substantive verdict; wire the other 11 agents (Phase 3); log the dated criteria as predictions
  (Phase 5); build the golden-set eval (Phase 6).

Demos: `python -m firm gate-demo` · `python -m firm facts-demo` · `python -m firm ingest --ticker X` ·
`python -m firm forensic --ticker X` · `python -m firm analyze --ticker X` ·
`python -m firm packets --ticker X` · `python -m firm deep-dive --ticker X`

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
