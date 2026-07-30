# MASTER BUILD PROMPT — "Agentic Equity Research Firm"
### Micro / Small / Mid-cap multibagger discovery engine (India-first, market-agnostic core)

---

## HOW TO USE THIS PROMPT

1. Create an empty git repo. Open it in **Claude Code** (or Cowork).
2. Paste this entire document as your first message, prefixed with:
   > *"This is the build spec for the project. Read it fully. Do NOT write any code yet. First produce `docs/PLAN.md` restating the architecture in your own words, list every assumption you are making, list every open question, and give me the Phase 0 acceptance test. Then stop and wait."*
3. Approve the plan. Then say: *"Build Phase 0. Stop at the acceptance test."*
4. Never let it skip phases. Never let it build Phase 3 before Phase 1's acceptance test passes.

Save this file as `docs/SPEC.md` in the repo. It is the constitution.

---

## 1. MISSION

Build a **research firm made of specialised agents**, not a stock screener with a chatbot on top.

The objective is **not** to find profitable companies. It is to answer one question with an auditable evidence chain:

> *"Can this business plausibly compound earnings fast enough, for long enough, funded by its own returns, under a management team that has historically done what it said — such that a 5–10x over 5–8 years is a live scenario and not a fantasy?"*

Everything in the system serves that question. A company that is profitable but cannot pass the growth-feasibility math (§6) is **rejected**, no matter how good it looks.

**Scope:** Indian listed equities, market cap ₹300 cr – ₹30,000 cr (micro/small/mid). Core engine must be market-agnostic; India-specific logic lives only in `adapters/india/`.

**Hard boundary:** This system produces *research artifacts*. It never places orders, never connects to a broker execution API, and never emits "buy this." Outputs are theses with explicit assumptions, kill criteria, and confidence intervals.

---

## 2. NON-NEGOTIABLE ENGINEERING LAWS

These are stated first because every downstream design decision follows from them. Violating any of these is a build failure.

**LAW 1 — Deterministic compute / LLM narration separation.**
No financial number is ever produced by a language model. Ever. All ratios, growth rates, DCFs, scenarios, and sensitivities are computed by pure Python in `core/compute/` with unit tests. The LLM receives computed numbers as input and writes reasoning about them. If an LLM outputs a number that did not come from the compute layer, the validator fails the run.

**LAW 2 — Provenance or it doesn't exist.**
Every fact in the fact store carries `(doc_id, page/paragraph, published_at, extractor_version)`. Every numeric claim in every report renders with a citation token. A post-processing validator scans the final report, extracts every number, and asserts each maps to a `fact_id`. Unsourced number → build fails.

**LAW 3 — Point-in-time discipline.**
Every document row has `published_at`. Every pipeline run has an `as_of` date. The data access layer **filters by `published_at <= as_of` at the query layer, not at the agent layer**. This is what makes historical evaluation (§9) honest. Look-ahead bias is the single easiest way to build a system that appears brilliant and is worthless.

**LAW 4 — Structured output contracts.**
Every agent returns a Pydantic-validated JSON object, never free prose. Prose lives in a `narrative` field *inside* the schema. Schema violation = automatic retry with the validation error, max 2 retries, then hard fail with a logged artifact. Agents never talk to each other in natural language; they read each other's JSON.

**LAW 5 — Idempotent, resumable, cached.**
A run is a DAG of tasks. Each task is keyed by `hash(agent_version, prompt_version, input_fact_ids, as_of)`. Re-running is free if nothing changed. A crash at stage 7 resumes at stage 7. Every LLM call is cached to disk by that key.

**LAW 6 — Portability contract.** (this is your "don't get stuck on one platform" requirement)
- All agent definitions are **markdown files with YAML frontmatter** in `agents/`. Zero prompts inside `.py` files.
- All model access goes through one interface: `core/llm/provider.py` with `AnthropicAdapter`, `OpenAIAdapter`, `LocalAdapter`. Swapping providers = one line in `config/models.yaml`.
- State is SQLite + Parquet + JSONL + Markdown. No proprietary formats, no vendor-hosted state, no vector DB as source of truth.
- Entry point is a CLI (`python -m firm run --ticker X --as-of 2026-07-23`), never a notebook.
- Everything is git-tracked including prompts, so prompt changes are diffable.

