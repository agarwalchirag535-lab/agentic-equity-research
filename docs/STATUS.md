# STATUS.md — project state, handoff, and what to do next

> **Read this first if you are new to this repo** (new session, new agent, new platform, or the owner
> after a break). It is the single authoritative answer to *"what is built, what is not, and what
> should happen next."* Last updated **2026-08-01**.
>
> Reading order for a cold start: this file → [`CLAUDE.md`](../CLAUDE.md) (the laws) →
> [`SPEC.md`](SPEC.md) (the constitution) → [`DECISIONS.md`](DECISIONS.md) (why things are the way they
> are, ADR-0001…0044). Keep this file updated as work lands — a stale STATUS is worse than none.

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
| **2 — three agents, deep** | ✅ **complete — acceptance test passes; first report published (§6a)** |
| 3 — full roster + orchestrator | ✅ **complete — acceptance run published 2026-08-01 (§6b)**: 9 of 9 agents staffed and rendered, every data prerequisite satisfiable (ADR-0030–0044) |
| 4 — judgment tier | ⚠️ prompts exist as markdown; numeric fields now registered null-only (ADR-0043) so wiring cannot open a Law-1 hole; **needs the owner's explicit go per CLAUDE.md build order** |
| 5 — memory loop | ⚠️ half-built (see §3) |
| 6 — evaluation / golden set | ❌ not started (see §3 — this is the biggest risk) |

**Tests:** 663 passing · `core/compute` at **100%** (the Phase-1 gate; note `--cov-fail-under=100` scopes
to the compute layer only, per `pyproject.toml`). `make cov` was silently broken until 2026-07-30 — it
invoked a bare `python`, absent on stock macOS, so the gate failed before measuring anything; it now
resolves the interpreter and the 100% is verified rather than asserted · the Phase-2 modules
(`pipeline/{derive,checks,filing,deep_dive}`, `report/{criteria,assemble}`, `agents/evidence`) at **98%**
line coverage (derive 97%, filing 100%).

```bash
python -m pytest --cov --cov-fail-under=100
```

**Git:** branch `feat/forensic-primary-source-layer` — `75ffbfa` (initial: compute core + primary-source
forensic layer), `97901ea` (dual-verdict report generator + model-specific checks), plus uncommitted
Phase-2 work. Not merged to `main`.

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

**2b. Phase 2 — the agents are wired (ADR-0021).** `python -m firm deep-dive --ticker X --as-of D` runs
the whole chain and publishes to `reports/{TICKER}/{run_id}/report.md` + `.json`:

| module | what it does |
|---|---|
| `core/pipeline/derive.py` | point-in-time facts view + `Derivation` (formula + input `Fact`s + a citation whose grade is the **worst** input grade); a metric with missing inputs lands in `missing`, never as a zero |
| `core/pipeline/checks.py` | evaluates **every** playbook check into PASS / FLAG / UNAVAILABLE(reason) / NOT_APPLICABLE(reason), and feeds the screen only from checks that actually ran |
| `core/pipeline/filing.py` | walks an audited filing: registers grade-A `(page,line)`-bound facts, enumerates the notes, dispositions each from the checks that read it, scans Schedule III + CARO |
| `core/agents/evidence.py` | agent output → evidence-graph fragment; unknown `fact_id` = hard problem; load-bearing promotion + run-wide cap |
| `core/report/criteria.py` | kill / rehabilitation `Criterion` objects computed from metrics + config, dated to next FY close + filing lag |
| `core/report/assemble.py` | the verdict ladder and the `ResearchReport` assembly |
| `core/pipeline/deep_dive.py` | the orchestration + the four discipline enforcements (see below) |

What the pipeline enforces that nothing before it could:
1. **An agent may not author a number.** Numeric schema fields are re-checked against `core/compute` with
   the arithmetic validator; a field the compute layer cannot produce must be `null`.
