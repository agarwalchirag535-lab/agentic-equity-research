# STATUS.md — project state, handoff, and what to do next

> **Read this first if you are new to this repo** (new session, new agent, new platform, or the owner
> after a break). It is the single authoritative answer to *"what is built, what is not, and what
> should happen next."* Last updated **2026-07-30**.
>
> Reading order for a cold start: this file → [`CLAUDE.md`](../CLAUDE.md) (the laws) →
> [`SPEC.md`](SPEC.md) (the constitution) → [`DECISIONS.md`](DECISIONS.md) (why things are the way they
> are, ADR-0001…0020). Keep this file updated as work lands — a stale STATUS is worse than none.

---

## 0. The one question

> *Can this business plausibly compound into a 5–10x over 5–8 years, self-funded, under honest
> management?*

Everything serves that. Output is **research artifacts only** — never an order, never "buy this".

## 1. Where the project stands

| Phase (SPEC §11) | State |
|---|---|
| 0 — skeleton + contracts | ✅ complete |
| 1 — compute layer | ✅ complete (100% coverage enforced by `make cov`) |
| **2 — three agents, deep** | ❌ **not started — needs the owner's explicit go** |
| 3 — full roster + orchestrator | ⚠️ DAG/gates/budget code exists; agents not wired to the graph or the report |
| 4 — judgment tier | ⚠️ agent prompts exist as markdown; no validated outputs flowing |
| 5 — memory loop | ⚠️ half-built (see §3) |
| 6 — evaluation / golden set | ❌ not started (see §3 — this is the biggest risk) |

**Tests:** 271 passing · `core/compute` at **100%** (the Phase-1 gate) · every module built in the
forensic/data work is also at 100% except deliberate network wrappers.

```bash
python -m pytest --cov --cov-fail-under=100
```

**Git:** branch `feat/forensic-primary-source-layer` — `75ffbfa` (initial: compute core + primary-source
forensic layer), `97901ea` (dual-verdict report generator + model-specific checks). Not merged to `main`.

## 2. What is BUILT (with file paths)

**Compute core** (`src/firm/core/compute/`, pure Python, no network, 100% covered)
- `multibagger.py` — §6 decomposition + the feasibility gate (`g/ROIC`), serial-dilution flag
- `dcf.py`, `reverse_dcf.py`, `scenarios.py`, `sensitivity.py`, `ratios.py`, `dupont.py`, `roic.py`
- `quality.py` — the forensic check library (see §2a)
- `divergence.py` — exogenous-series divergence (a metric moving against the force that should drive it)
- `models.py` — business-model detection → playbook selection

**2a. Forensic checks in `quality.py`** — cash-reality (ADR-0006: cash-vs-interest, cash+debt paradox,
cumulative CFO/PAT, ageing CWIP) · sector-branched lender checks (ADR-0002) · originate-to-sell
(ADR-0012: gain-on-sale reliance, provision-vs-book divergence, reserve suppression, held-for-sale
zero-reserve) · universal SPEC §5 (receivables/inventory stock-flow divergence, other-income share,
trader gross-vs-net tell) · model-specific (ADR-0020: contract assets, guarantees-to-net-worth,
capitalised cost, adjusted-vs-statutory EBITDA, **promoter lending = SEVERE**) · `forensic_screen()`
aggregates to PASS / REVIEW / HARD_FAIL.

**Data layer — primary sources** (ADR-0018 closed the long-standing open question)
- `adapters/india/exchange.py` — **BSE archives** = the point-in-time spine. `published_at` is the
  exchange dissemination timestamp (never the fetch date). Parsers tested against **real frozen API
  responses** in `tests/fixtures/bse_*.json`.
- `adapters/base/extract.py` — OCR fallback; an unreadable filing is a **signal** (`complete=False`),
  never a silent blank
- `adapters/base/tables.py` — provenance-locked figures bound to `(page, line)`; Indian number formats
- `adapters/base/sourcing.py` — primary-first grade policy (screener demoted to grade-B cross-check)
- `adapters/india/notes.py` — the line-by-line engine: note enumeration, `{clean|flag|unknown}`
  disposition per note, 100%-coverage gate, Schedule III mandatory rows, CARO 2020 clause triage
- `core/ingest/bronze.py` — immutable content-addressed archive + resumable, polite backfill
- `core/facts/store.py` — provenance + point-in-time query layer (Laws 2 & 3)

**Evidence + reporting**
- `schemas/evidence.py` + `core/validators/evidence_graph.py` — claim/evidence/entity graph with six
  blocking invariants (R1 no load-bearing claim without grade-A/B support … R6 no look-ahead)
- `core/graph/queries.py` — entity-path traversal (undisclosed-related-party detection)
- `schemas/report.py` + `core/validators/publication.py` + `core/report/render.py` — the **dual-verdict
  report** with three blocking publication gates (ADR-0019)

**Docs that matter:** `FORENSIC_METHODOLOGY.md` (reverse-engineered investigation patterns + the gap
analysis), `ADAPTIVE_FORENSICS.md` (business-model playbooks + line-by-line spec),
`REPORT_ARCHITECTURE.md` (the publishable report), `VALIDATION_TIER0.md` (live calibration evidence).

## 3. What is REMAINING (priority order)

### A. Phase 2 — wire the agents to the graph and the report ← **the real gap**
Verified: nothing in `core/agents/` or `core/orchestrator/` references `EvidenceGraph` or
`ResearchReport`. The machinery can detect and structure, but **no report has yet been published through
the new pipeline**. Work: have `financial_statement_analyst`, `forensic_accountant`, `business_analyst`
emit evidence-graph fragments; assemble a `ResearchReport`; run the publication gates; write to
`reports/{TICKER}/{run_id}/`. **Requires the owner's explicit go** (CLAUDE.md build order).