**LAW 7 — Agents never see raw HTML.**
Scrapers write to bronze. Parsers normalise to silver. Agents read gold. An agent that reads a raw web page will hallucinate structure that isn't there.

---

## 3. REPOSITORY STRUCTURE

Build exactly this. Do not improvise the layout.

```
equity-firm/
├── CLAUDE.md                    # repo constitution: laws, conventions, what NOT to do
├── docs/
│   ├── SPEC.md                  # this file
│   ├── PLAN.md                  # your restatement + assumptions
│   ├── DECISIONS.md             # ADR log: every architectural choice + why
│   └── DATA_SOURCES.md          # every source, licence, rate limit, reliability grade
├── config/
│   ├── models.yaml              # model per agent role + temperature + token budget
│   ├── universe.yaml            # mcap bands, exclusions, liquidity floors
│   ├── thresholds.yaml          # EVERY hardcoded number lives here, nowhere else
│   └── sectors.yaml             # sector taxonomy + per-sector KPI definitions
├── agents/                      # one .md per agent — mandate, inputs, outputs, DoD
│   ├── _shared/
│   │   ├── house_style.md       # analytical standards all agents inherit
│   │   ├── epistemics.md        # how to express uncertainty, when to say "unknown"
│   │   └── forbidden.md         # anti-patterns: vague adjectives, unsourced claims
│   ├── macro_strategist.md
│   ├── sector_analyst.md
│   ├── business_analyst.md
│   ├── unit_economics_analyst.md
│   ├── financial_statement_analyst.md
│   ├── forensic_accountant.md
│   ├── management_analyst.md
│   ├── transcript_analyst.md
│   ├── ownership_flows_analyst.md
│   ├── valuation_modeler.md
│   ├── thesis_synthesizer.md
│   ├── red_team.md
│   ├── portfolio_manager.md
│   └── post_mortem.md
├── schemas/                     # Pydantic models — one per agent output
├── core/
│   ├── llm/                     # provider abstraction, caching, retry, budget guard
│   ├── compute/                 # ALL math lives here, 100% test coverage required
│   │   ├── ratios.py
│   │   ├── dupont.py
│   │   ├── roic.py
│   │   ├── quality.py           # accruals, Beneish, Altman, Piotroski, Benford
│   │   ├── dcf.py
│   │   ├── reverse_dcf.py
│   │   ├── scenarios.py
│   │   ├── sensitivity.py
│   │   └── multibagger.py       # §6 decomposition + feasibility gate
│   ├── orchestrator/            # DAG, gates, budget, resume, parallelism
│   ├── facts/                   # fact store, provenance, point-in-time query layer
│   └── validators/              # citation validator, number validator, schema validator
├── adapters/
│   └── india/                   # NSE/BSE, AMFI, SEBI, screener parsing, ₹cr/lakh units
├── data/
│   ├── bronze/                  # raw immutable: PDFs, HTML, filings. never edited.
│   ├── silver/                  # parsed, typed, unit-normalised parquet
│   ├── gold/                    # analysis-ready fact tables
│   └── firm.db                  # SQLite: facts, runs, predictions, lessons
├── memory/
│   ├── lessons.jsonl            # append-only: what we got wrong and why
│   ├── predictions.jsonl        # append-only: falsifiable calls with resolution dates
│   ├── calibration.db           # Brier scores per agent per claim-type
│   └── company_notes/           # persistent per-ticker running file, updated each run
├── evals/
│   ├── golden_set/              # 30 historical cases, point-in-time frozen
│   ├── rubrics/                 # how a good output is scored
│   └── run_eval.py
├── reports/                     # generated theses, versioned by run_id
└── runs/                        # full trace per run: every prompt, response, cost, timing
```