2. **An agent may not cite a fact that does not exist** — the citation validator runs over **every string
   the agent authored** (narrative, claim texts, `what_it_does`, `moat`, `disconfirming_search`,
   `open_questions`, flag strings — anything typed `str` in its schema except the harness-set identity
   fields), against the run's known fact ids, with one corrective retry, then `AgentDisciplineError`.
3. **The forensic agent may not narrate past a deterministic HARD_FAIL**; its veto can only make a verdict
   worse.
4. **A report that fails P1/P2/P3 or R1–R6 never reaches disk** — the violations come back on the result
   object instead.

CLI: `firm deep-dive` (provider `local|claude_code|anthropic|openai`) and `firm packets` → answer each
`{agent}.md` by hand → `firm deep-dive --answers <dir>` (ADR-0010: agents run with no API key).

**Docs that matter:** `FORENSIC_METHODOLOGY.md` (reverse-engineered investigation patterns + the gap
analysis), `ADAPTIVE_FORENSICS.md` (business-model playbooks + line-by-line spec),
`REPORT_ARCHITECTURE.md` (the publishable report), `VALIDATION_TIER0.md` (live calibration evidence).

## 2b. Line-by-line depth (ADR-0022, 2026-07-30)

The owner's critique of the first report was that it was beginner-level: it said revenue grew 11% and never
asked *why* — volume or price, one buyer or many, arm's length or related-party — and reported debt levels
without asking what the debt bought. `config/line_items.yaml` + `core/pipeline/interrogate.py` now put ~35
analyst questions to every company across 10 statement lines, each ANSWERED with its fact ids, UNANSWERED
with the filing row that would close it, or NOT_APPLICABLE with the reason it was suppressed.

The distinction that makes it honest: a **DISCLOSURE** gap (asked, the filing did not carry it) may degrade
the verdict; a **CAPABILITY** gap (no extractor built yet) may not — it lowers confidence instead. Charging
a company for the firm's own unfinished note-parser would reject every good business we cannot yet read.

## 3. What is REMAINING (priority order)

### PHASE 3 — every data prerequisite is now satisfiable (ADR-0030/0031)
`config/roster.yaml` declares all 14 agents with stage, gate, phase and data prerequisites; `plan_run`
enforces build order and reports three distinct kinds of skip. 54 governance documents ingested from the IR
sections that discovery had never opened. Remaining in this phase:
1. ~~wire `deep_dive` to the roster~~ DONE (ADR-0033) — `--phase`/`--documents`; coverage gaps reach the
   report but never the verdict; pre-flight names unstaffed agents. DONE (ADR-0034): 8 agents now appear in a published report's
   `agent_versions`. Shareholding is now registered as grade-A quarterly facts and CITED in the report (ADR-0035).
   The transcript chain is complete (ADR-0036/0037): `adapters/india/transcripts.py` parses dated verbatim
   guidance quotes (statement/question separation, unit-anchored values only), `core/ingest/transcripts.py`
   registers them grade-A, and `run_deep_dive` feeds the series to the packet as `management_guidance` with
   citable ids — 57 guided figures across 13 real quarters FY20-FY26. The older shareholding layout is
   fixed (ADR-0038): 27 of 27 filings now parse and **26 quarters** register grade-A (Q1FY20-Q4FY26, was
   12). Peer comparison is built (ADR-0039), so `sector_analyst` is staffed and every Phase-3 data
   prerequisite in `config/roster.yaml` now has something behind it.
2. ~~parser + registration for transcripts (guidance extraction)~~ DONE (ADR-0036/0037)
   ~~older shareholding layout~~ DONE (ADR-0038). Two stated gaps left: one filing (Q3FY26) has its
   reporting date scrambled by the text layer and is refused rather than guessed (that quarter is
   duplicated by another file); and SEBI's 2025 NDU / other-encumbrance declarations are not parsed — only
   the pledge question is. Folding NDU into `pledged` would misreport it.
