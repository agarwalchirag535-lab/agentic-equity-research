# PLAN.md — Restatement, Corrections, Assumptions, Open Questions

> Companion to [`SPEC.md`](SPEC.md). SPEC is the constitution; this is the build plan and the record
> of where I disagree with the spec and changed it. Every change here has a matching ADR in
> [`DECISIONS.md`](DECISIONS.md).

## 1. Architecture in my own words

A staged, gated pipeline turns ~3,000 Indian listed companies into 3–5 defensible investment theses.
Cheap deterministic filters run first; expensive LLM agents only ever see survivors. Three ideas make
it honest rather than just impressive:

1. **Math is code, narration is LLM.** Every ratio, DCF, and gate decision is pure Python with unit
   tests (`core/compute/`). LLMs never emit numbers — they explain numbers handed to them. This is the
   single most important design choice; it's what stops the system hallucinating a plausible balance
   sheet.
2. **Point-in-time truth.** Every document has a `published_at`; every run has an `as_of`. The fact
   store filters `published_at <= as_of` at the query layer. This is the only thing that makes the
   historical eval (Phase 6) an honest test rather than hindsight theatre.
3. **A feasibility gate with teeth** (§6). Before any deep work, `g_required / ROIC` decides whether a
   company can even *self-fund* the growth its target return demands. Most retail multibagger theses
   die here, correctly.

The output is never "buy." It is: *"this returns Nx if and only if A, B, C happen; here is the evidence
and probability for each; here is what would prove me wrong (dated kill criteria)."*

## 2. Corrections I made to the spec (structure)

The spec's layout was ~90% right. I fixed six concrete defects before scaffolding (ADRs 0001, 0004):

| # | Defect in SPEC §3 | Fix |
|---|---|---|
| 1 | Law 6 mandates `python -m firm run` but no `firm/` package exists in the tree | All Python now under `src/firm/`; `python -m firm` and the `firm` console script both resolve |
| 2 | No `tests/` dir, yet Phase 1 demands 100% compute coverage | Added `tests/` mirroring the tree; `make cov` enforces the gate |
| 3 | Stage 9 monitoring, weekly post-mortem, prediction resolution, prompt-evolution had no home | Added `core/monitoring/` and `core/evolution/` |
| 4 | `screener` is code (§5) but was grouped with LLM agents with no dir | Added `core/screen/`; it is NOT an `agents/*.md` file |
| 5 | "Market-agnostic core" had only `adapters/india/`, no interface | Added `adapters/base/` — India implements a declared contract |
| 6 | No dependency/tooling manifest despite a portability law | Added `pyproject.toml`, `Makefile`, `.env.example`, `.gitignore` |

Also: `schemas/_base.py` holds the shared `Citation` / `Confidence` / `Provenance` / `OpenQuestion`
types so Laws 2 & 4 aren't copy-pasted into 14 schema files; `data/gold/rejected/` is now explicit.

## 3. Corrections I made to the spec (substance)

These are the parts of the spec I think are wrong or weak. The spec explicitly asked me to say so.

- **ADR-0002 — Forensic models must branch by sector.** Beneish M-score, Piotroski F, and
  conventional accruals are *invalid* for banks/NBFCs/insurers (no gross margin, no inventory,
  different accrual structure). The spec fires them at the whole universe. `quality.py` now suppresses
  the inapplicable models for financials and substitutes lender-appropriate checks (GNPA/NNPA drift,
  restructured book, provision coverage, slippage). Empirically the M-score threshold (−1.78) does
  carry signal on non-financial NSE500 names, but on banks it is misleading.
- **ADR-0003 — Benford's Law is demoted, not load-bearing.** Benford needs large transaction-level
  datasets. A company's reported *summary* financials have ~50–200 mostly-derived numbers; running
  Benford on them is close to numerology and manufactures false positives. It stays as an optional
  grade-F flag that can never, alone, trigger a forensic veto.
- **ADR-0005 — Gate B is deterministic.** The "forensic quick-kill" on ~400 companies must NOT call an
  LLM — Sloan accruals, CFO/PAT, Beneish, debtor-day divergence are pure math. The *LLM*
  `forensic_accountant` (related-party maze, auditor history, narrative) runs later on ~150 survivors.
  This cuts Gate-B cost by an order of magnitude.