---

## 4. THE DATA LAYER

Build this **before any agent**. An agent firm on bad data is an expensive hallucination machine.

**Bronze (immutable raw):** annual reports, quarterly results, concall transcripts & audio, investor presentations, exchange filings, shareholding patterns, credit rating rationales, DRHPs, industry reports, regulatory orders, news. Store with SHA-256, source URL, fetch timestamp, `published_at`.

**Silver (parsed + normalised):** Standardised chart of accounts across companies. Every Indian-reporting quirk handled explicitly in `adapters/india/`: ₹ crore vs lakh vs million, consolidated vs standalone (**default to consolidated, flag when only standalone exists**), restated prior years, Ind-AS transition breaks, changed financial year-ends, exceptional items separated, discontinued operations.

**Gold (fact tables):** `financials`, `segments`, `shareholding`, `management_statements`, `guidance`, `capex_announcements`, `related_party`, `contingent_liabilities`, `auditor_history`, `pledges`, `insider_trades`, `bulk_block_deals`, `mf_holdings`, `fii_dii_flows`, `credit_ratings`.

**Reliability grading:** every source gets `A` (audited filing), `B` (exchange filing / rating rationale), `C` (company presentation / concall claim), `D` (media / broker note). Agents must weight by grade and are forbidden from building a core thesis pillar on grade `D` alone.

**Minimum history:** 10 years of financials where available, 12 quarters of concalls, 8 quarters of shareholding. If a company has <5 years of history, it is flagged `INSUFFICIENT_HISTORY` and routed to a separate lighter pipeline — never mixed with the main one.

---

## 5. THE AGENT ROSTER

Each agent gets a markdown file with: **Mandate** (one sentence), **Inputs** (exact fact tables), **Method** (numbered analytical steps), **Output schema** (reference to `schemas/`), **Definition of Done**, **Known failure modes**, **Forbidden behaviours**.

### Tier 1 — Top-down

**`macro_strategist`** — Where are we in the credit, capex, and earnings cycle? Rates, liquidity, INR, commodity inputs, government capex and policy vectors (PLI, import substitution, energy transition, defence indigenisation, China+1, formalisation, DPI). Output: ranked sector tailwind/headwind scores with a 3-year view and explicit falsifiers.

**`sector_analyst`** — Map the sector's value chain and locate the profit pool. Who has pricing power and why? Structural growth vs cyclical bounce — and the test that distinguishes them. Consolidation trajectory, entry barriers, regulatory dependency, import intensity. Defines the **sector-specific KPI set** that downstream agents must use (a lender is not analysed like a chemicals company; the system must know the difference).

**`screener`** — *Deterministic code, not an LLM.* Runs the full universe. Liquidity floor, mcap band, data completeness, and a first-pass factor sweep. Output: ranked candidate list with every filter's pass/fail recorded.

### Tier 2 — Company deep dive

**`business_analyst`** — What does this company actually *do*, expressed so a non-expert understands the money flow. Position in the value chain. Customer concentration. Switching costs. Where the moat is, or the honest admission that there isn't one. Includes the **National Relevance Test**: does this business sit on a structural need of a growing India (energy, manufacturing depth, credit access, healthcare, logistics, digital rails, defence, water, food supply chain)? A business with no structural tailwind can still be a good investment, but the thesis must then rest entirely on execution or re-rating and must say so explicitly.
For new-age / new-economy businesses: what is the actual product, who pays, why now, what technology or regulatory shift made this possible, and what would make it obsolete.

**`unit_economics_analyst`** — Decompose the business to its atomic profitable unit: one store, one plant, one customer, one truck, one MW, one loan, one subscription. Then: revenue per unit, contribution margin per unit, capex per unit, payback period, cohort retention, LTV/CAC (with an honest CAC — including the costs companies hide in "other expenses"), capacity utilisation, incremental margin on the next unit. **This is where most theses die and it should.** Output must include: how many units exist today, how many can plausibly exist in 7 years, and the arithmetic connecting the two to revenue.