3. ~~peer-set ingest for `sector_analyst`~~ DONE (ADR-0039). `core/pipeline/peers.py` + `--peer TICKER`
   on `deep-dive`/`packets`. Every row is measured on one period BOTH companies cover — the subject files
   before its peer, so "each company's latest" would compare FY26 against FY25 and look normal doing it.
   Live: ALKYLAMINE vs BALAMINES on FY25 — larger (₹1,571.8cr vs ₹1,273.6cr), slightly thinner net margin
   (11.83% vs 12.27%), much faster collection (53.6 vs 70.4 days), 6.1% vs 0.9% sales CAGR FY21-FY25.
   **Next for this item:** peers are supplied by ticker and must already be ingested; pointing
   `discover-filings` at a peer's IR site to build the peer set automatically is not done. Only three
   measures are compared (scale, net margin, receivable days) plus growth — inventory days and interest
   cover need COGS/EBIT, which the peer metric set does not carry cleanly, and proxies were refused.


### 0. ~~RECENCY BEATS PROVENANCE~~ — FIXED 2026-07-30 (ADR-0029)
Resolution is now `(grade, published_at DESC)`. FY26 Sales/receivables/inventory/cash resolve grade A from
the filing. Derived ratios stay grade B by the worst-input rule, correctly, until the AR ingest widens.

<details><summary>original entry</summary>
`FactStore.query_fact` resolves ties with `ORDER BY d.published_at DESC`. A screener snapshot taken today
therefore outranks the audited annual report published last month, and owner directive 1 says the opposite:
the AR is the source of record and screener.in is a grade-B **cross-check**. Demonstrated on ALKYLAMINE FY26:

| metric | resolves to | should be |
|---|---|---|
| `pnl:Sales` FY26 | 1536.00 **grade B** (screener) | 1535.86 grade A (AR p.13 l.14) |
| `balance_sheet:Trade Receivables` FY26 | 230.50 grade A | correct — only because the screener has no such row |

So the grade-A facts are ingested and only win where the screener is silent. Every published derived ratio is
consequently grade B, and `fact_citations` contains **zero grade-A entries**. The forensic layer is reading
primary sources; the *report* is still quoting the aggregator wherever both exist.

Fix: order by `(grade, published_at)` — best grade first, most recent within a grade — while keeping the Law 3
`published_at <= as_of` filter untouched. This is a load-bearing change to the resolver every other layer
depends on, so it needs its own tests: a restatement must still be invisible before its publication date, and
a grade-A filing must not resurrect a figure the company later corrected.
</details>

### 0b. Substantive note coverage is 9% against a 50% floor
Not a defect — the floor is right and the coverage is not there yet. Needs note-content readers for inventory,
receivables, borrowings, contingent liabilities, tax, leases, employee benefits and segment, on the pattern of
`notes_content.related_party_summary`. Several sessions of work, one note category at a time.

### 0. ~~A FALSE-POSITIVE FORENSIC_CAUTION~~ — FIXED 2026-07-30 (ADR-0025)
Both causes fixed: `ExternalInputs` is now canonical ₹ crore (the ADR-0024 unit fix had normalised only the
fact store, so a lakh cash figure met a crore asset base and produced `cash/assets 496.6%`), and
`config/thresholds.yaml:check_inputs` gives the deterministic checks the input-plausibility precondition the
narration layer already had. ALKYLAMINE now returns INSUFFICIENT_DISCLOSURE with `disclosure_gap` as the only
live flag. **Still open from this**: a check may silently divide a grade-A filing figure by a grade-B
screener figure; mixed-grade arithmetic should be surfaced or refused.

<details><summary>original entry</summary>
Found 2026-07-30 on the first primary-source run of ALKYLAMINE. The deterministic screen returned
`FORENSIC_CAUTION` on `cash_debt_paradox`, and the finding is **not real**. Its detail line reads
`cash/assets 496.6% at cost of debt 100.0%` — cash cannot be 5x total assets, and the 100% cost of debt is
Interest ₹1cr ÷ Borrowings ₹1cr, i.e. two *rounded* grade-B screener figures whose ratio carries no
information. A published FORENSIC_CAUTION on a real listed company resting on that would be a serious
error, and the legal-framing gate (P3) cannot catch it because the check is deterministic and the prose is
correctly hedged.