- **ADR-0006 — New "cash-reality" forensic checks** (the user's core concern: *"the cash isn't
  there / the cash flow tells a different story than the P&L"*). Added to `quality.py`:
  cash-vs-interest-income consistency; simultaneous high-cash + high-cost-debt; multi-year cumulative
  CFO vs cumulative PAT; perpetual/ageing CWIP. See §5 of this plan.
- **ADR-0007 — Institution *quality* weighting.** `ownership_flows_analyst` will weight an institutional
  entry by that fund's historical small-cap track record and its position size relative to its own
  fund — "smart money entered" must be a scored signal, not binary.

## 4. The multibagger math is correct (verified)

I re-derived §6.2: for a 10x over 7 years, `10^(1/7) − 1 = 38.9%` earnings CAGR with no re-rating;
`(10/1.5)^(1/7) − 1 = 31.1%` at 1.5×; `25.8%` at 2.0×; `18.8%` at 3.0×. All correct. The feasibility
identity `g_sustainable = ROIC × reinvestment_rate` and `required_reinvestment = g / ROIC` are the
standard NOPAT-based sustainable-growth formulation and are implemented verbatim in
`core/compute/multibagger.py` with tests.

## 5. New forensic checks (implemented in `core/compute/quality.py`)

| Check | Red-flag logic | Signals |
|---|---|---|
| Cash-vs-interest-income | implied yield on avg cash `<< ` risk-free (e.g. `< 40%` of it) | cash is fictitious / encumbered / with related parties |
| Cash-and-debt paradox | large gross cash held *while* paying high-cost debt | the cash can't be used, or doesn't exist |
| Cumulative CFO/PAT | Σ CFO over N yrs `/` Σ PAT `< 0.7` | reported earnings never converted to cash — P&L ≠ cash reality |
| Ageing CWIP | capital-WIP `> X%` of assets and not commissioning to PP&E over 2–3 yrs | capex siphoning via perpetual CWIP |
| Sloan accruals | `(ΔWC − D&A)/avg assets` high | earnings quality low, mean-reversion risk |
| Beneish M (non-fin only) | `> −1.78` | earnings-manipulation probability elevated |

The `forensic_accountant` agent retains an **absolute veto** — but the veto rests on these deterministic
computations, never on LLM prose.

## 6. Assumptions
1. Consolidated financials are the default; standalone only when consolidated is absent (flagged).
2. 10 yrs financials / 12 quarters concalls / 8 quarters shareholding is the target history; below 5 yrs
   → `INSUFFICIENT_HISTORY`, separate lighter pipeline.
3. Cost model: cheap model for extraction/classification, strongest model for synthesis/red-team/valuation.
4. A plain DAG runner in Phase 3; LangGraph only if we outgrow it.
5. The compute layer has zero network/LLM dependencies and is fully testable offline.

## 7. Open questions (need human decision before Phase 2)
1. ~~**Data source of record for point-in-time history.**~~ **ANSWERED (owner, 2026-07-30 → ADR-0018):
   BSE/NSE archives + official filings, free tier. `published_at` = exchange dissemination timestamp;
   implemented behind `FilingsSource` in `adapters/india/exchange.py`; screener stays a grade-B
   cross-check.
2. **Golden-set sourcing.** Where do the 30 point-in-time-frozen 2015–2021 cases come from without
   look-ahead contamination in the underlying data?
3. **Risk-free / cost-of-debt reference series** for the cash-reality checks — one fixed number in
   `thresholds.yaml`, or a dated series?
4. **Budget ceiling per run** and per-stage token budgets — concrete USD numbers for `config/models.yaml`.
5. **Which LLM provider is primary** for Phase 2 (affects `config/models.yaml`, not the code).

## 8. Phase 0 acceptance test (concrete)
- **Company:** a single well-covered, clean-history name for the ingestion smoke test — proposed:
  **a mid-cap with a full 10-yr filing history and 12 public concalls** (final pick pending OQ#1's data
  source). 
- **Test:** ingest its last 5 annual reports + 8 concalls into bronze → silver → gold; query
  `"revenue FY24 as-of 2024-08-01"` and get the right number **with a citation**; the same query
  `as-of 2024-04-01` correctly returns **nothing** (point-in-time proof).
- **Already runnable today (compute layer, no data):** `make cov` → 100% coverage on `core/compute`;
  `python -m firm gate-demo` → the §6.3 feasibility gate correctly **rejects** a synthetic company with
  ROIC 15% requiring 30% growth, and **passes** a ROIC-40% self-funder.

## 9. Biggest risk, stated plainly
The agents are the fun part and the easy part. **Point-in-time data acquisition (Phase 0) and the honest
golden-set eval (Phase 6) are 3–5× harder than Phases 2–4 and are where this project will actually
succeed or fail.** The plan front-loads the compute core (done-able now, offline) precisely so momentum
doesn't hide the fact that the data layer is the real work.

## 10. Build order
Phase 0 (skeleton + contracts + compute core) → 1 (finish compute + tests) → 2 (three agents) →
3 (full roster + orchestrator) → 4 (judgment tier) → 5 (memory loop) → 6 (evaluation). No phase skip.