**`financial_statement_analyst`** — Full 3-statement work across 10 years. Revenue bridge (volume / price / mix / acquisition). Margin walk. Extended DuPont. **ROIC vs WACC and, more importantly, incremental ROIC** = ΔNOPAT / ΔInvested Capital over rolling 3-year windows. Working capital cycle and its trend. Capex intensity: maintenance vs growth capex separated (companies rarely disclose this — estimate it and show the method). Cash conversion: CFO/EBITDA and FCF/PAT across a full cycle. Debt schedule, covenants, refinancing walls.

**`forensic_accountant`** — Assumes the numbers are lying until proven otherwise. Sloan accrual ratio. Beneish M-score. Altman Z (sector-adjusted). Piotroski F. Benford on reported digits. CFO/PAT persistently <0.7. Receivable and inventory days diverging from revenue. Other income as a share of PBT. Capitalised expenses trend. Related party transaction map. Auditor changes, resignations, qualifications, emphasis of matter. Promoter pledge trajectory. Contingent liabilities vs net worth. Subsidiary and associate maze. Exchange surveillance flags (GSM/ASM), SEBI orders. Frequency of equity raises and what happened to the money.
**Authority: this agent holds an absolute veto.** No other agent can overturn a forensic hard-fail.

**`management_analyst`** — The capital allocation track record is the thesis. Build a **Promise-vs-Delivery scorecard**: extract every dated, quantified management commitment from the last 12 concalls and presentations (capacity, revenue, margin, capex, timelines), then resolve each against what actually happened. Score = delivered / (delivered + missed + quietly dropped). Capital allocation history: what did they do with every rupee of retained earnings — organic capex, M&A, buybacks, dividends, debt reduction — and what was the return on each. Compensation vs performance. Promoter buying/selling. Succession. Governance: board independence, auditor tenure, subsidiary structure.

**`transcript_analyst`** — Reads 12+ quarters of concalls as a time series, not as documents. Tracks: guidance drift (the number quietly moving down over four quarters), vocabulary shift, questions that get dodged and by which executive, which analysts stopped attending, when the CFO stops giving forward numbers, changes in how they describe the same segment. Output: a quarter-by-quarter tone and disclosure-quality trace with quoted evidence and dates.

**`ownership_flows_analyst`** — Shareholding pattern deltas across 8 quarters. Which mutual funds entered/exited, at what price, sizing relative to their fund. FII/DII trajectory. Free float and its trend. Bulk and block deals with counterparty identification. Insider transactions. Concentration risk: a micro-cap where two funds hold 18% has an exit problem — quantify days-to-exit at 20% of ADV. Note where institutional *absence* is the opportunity (undiscovered) vs the warning (they looked and passed).

### Tier 3 — Judgment

**`valuation_modeler`** — Runs the compute layer, interprets the output. **Reverse DCF first**: what growth and margin is the current price already demanding? Then explicit DCF with a 3-stage fade. Earnings power value as a floor. Scenario analysis: bear / base / bull / disaster, each with a stated probability that must sum to 1. Sensitivity: 2-D tables on the two variables that actually matter (identified, not assumed). Monte Carlo on the 3–5 genuinely uncertain drivers with justified distributions. Exit multiple must be argued from comparable businesses at comparable ROIC and growth — never assumed constant.

**`thesis_synthesizer`** — Owns the §6 multibagger decomposition and the feasibility gate. Writes the thesis as: *"This returns Nx if and only if A, B, and C happen. Here is the evidence for each, here is the probability, here is what would prove me wrong."* Must state the **three most load-bearing assumptions** and what each is worth in the valuation.

**`red_team`** — Runs *after* the thesis, with access to it, and is instructed to destroy it. Must produce: the strongest bear case, the base rate of failure for this business type, the specific line items where the bull case is most fragile, a search for disconfirming evidence it must actively go find, and **explicit kill criteria** — the observable, dated events that would falsify the thesis. A thesis without kill criteria does not ship.