The root cause is architectural, not a bad threshold: **ADR-0022's plausibility discipline exists only in
the narration layer** (`config/line_items.yaml` `plausible:`), where it correctly refuses to narrate the
same degenerate 100% cost of debt. `core/compute/quality.py` has no equivalent, so a check whose inputs are
degenerate returns FLAG instead of UNAVAILABLE. Work:
- give the checks an input-plausibility precondition (materiality floor on the denominator; a
  cash/assets ratio > 1 is arithmetically impossible and must fail loudly, not flag)
- ban mixed-grade arithmetic in a check: cash here is grade A from the filing, borrowings grade B from the
  screener, and the ratio silently spans both
- the `cash/assets` denominator itself is wrong and needs tracing — 94.15/496.6% implies a ₹19cr asset base
  against a real ~₹2,000cr balance sheet
</details>

### A. Close the data gap the first real report exposed ← **the highest-value next step**
**Primary sources are now wired for any company (ADR-0024/0026).** Two commands:
```
firm discover-filings --ticker TICKER --url <company IR financials page>   # writes the manifest
firm deep-dive --ticker TICKER --filings data/manifests/TICKER-filings.json
```
ALKYLAMINE is done end to end: 10 annual reports FY17-FY26 as grade-A facts, cross-checked against each
other. Note *contents* are now partly read (ADR-0027): the Ind AS 24 related-party note is parsed, so
`promoter_lending` runs and unavailable checks are down to 29%. On ALKYLAMINE it is a real finding — the note
discloses only director remuneration (₹27.69cr), no related-party sales, loans or guarantees.

**The one remaining blocker to a substantive report:** `adapters/india/notes.py:_NOTE_HEADING` does not match
the note headings in these filings. Scoped enumeration (`notes_section_start`) correctly locates the section
at p.86 but finds 3 notes where there are ~49, so `substantive_share` stays 0% and the verdict is
`INSUFFICIENT_DISCLOSURE` for that reason alone. `adapters/india/notes_content.py:_NOTE_HEADING` matches them
reliably (it locates notes 38-49) — **port that pattern**. One file, and then the governance, related-party
and ratio-determinant questions all become answerable.

**As of ADR-0022 this backlog generates itself.** Every report now emits `disclosure_backlog`: the
deduplicated, ordered list of primary-source rows that would answer a question the pipeline had to leave
unanswered. Read it off the latest report rather than from prose here —
`reports/ALKYLAMINE/<run>/report.md` §"What would close the gaps" is the live worklist (16 entries on the
2026-07-23 run, led by tonnage/realisation, customer concentration, and the Ind AS 24 related-party note).
The three metrics named in `config/line_items.yaml` with no derivation behind them —
`receivable_days`, `receivable_days_delta`, `inventory_days` — are allowlisted in
`tests/test_line_item_registry.py`; deleting an entry from that allowlist is how you'd start the work.

The ALKYLAMINE run (§6a) returned `INSUFFICIENT_DISCLOSURE` because 4 of 7 applicable checks had no
inputs. Every one of those inputs is in the audited annual report, which the pipeline can already walk —
what is missing is the *numeric extraction quality* on real ARs (ADR-0011) plus a couple of series:
- **cash and cash equivalents** — without it the sharpest check in the library (`cash_interest_inconsistent`,
  "is the cash real?") cannot run at all. Highest single-item value.
- **receivables / inventory / payables** — unlock the stock-flow divergence checks and working-capital days
- **the Schedule III promoter-lending row** — a SEVERE check with no data behind it today
- `firm ingest` writes a grade-B screener snapshot only; wire `backfill_filings()` to the CLI so a run can
  fetch and walk the AR for a ticker in one command (`firm deep-dive --filing latest`).