### B. Phase 5 — finish the memory loop (small wire-up, high value)
- `memory/predictions.jsonl` and `memory/lessons.jsonl` **do not exist yet**
- report `Criterion` objects (kill/rehabilitation) are not logged as predictions
- `core/monitoring/` (Brier, resolver, watch triggers) is built but nothing flows into it
- **`core/evolution/` is completely empty** — the prompt-evolution job (SPEC §7.3) was never written

### C. Phase 6 — the golden set ← **the biggest risk, and the honest measure**
`evals/golden_set/` and `evals/rubrics/` contain only `.gitkeep`; there is no `run_eval.py`.
**Every forensic threshold in `config/*.yaml` is provisional until this calibrates them.** Needs 30
Indian companies 2015–2021, point-in-time frozen, spanning fraud *types* (receivable, cash, guarantee,
inventory — not just lender). PLAN §9 warns this is 3–5× harder than the agent phases.

### D. Data-layer gaps
- **Public-records adapters** — MCA/ROC, CERSAI (charges/liens), NCLT, SEBI orders. This is the activist
  edge; `core/graph/queries.py` already supports the queries but has no data to run them on.
- **Exogenous series** (`config/exogenous.yaml`) — `divergence.py` works but has no data behind it
- **`firm backfill` CLI command** — `backfill_filings()` exists but isn't exposed on the CLI
- Matrix items needing external data: same-store growth, ECL stage migration, RERA/USFDA cross-checks

### E. Phase 4 — judgment tier
`valuation_modeler`, `thesis_synthesizer`, `red_team`, `portfolio_manager` exist as prompts only.

## 4. Owner directives (standing — do not violate)

1. **Primary sources first, always.** BSE/NSE archives, audited annual reports, SEBI. screener.in is a
   grade-B *cross-check*, never the source of record. The historical pain point: agents silently
   preferring easy secondary sources over the primary filing.
2. **Missing data is a signal, never a blank.** For a listed company the data is public by law; if it
   cannot be found, ask *why* — `disclosure_gap` / `INSUFFICIENT_DISCLOSURE`, never a silent skip.
3. **Zero hallucination.** Every figure traces to a cited primary source. If it isn't disclosed, write
   **UNAVAILABLE** — never estimate a number that will carry a forensic conclusion.
4. **Dual-verdict publishing** (ADR-0016). Publish on PASS as well as FAIL. A positive report must show
   the Verified-Clean Checklist (every check that ran, *passes included*) — "we found nothing" is
   worthless unless you show what you looked at.
5. **Adapt to the business structure** (ADR-0017). The two Hindenburg reports in the repo root were
   *method references only*, not the goal. n companies, n structures.
6. **Line by line.** Notes-to-accounts get enumerated and dispositioned, not keyword-spotted.
7. **Critique honestly.** The owner explicitly wants flaws named, not rubber-stamping.

## 5. Gotchas discovered the hard way (do not re-learn these)

- **Indian AR lines carry note-number prefixes** — `"Note 9: Trade Receivables 118.0"`. Naively, the `9`
  parses as a figure and the label collapses to "Note". Fixed in `tables.py` (`_LEADING_NOTE`), with a
  regression test. *Found by the end-to-end test, not by unit tests.*
- **Primary filings are often image-only / dynamic-render PDFs.** A naive text fetch returns nothing —
  which is exactly when an agent silently falls back to a secondary source. Hence the OCR fallback and
  `complete=False`.
- **BSE annual-report archive depth:** BSE *lists* reports back to 1997, but rows before **2012** have no
  authorise date and/or no PDF link. Honest dated-and-downloadable depth is **2012–2026 (15 years)**.
- **NSE aggressively blocks non-browser clients.** BSE is the implemented archive; NSE is a manual fallback.
- **Provisions moving is not automatically bad.** Reserve *suppression* (Sezzle: rate cut into a growing
  book) is the fraud tell; reserves *rising* (CreditAccess FY25) is honest recognition of stress. The
  checks encode this distinction — do not collapse it.
- **A `REVIEW` verdict is an invitation to investigate, not an accusation.** Legal framing is a blocking
  validator (P3).

## 6. Live calibration evidence (what has actually been tested on real data)

From `VALIDATION_TIER0.md`, using figures read directly from the companies' own filings:
- **Bajaj Finance FY25** → `PASS`. No false positive on a quality lender (divergence gap 0.46 vs the
  0.50 threshold — a deliberate near-miss worth knowing about).
- **CreditAccess Grameen FY25** → `REVIEW`. Impairment +327% on a book that *shrank* 2.9% fired
  correctly; `reserve_suppression` correctly did **not** fire (they provisioned more, honestly).
- Gain-on-sale reliance → **UNAVAILABLE** in both (not broken out in the source) — reported, not guessed.

The check library was also back-tested against the exact figures in the two Hindenburg reports
(Carvana gain-on-sale 2.2× NI; Sezzle provisions +130% on a +6% book; Carvana GPU +209% vs Manheim
−20.3%) — all fire as expected.

## 7. Suggested next step

**Phase 2** (§3A) is the highest-value unblock: it converts everything built into actual published
reports on real Indian companies. Then §3B (predictions logging — a small wire-up), then the golden set.

Deliberate recommendation *against* doing the golden set first, despite it being the honest measure:
it is the single biggest lift in the project, and it is far more useful once agents are producing
reports to score.