**`portfolio_manager`** — Position sizing under liquidity constraint (days to build/exit at 20% ADV), correlation with existing holdings, sector concentration, staged entry plan, and expectancy: `p(bull)×return(bull) + p(base)×return(base) + p(bear)×return(bear)`.

### Tier 4 — Meta

**`post_mortem`** — See §7. Runs on a schedule, not on demand.

---

## 6. THE MULTIBAGGER MATH — THE CORE GATE

Implement in `core/compute/multibagger.py`. **This is the intellectual centre of the system.**

### 6.1 Decomposition

```
Total Return = (1 + g_earnings)^n  ×  (M_exit / M_entry)  ×  (1 / dilution_factor)
```

Where `dilution_factor = (shares_exit / shares_entry)`.

### 6.2 Required earnings CAGR for a 10x over 7 years

| Re-rating (M_exit/M_entry) | Required earnings CAGR |
|---|---|
| 1.0× (no re-rating) | **38.9%** |
| 1.5× | **31.1%** |
| 2.0× | **25.8%** |
| 3.0× | **18.8%** |

The system must state which row it is underwriting **and defend the re-rating assumption separately from the growth assumption.** Most retail theses silently assume 3.0× re-rating and call it conservative.

### 6.3 The Feasibility Gate — HARD FAIL

Sustainable growth is bounded by the return on capital and the reinvestment rate:

```
g_sustainable = ROIC × Reinvestment Rate
Reinvestment Rate = (Capex − D&A + ΔWorking Capital) / NOPAT
```

Therefore, for any required growth `g`:

```
Required Reinvestment Rate = g / ROIC
```

**Gate logic:**
- If `g / ROIC > 1.0` → the company **cannot** self-fund this growth. It must raise debt or equity. The agent must then model that funding explicitly, including the dilution, and re-run the decomposition. It may not wave this away.
- If `g / ROIC > 1.0` **and** debt capacity is exhausted **and** the thesis assumes no dilution → **HARD FAIL. Thesis rejected.**
- If `g / ROIC < 0.6` → self-funding with surplus. Flag as high-quality compounding; then ask what happens to the surplus cash (capital allocation risk).

*Worked example the system should produce:* a company needs 26% earnings CAGR. ROIC is 22% → required reinvestment = 118% of NOPAT → it will dilute or lever. At ROIC 40% → required reinvestment = 65% → self-funded with 35% surplus. **Same growth, completely different investment.** This single test kills the majority of retail multibagger theses and it should be run before any deep work.

### 6.4 Runway test
`g` must be sustainable for `n` years, not one. Required: TAM sizing built bottom-up from units (§5 unit economics), current penetration, plausible terminal market share with a named competitive reason, and the capex-to-revenue ratio implying the balance sheet size at year `n`. If the implied year-7 revenue requires the company to hold 60% of its addressable market, say so.

### 6.5 Dilution drag
```
EPS growth = (1 + g_earnings) / (1 + g_shares) − 1
```
Track historical share count growth over 10 years. Serial diluters in micro-cap India are a distinct failure category — flag any company whose share count grew >6% CAGR without a matching step-up in ROIC.

### 6.6 Re-rating: must be *argued*, not assumed
Legitimate re-rating drivers, each requiring evidence: ROCE inflection, earnings quality improvement (CFO/PAT trend), debt paydown changing the equity risk profile, business mix shift toward higher-multiple revenue, cyclical→structural perception change, institutional discovery (index inclusion, first MF entry, coverage initiation), governance improvement, promoter pledge release. Absent an identified driver, the model uses `M_exit = M_entry` and the thesis must clear the 38.9% bar.

---

## 7. MEMORY AND THE RECURSIVE SELF-IMPROVEMENT LOOP

This is the part that makes the system get better instead of just getting bigger. Build it in Phase 5, but design the schemas in Phase 0.

### 7.1 Every thesis emits falsifiable predictions