### B. Phase 3 — the remaining 11 agents onto the same rails
The three Tier-2 agents are wired; the pattern to copy is `PHASE2_AGENTS` + `NUMERIC_FIELD_SOURCES` +
`_narration()` in `core/pipeline/deep_dive.py`. Sequencing them behind Gates A–E in
`core/orchestrator/` is the actual Phase-3 work; `management_analyst` / `ownership_flows_analyst` also need
shareholding + pledge ingestion, which does not exist yet.

### C. Phase 5 — finish the memory loop
- ✅ **done 2026-07-30 (ADR-0023):** a published report's kill criteria are logged to
  `memory/predictions.jsonl`, idempotent by `(run_id, metric)`, at the report's own confidence as the
  probability. Kill criteria only — rehabilitation criteria are counterfactuals the firm is not
  forecasting. Blocked reports log nothing. `run_deep_dive(memory_root=...)` isolates the ledger in tests.
- `memory/lessons.jsonl` **still does not exist**
- `resolver.py` is built but **never invoked**: nothing resolves a prediction against a later filing, so
  the ledger has inputs and no loop. This is the next Phase-5 step and it needs a second point-in-time
  run of the same ticker to have anything to resolve against.
- `core/monitoring/` (Brier, resolver, watch triggers) is built but nothing flows into it
- **`core/evolution/` is completely empty** — the prompt-evolution job (SPEC §7.3) was never written

### D. Phase 6 — the golden set ← **the biggest risk, and the honest measure**
`evals/golden_set/` and `evals/rubrics/` contain only `.gitkeep`; there is no `run_eval.py`.
**Every forensic threshold in `config/*.yaml` is provisional until this calibrates them.** Needs 30
Indian companies 2015–2021, point-in-time frozen, spanning fraud *types* (receivable, cash, guarantee,
inventory — not just lender). PLAN §9 warns this is 3–5× harder than the agent phases. The Phase-2
pipeline is now the thing an eval would drive: `run_deep_dive(..., as_of=<historical date>)` already
refuses to read a filing published after `as_of`.

### E. Data-layer gaps
- **Public-records adapters** — MCA/ROC, CERSAI (charges/liens), NCLT, SEBI orders. This is the activist
  edge; `core/graph/queries.py` already supports the queries but has no data to run them on.
- **Exogenous series** (`config/exogenous.yaml`) — `divergence.py` works but has no data behind it
- Matrix items needing external data: same-store growth, ECL stage migration, RERA/USFDA cross-checks

### F. Phase 4 — judgment tier
`valuation_modeler`, `thesis_synthesizer`, `red_team`, `portfolio_manager` exist as prompts only. Until
they run, every report says so explicitly in its Valuation and Management sections rather than leaving them
blank — see the ALKYLAMINE note.

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
- **A boolean that defaults to `False` cannot tell you a check never ran.** `ForensicMetrics` booleans made
  "clean" and "not evaluated" the same value; the published checklist would have asserted passes that never
  happened. Hence `core/pipeline/checks.py` records an explicit outcome per check — never infer a pass from
  the absence of a flag.
- **100% note coverage is cheap to fake.** Dispositioning every note `unknown` satisfies the coverage gate
  while reading nothing, so `NotesReview.substantive_share` (notes a real check looked at) is what the
  verdict consults. If you add a note category, add its checks to `NOTE_CHECKS` or coverage becomes theatre.
- **Point-in-time applies to the document, not just its figures.** Filtering an unpublished filing's facts
  at the query layer still leaks its notes, its Schedule III rows and its auditor language into the run.
  `run_deep_dive` skips a filing whose `published_at > as_of` entirely.