`memory/predictions.jsonl`, append-only:
```json
{
  "prediction_id": "...", "run_id": "...", "ticker": "...",
  "agent": "thesis_synthesizer", "agent_version": "1.4.2",
  "claim": "Gross margin expands to >34% by Q4FY27",
  "metric": "gross_margin", "operator": ">=", "threshold": 0.34,
  "resolve_by": "2027-05-31", "probability": 0.65,
  "load_bearing": true, "evidence_fact_ids": ["...", "..."],
  "resolved": null, "outcome": null
}
```
Rules: minimum 8 predictions per thesis; at least 3 must be `load_bearing: true`; every prediction must be resolvable from a future filing without human judgment.

### 7.2 The post-mortem cycle

Runs weekly, and on every new quarterly result:
1. Resolve every prediction whose `resolve_by` has passed, from the fact store.
2. Compute **Brier score** per agent, per claim type, per sector: `mean((probability − outcome)²)`.
3. For every miss, run root-cause classification into a fixed taxonomy: `data_error` / `parsing_error` / `wrong_base_rate` / `overweighted_management_claim` / `missed_competitive_response` / `missed_capital_structure_risk` / `macro_shock` / `overconfident_prior` / `insufficient_disconfirming_search`.
4. Append a structured lesson to `memory/lessons.jsonl` with a proposed **prompt patch**.

### 7.3 Prompt evolution — with a human in the loop

A `prompt-evolution` job proposes concrete diffs to `agents/*.md` based on clustered lessons. It requires ≥3 lessons in the same root-cause category before proposing a change (prevents overfitting to one bad quarter). Every proposed diff is a git branch with the supporting lessons in the PR body. **You approve or reject.** Agent files carry semantic versions; every prediction records the agent version that made it, so you can measure whether v1.4 actually beat v1.3.

### 7.4 Persistent company memory

`memory/company_notes/{ticker}.md` — an append-only running file per company: every thesis version, every management promise and its resolution, every red flag raised and how it aged, every price/thesis divergence. On any re-run, this file is loaded first. The system should never re-learn something it already knew about a company.

### 7.5 Calibration dashboard
Track and display: Brier score trend per agent, over/under-confidence curve, hit rate by claim type, and **which agent's outputs most changed the final decision** (attribution). An agent whose output never changes a decision is dead weight — cut it.

---

## 8. THE PIPELINE — STAGES AND GATES

The gate structure is what keeps cost sane: expensive agents only see companies that survived cheap filters.

```
Stage 0  Universe build                        ~3,000 companies
Stage 1  Deterministic screen (code only)
         GATE A: liquidity, mcap band, data completeness, min history
                                                → ~400
Stage 2  Forensic quick-kill (cheap subset)
         GATE B: no hard forensic fail          → ~150
Stage 3  Sector fit + business comprehension
         GATE C: structural growth runway exists → ~60
Stage 4  Deep financials + unit economics       (expensive)
Stage 5  Management + transcripts + ownership   (expensive)
         GATE D: §6.3 FEASIBILITY MATH PASSES   → ~20
Stage 6  Valuation, scenarios, sensitivity
Stage 7  Red team
         GATE E: thesis survives bear case with kill criteria → ~8
Stage 8  Thesis synthesis + position sizing     → 3–5
Stage 9  Monitoring: predictions logged, watch triggers armed
```

**Gate rules:** every gate logs pass/fail *with reason* for every company. Rejected companies go to `data/gold/rejected/` with the reason — this becomes training data for the calibration loop, because knowing what you correctly rejected matters as much as knowing what you picked. A company rejected at Gate D is re-checked every 4 quarters; balance sheets change.

---

## 9. THE HARNESS

**Orchestration:** a plain DAG runner. Do not reach for a heavy framework in Phase 1 — you will spend more time fighting abstractions than doing analysis. If you outgrow it, LangGraph is the least-bad upgrade because state is explicit.

**Parallelism:** Tier-2 agents are independent of each other and run concurrently. Tier-3 agents are strictly sequential (`valuation → thesis → red_team → PM`) because each consumes the previous one's output. Enforce this in the DAG, not by convention.