- **The citation validator treats every digit as a claim — including one glued to a word.** A number in
  agent prose must be followed by a `[fact:...]` token whose id is real *and* whose value matches what was
  quoted (rounding to the precision you wrote is fine; changing the digits is not). "Rs9999 crore" is
  caught precisely because it is ordinary Indian prose and was the way a fabricated figure got through.
  Accepted strictness, all documented in `validate()`: a **bare calendar year** ("in 2019") is a claim — use
  `FY19`, which is a recognised label; a **chemical formula** ("CO2") reads as a glued number, so write the
  compound out; a **range** ("18-20%") is two numbers needing two sources; and two numbers before one token
  both bind to that token, so cite each figure separately. A false positive fails the run and is corrected
  on retry, which is the safe direction here.
- **Typographic minus signs are normalised before scanning.** U+2212 parsed as a *positive* number, so a
  flipped sign passed the value check while correctly-written negative prose failed it. If you touch
  `_NUMBER`, keep `_MINUS_SIGNS` applied first.
- **Fact ids contain colons — the citation grammar must accept them.** `derived:cum_cfo_pat` and
  `screener-X:pnl:Sales:FY26` could not be cited at all under the original `[A-Za-z0-9_-]+` id pattern, so
  the validator was satisfiable *only* by writing no numbers in prose: it passed by vacuum, not by
  provenance. Also note `window` bounds where the token may *start*, not how much text is searched — a
  namespaced id is longer than the window.
- **The citation surface is every authored string, not the fields you remember.** The first version checked
  `narrative` plus claim texts, and an audit walked fabricated percentages into a published report through
  `what_it_does` and `disconfirming_search`. `authored_texts()` now checks every `str` field on the agent
  output, so a new schema field is covered the moment it exists. If you ever narrow it back to a name list,
  you have re-opened the hole.
- **Screener data cannot produce a forensic pass.** Receivables, inventory and cash are not broken out in
  the screener snapshot, so four of seven universal checks are structurally unavailable from it. Any run
  without an AR walk should be expected to return `INSUFFICIENT_DISCLOSURE`; that is the design working.

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

## 6b. The published Alkyl Amines report (2026-07-31)

`reports/ALKYLAMINE/2026-07-23-0c32a293299a/` — **`QUALITY_WRONG_PRICE`**, confidence 0.55, eight agents,
408 lines. The first report the firm has published on primary sources end to end, and the first with a
verdict that is a judgment about the business rather than about our own reading of it.

What changed under it, in one line each (ADR-0036/0037/0038):

| before | after |
|---|---|
| 4 metrics read from the annual reports | **36**, FY16-FY26, essentially all grade A |
| every derived ratio grade B | ROIC, OPM, cash conversion, working capital, cost structure all grade A |
| 11 of ~63 notes enumerated, 9% substantive | **45 enumerated, 100% dispositioned, 64% substantive** |
| 32% of line-by-line questions answered | **56%** |
| `INSUFFICIENT_DISCLOSURE` — the opacity was ours | `QUALITY_WRONG_PRICE` — the finding is the company's |

The finding itself: forensically clean on six of seven applicable checks, including the one that matters
most — the reported cash and bank balances yield **7.78%** on the average balance, which is a real term-
deposit rate and not what a fabricated balance earns. Profit converts to cash (ΣCFO/ΣPAT **1.27**),
receivable days moved **1.2** days, the related-party note discloses remuneration and nothing else, and
the promoter stake is flat at **72.05%** and unpledged across twelve quarters. Against that: return on
capital **10.3%** and rolling three-year incremental return **−23%**, on capex that ran at **3.44×** the
depreciation charge — expansion, not replacement, so the poor return cannot be explained away as the cost
of standing still. The margin question is answered rather than asserted for the first time: the material
cost ratio moved **+1.7pp** against +0.5pp for employees and +0.7pp for other expenses, so the margin went
to feedstock, which is the one line management does not set.

**What the report still cannot do, printed in it rather than hidden:** no tonnage or realisation, so the
volume-versus-price question that a spread business turns on is unanswered; no transcript parsing, so the
promise-vs-delivery scorecard is empty across thirteen ingested calls; no institutional split or volume
history, so smart-money and days-to-exit are null; no valuation tier. The `disclosure_backlog` in the
report is the live worklist — 31 entries, led by the production-and-sales table and the segment note.

## 6a. Phase 2 evidence: what the pipeline actually produced

**Acceptance test (SPEC §11 Phase 2)** — `tests/test_phase2_e2e.py`, offline and deterministic (agent
answers are scripted, so what is under test is the pipeline and the gates, not an LLM's mood). Five
companies, five verdicts: `COMPOUNDER`, `QUALITY_WRONG_PRICE`, `FORENSIC_CAUTION` (the accounting-fraud
pattern — profit that never becomes cash with receivables absorbing the gap), `INSUFFICIENT_DISCLOSURE`,
`WATCH`. The fraud company's report ships with its flags visible, its replication steps stated, and hedged
language; the same company with a forensic agent that returns `PASS` fails the run instead of publishing.

**One honest deviation from SPEC's wording:** SPEC says the fraud case should come *from the golden set*.
The golden set does not exist yet (Phase 6, §3D), so the fraud company is a synthetic series built to the
pattern the check library was back-tested against (§6). The pipeline is exercised; the *calibration* claim
SPEC wanted from a real historical case is still outstanding and belongs to Phase 6.

**Independent audit (2026-07-30) found two real breaches in the citation gate, both now fixed.** (1) The
gate originally read only `narrative` and the claim texts, while `render.py` also publishes `what_it_does`,
`disconfirming_search` and `open_questions` — so fabricated figures ("controls 73.4% of the market",
"9,999 crore of revenue") could reach a published COMPOUNDER report through fields nobody checked.
`authored_texts()` in `core/pipeline/deep_dive.py` now treats **every string an agent returns** (recursing
into nested schema models, so the Phase-3/4 agents inherit it) as prose to
be checked, which is enumeration-proof as schemas grow. (2) A re-audit then found that `citation.py` itself
had two defects: its id grammar excluded the colons every real fact id contains (so *no* number could ever
be cited — the validator passed by vacuum), and its number pattern skipped digits glued to a preceding word
("Rs9999 crore" sailed through). Both are fixed, and a **value check** was added: a number citing a real
fact must state that fact's figure, so keeping the citation and changing the digits now fails.
Regression tests: `test_a_fabricated_number_in_any_rendered_agent_field_fails_the_run`,
`test_a_number_cited_to_a_real_fact_but_misquoted_fails_the_run`, and four new cases in
`tests/validators/test_validators.py`. Three other break attempts held without changes: numbers smuggled
into validated prose, `COMPOUNDER` over a fired SEVERE flag, and publishing below full note coverage on a
non-`INSUFFICIENT_DISCLOSURE` verdict.

**First real report** — `reports/ALKYLAMINE/2026-07-23-433c94208117/` (grade-B screener facts, FY15–FY26,
no AR walked). Verdict **`INSUFFICIENT_DISCLOSURE`**: 4 of 7 applicable checks had no inputs (57% vs the
34% ceiling), confidence 0.21. What it did establish, deterministically:
- ΣCFO/ΣPAT **1.27** and CFO/PAT **1.33** — reported profit has converted to cash; the "cash isn't there"
  family of failures does not appear in the figures available
- ROIC **10.3%** but rolling 3-year **incremental** ROIC **−24%** — the specific failure the
  `financial_statement_analyst` mandate warns about, and the reason the feasibility gate returns
  `NEEDS_EXTERNAL_FUNDING` (2.52× NOPAT required to fund 25.8% growth for a 5x/7y target)
- unavailable, with reasons published: cash-yield test, cash-vs-debt paradox, promoter lending, the
  mandated-disclosure scan

That verdict is the system working, not failing: on a grade-B snapshot with the notes unread, a thesis
would have been the dishonest answer. It is also a concrete work list — see §3A.

**Current report** — `reports/ALKYLAMINE/2026-07-23-0c32a293299a/`, and it superseded the paragraph
above: verdict **`QUALITY_WRONG_PRICE`**, 8 agents narrating, confidence 0.55, 86% of the playbook
evaluable, 64% of notes substantively dispositioned, grade-A citations throughout. Its own stated limits
(no transcript corpus, ownership visible only from Q2FY23, no peer) are exactly what ADR-0036–0039 then
closed — **no report has been published since**, so the phase-3 re-run is what converts that work into
output. §7 is written against this state, not the paragraph above.

## 6b. Phase 3 evidence: the acceptance run

`reports/ALKYLAMINE/2026-08-01-66a2eb26d679/` — **9 of 9 phase-3 agents staffed, narrated and rendered**,
verdict `QUALITY_WRONG_PRICE`, confidence 0.55, 100% note coverage with 64% substantive, 56% of the
line-by-line questions answered, 31 open items in the disclosure backlog.

Command (the whole chain, no API key — ADR-0010):

```bash
python -m firm deep-dive --ticker ALKYLAMINE --as-of 2026-08-01 --phase 3 \
  --documents data/manifests/ALKYLAMINE-documents.json \
  --filings data/manifests/ALKYLAMINE-filings.json --peer BALAMINES --answers <dir>
```

Ingest on that run: 10 annual reports as grade-A facts, **26 of 27** shareholding filings, **57 guided
figures** from 10 of 14 transcripts, 1 peer comparable. All four citation families reach the published
page — filing (31), peer (6), guidance (2), shareholding (2).

What the new evidence changed, concretely: `transcript_analyst` went from *"there is no conclusion here
to disconfirm, which is itself the finding"* to a five-year guidance walk-down (mid-teens → GDP-anchored)
quoted verbatim with call dates; `management_analyst` gained the promise-versus-delivery half it had
previously reported as missing; `ownership_flows_analyst` reads seven years of quarterly ownership
instead of three; `sector_analyst` ran for the first time and put a peer on the page. **The verdict did
not move.** More evidence, same answer, is the separation of powers working.

Three defects the run itself surfaced, all fixed: the branch divergence (below), the layout-mode
shareholding regression (ADR-0044), and three agents whose prose was dropped from the report they were
credited in (ADR-0044).

**The divergence worth remembering.** The re-run failed with 19 `unknown_fact_id` violations because the
report on disk had been produced by a *sibling branch* whose whole-filing extraction this branch lacked;
`reports/` is gitignored, so the artifact survived a branch switch in the same worktree and looked like
ours. The citation gate was right and the branch was wrong. Both lines are now merged, and the ADR
numbering collision that caused (both wrote 0036–0038) is recorded in `DECISIONS.md`.

## 7. Suggested next step

Updated 2026-08-01, in order:

1. ~~Re-run ALKYLAMINE at `--phase 3`~~ **DONE 2026-08-01** — see §6b. Nine agents narrated,
   `sector_analyst` for the first time; guidance, ownership, peer and filing citations all reach the page.
2. **Substantive note coverage 9% → 50% (§0b)** — the owner's core directive is line-by-line depth, and
   this is the largest gap between what the docs claim and what the system reads. One note category at a
   time (inventory, receivables, borrowings, contingent liabilities, tax, leases, employee benefits,
   segment), on the `related_party_summary` pattern.
3. **Phase 4, the judgment tier — blocked on the owner's explicit go (CLAUDE.md build order).** The firm
   currently rejects far better than it affirms, and affirming is half the mandate. The Law-1 hole its
   numeric fields would have opened is closed pre-emptively (ADR-0040): every field is registered
   null-only until wiring gives it a compute source.
4. **The golden set.** The old argument for deferring it — "wait until the pipeline can produce a
   substantive verdict" — expired when `QUALITY_WRONG_PRICE` published. It is the honest measure and
   every threshold is provisional until it runs.

Also on the board, from the owner's 2026-08-01 goal statement: a **sector sweep** (`firm sweep`-style
orchestration: sector → company list → one report each — a thin loop over the existing engine, and the
golden set is itself a 30-company sweep), and a **questions-for-management artifact** assembled from the
open_questions + disclosure_backlog the reports already emit.