**Budgets:** per-agent token budget and per-run cost ceiling in `config/models.yaml`. Run aborts and reports on breach. Use a cheaper model for extraction and classification, the strongest model for synthesis, red-teaming, and valuation judgment. Log cost per company per stage from day one — you will need it to decide what to cut.

**Tracing:** `runs/{run_id}/` contains every prompt sent, every response, token counts, timings, cache hits, gate decisions. A run must be fully reconstructable six months later.

**Evaluation harness (`evals/`):** assemble a **golden set of 30 Indian companies from 2015–2021** with known outcomes — 10 that became genuine multibaggers, 10 that went nowhere, 10 that blew up (fraud, dilution spiral, cyclical top mistaken for structural growth). Freeze the data at a point-in-time `as_of` date before the outcome was knowable. Run the full pipeline against each. **This is the only honest measure of whether the system works.** Score on: did it flag the blow-ups before they blew up, did it reject the compounders (false negatives are the expensive error here), and was its stated confidence calibrated. Re-run the eval after every prompt change.

**Anti-hallucination validators (blocking):**
- `citation_validator` — every number in the report maps to a `fact_id`
- `arithmetic_validator` — recomputes every ratio quoted in prose from source facts
- `consistency_validator` — cross-agent contradictions surfaced, never silently resolved
- `hedge_detector` — flags vague quantifiers ("strong growth", "healthy margins", "significant opportunity") and forces a number

---

## 10. OPEN SOURCE TO SURVEY BEFORE BUILDING

Spend the first day reading, not writing. **Instruction to Claude: search GitHub for each of these, check last-commit date and open issues, and write `docs/PRIOR_ART.md` summarising what to steal and what to avoid.** Do not fork any of them — the goal is to lift specific design patterns.

- **AI4Finance-Foundation/FinRobot** — the closest prior art. <cite index="1-1">It runs a lead agent orchestrating specialised research agents through a pipeline engine, and enforces strict separation between deterministic financial computation and LLM narration, with all valuation outputs computed through deterministic code paths with full provenance.</cite> That separation principle is Law 1 above; study their implementation.
- **TauricResearch/TradingAgents** — <cite index="5-1">multi-agent framework mirroring a real trading firm, with fundamental, sentiment and technical analysts feeding a trader and risk management team, where agents debate to reach a strategy.</cite> Steal the bull/bear debate structure; ignore the trading execution layer entirely.
- **virattt/ai-hedge-fund** — <cite index="8-1">widely-used multi-agent proof of concept with valuation, sentiment, fundamentals and technicals agents, a risk manager computing position limits, and a portfolio manager synthesising signals; trades are simulated only.</cite> Good reference for agent-to-portfolio plumbing.
- **LLMQuant/awesome-trading-agents** and **Tom-roujiang/Awesome-LLM-Quantitative-Trading-Papers** — curated indexes; use them to find anything newer than this spec.
- **Look-Ahead-Bench (arXiv)** — read this before building the eval harness. Look-ahead bias contamination is the standard failure mode of exactly this kind of system.
- **OpenBB** — data layer patterns and provider abstraction, worth studying even though its India coverage is thin.
- **India data plumbing:** `bse` (BseIndiaApi), `pnsea`, `nsepython`, `jugaad-data` for exchange data; AMFI for mutual fund holdings; BSE/NSE announcement feeds for filings and transcripts. Grade each on reliability, note which break often, and put every one behind an adapter interface so a dead library is a one-file fix.

Also note (from the same ecosystem) that a Korea-market equity research framework already ships a self-improving *analyze → verify → reflect* loop — the pattern in §7 is not exotic, it is becoming standard. Build it in.

---

## 11. BUILD ORDER — PHASES WITH ACCEPTANCE TESTS

Do not proceed to the next phase until the acceptance test passes and I have confirmed.

**Phase 0 — Skeleton and contracts (no agents)**
Repo structure, `CLAUDE.md`, config files, Pydantic schemas for all 14 agent outputs, fact store with provenance, point-in-time query layer, LLM provider abstraction with caching.
*Acceptance:* ingest one company's last 5 annual reports and 8 concalls into bronze→silver→gold; query "revenue FY24 as-of 2024-08-01" and get the right number with a citation; the same query as-of 2024-04-01 correctly returns nothing.

**Phase 1 — Compute layer**
All of `core/compute/`. Ratios, DuPont, ROIC, incremental ROIC, quality metrics, DCF, reverse DCF, scenarios, sensitivity, and §6 multibagger math.
*Acceptance:* 100% unit test coverage on `core/compute/`; hand-verify the full ratio set for 3 companies against published data; the §6.3 feasibility gate correctly rejects a synthetic company with ROIC 15% requiring 30% growth.

**Phase 2 — Three agents, deep**
`financial_statement_analyst`, `forensic_accountant`, `business_analyst` only. Full schemas, full validators.
*Acceptance:* run on 5 companies including one known accounting fraud from the golden set; the forensic agent flags it; every number in all 15 outputs passes the citation validator.

**Phase 3 — Full roster + orchestrator**
Remaining agents, DAG, gates, budgets, parallelism, tracing.
*Acceptance:* full pipeline on 50 companies end-to-end; gate funnel produces sane counts; cost per company logged; a killed run resumes correctly.

**Phase 4 — Judgment tier**
`valuation_modeler`, `thesis_synthesizer`, `red_team`, `portfolio_manager`.
*Acceptance:* a complete thesis with reverse DCF, four probability-weighted scenarios, a bear case that genuinely engages with the bull case rather than listing generic risks, and dated kill criteria.

**Phase 5 — Memory and the loop**
Predictions, post-mortem, Brier scoring, lessons, prompt evolution, company notes.
*Acceptance:* backfill predictions on 10 historical theses, resolve them, produce a calibration report, and generate one prompt patch proposal with its supporting lessons.

**Phase 6 — Evaluation**
Golden set, rubrics, `run_eval.py`, regression on every prompt change.
*Acceptance:* full eval run with a scorecard; at least 7 of 10 blow-ups flagged before their blow-up date, with false-negative rate on the compounders reported honestly.

---

## 12. HOUSE ANALYTICAL STANDARDS (`agents/_shared/house_style.md`)

Every agent inherits these:

1. **Numbers over adjectives.** "Margins improved" is banned. "EBITDA margin went 14.2% → 18.6% over FY22–FY25, driven 60% by operating leverage and 40% by mix" is required.
2. **State the base rate first.** Before claiming a company will grow 30% for 7 years, state how many Indian companies in this sector have ever done that.
3. **Say "I don't know."** An explicit `unknown` with a note on what data would resolve it beats a confident guess. Every agent output has an `open_questions` array and an empty array is suspicious.
4. **Separate observation from inference from speculation.** Three different fields in every schema. Never blend them in prose.
5. **Confidence must be numeric** and must be justified by evidence count and grade, not vibes.
6. **Disconfirming search is mandatory.** Every agent must actively look for evidence against its own emerging conclusion and record what it found or failed to find.
7. **A management claim is data about management, not data about the business.** Tag it accordingly.
8. **Cite the grade.** When a thesis pillar rests on grade C or D evidence, say so in the thesis, not in a footnote.

---

## 13. FIRST INSTRUCTION TO CLAUDE

Read this entire spec. Then:
1. Write `docs/PLAN.md` — restate the architecture in your own words, list assumptions, list open questions, flag anything in this spec you think is wrong or will not work and say why.
2. Write `docs/PRIOR_ART.md` — survey §10.
3. Propose the Phase 0 acceptance test concretely, naming the specific company you'll use.
4. **Stop. Write no code. Wait for approval.**

Do not be agreeable about the parts of this spec you think are flawed. If the gate thresholds are wrong, if the agent roster has redundancy, if a phase is mis-ordered — say so now, before anything is built.
