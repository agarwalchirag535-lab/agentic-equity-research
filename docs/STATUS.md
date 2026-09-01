# STATUS.md — project state, handoff, and what to do next

> **Read this first if you are new to this repo** (new session, new agent, new platform, or the owner
> after a break). It is the single authoritative answer to *"what is built, what is not, and what
> should happen next."* Last updated **2026-09-01**.
>
> Reading order for a cold start: this file → [`CLAUDE.md`](../CLAUDE.md) (the laws) →
> [`SPEC.md`](SPEC.md) (the constitution) → [`DECISIONS.md`](DECISIONS.md) (why things are the way they
> are, ADR-0001…0062). Keep this file updated as work lands — a stale STATUS is worse than none.

---

## 0. The mandate

**A complete, standalone, evidence-backed research report on any company the owner chooses to
analyze** (ADR-0063, owner directive 2026-09-01) — business quality, growth, financials, earnings
quality, valuation, management/governance, forensic red flags, risks, industry/peers — landing on a
verdict the evidence chain supports, positive or negative.

Within it, one section keeps its teeth: the §6 return-potential decomposition — *can this business
plausibly compound into a 5–10x over 5–8 years, self-funded, under honest management?* It is a
component of the report, **not the sole purpose of the system**. ADR-0063 lists where the old
charter's narrowness still lives in code (the verdict ladder, `choose_verdict`, the hardwired 5x/7y
target, `thesis_synthesizer`'s mandate). Output is **research artifacts only** — never an order,
never "buy this".

## 1. Where the project stands

| Phase (SPEC §11) | State |
|---|---|
| 0 — skeleton + contracts | ✅ complete |
| 1 — compute layer | ✅ complete (100% coverage enforced by `make cov`) |
| **2 — three agents, deep** | ✅ **complete — acceptance test passes; first report published (§6a)** |
| 3 — full roster + orchestrator | ✅ **complete — acceptance run published 2026-08-01 (§6b)**: 9 of 9 agents staffed and rendered, every data prerequisite satisfiable (ADR-0030–0044) |
| 4 — judgment tier | ✅ **complete 2026-09-01 (ADR-0069/0070/0071/0072)**: the valuation reaches the report, the four judgment agents narrate, Gates A–E are reported as findings (never as filters — ADR-0064), and the base FCF is normalised over a cycle. `firm ingest-prices` finally puts a grade-A close in the store |
| 5 — memory loop | 🔨 **§7.1-7.4 done 2026-09-01 (ADR-0073/0077/0079)**: `firm resolve` scores due predictions point-in-time; `firm evolve` clusters lessons into prompt proposals a human approves and scores Brier per agent VERSION; per-company memory accumulates and is filtered by `as_of` on read. **Remaining: §7.5 the calibration dashboard** (over/under-confidence curve, hit rate by claim type, and which agent's output most changed the decision — an agent that never changes one is dead weight) |
| 6 — evaluation / golden set | ⚠️ **live and biting (ADR-0061)**: 8 cases, 7 in band + CAP-EPC recorded, positives **2/2**; register spans 7 event kinds; awaiting human sign-off |

**Tests:** 961 passing · `core/compute` at **100%** (the Phase-1 gate; note `--cov-fail-under=100` scopes
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

### 0b. Substantive note coverage is 51% against a 50% floor — barely publishing
**Rewritten 2026-08-01 (ADR-0045); the old "9%" figure was stale twice over.** The merge's note
reconciliation lifted it to 64%, and then fixing the enumerator lowered it to a truer **51%**: the
parser had been blind to 14 notes (lettered sub-notes like `36a`, dotted titles like `C.I.F.`, merged
siblings `45a`/`45b`), so 64% was a share of an incomplete denominator. **The contingent-liabilities
note was among the invisible ones** — the whole hidden-liability disclosure, unread behind a 100%
coverage score.

Enumeration is now 59 notes and the report prints the numbers it still cannot locate ([10, 46, 50])
beside the coverage figure, so a blind spot can no longer hide inside a perfect score.

**This is now load-bearing, not cosmetic: at 51% against a 50% floor, one more note found stops the
report publishing.** The remaining work is unchanged in shape — note-content readers on the
`notes_content.related_party_summary` pattern — but the priority order should follow the categories that
are actually `unknown` today: `contingent_liabilities` (now visible and still unread by any check),
`tax` (3 notes), `employee_benefits`, `segment`, `leases`, and the 10 `uncategorised`.

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
8. **The report is the product, not the filter** (ADR-0063, 2026-09-01). A full standalone research
   report on any chosen company, whatever the conclusion; the 5–10x question is one section of it.
   Do not let a feasibility miss against the 5x/7y target masquerade as a negative verdict on a clean,
   fairly-priced business, and do not gate an owner-requested deep dive on the discovery universe band.
9. **Research eligibility ≠ investment verdict** (ADR-0064, 2026-09-01). A company is NEVER refused a
   report for looking bad, failing the multibagger test, or failing an investment gate — bad companies
   get investigated, not filtered. Only conclusions vary (PASS/FAIL/MIXED/INSUFFICIENT_*). Integrity
   gates police the firm's honesty and stay blocking, but the terminal failure mode for an owner-chosen
   company must be a degraded honest report (INSUFFICIENT_EVIDENCE / deterministic-only), never
   silence. Every report surfaces specific questions the owner can take directly to management.

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

## 6c. The PC Jeweller point-in-time run (2026-08-31) — first true positive, and the extraction verdict

The owner moved the project to autonomous engineering mode; the first experiment was the one the
architecture review called for: a known historical fraud, point-in-time. **PC Jeweller, `as_of
2017-12-31`** — five ARs FY13-FY17 from the BSE archive (real dissemination dates), a month before the
collapse began.

**The old extraction line failed catastrophically and quietly** (full autopsy in ADR-0046): FY13-FY15
refused wholesale (plain-rupee units unknown), FY16 gave 4 rows, and FY17 stored 25 grade-A facts **from
the Ind AS transition note instead of the balance sheet** — `Total Assets FY16 = −6.41cr` at grade A,
past the identity check (the wrong table also balances). No cash-flow statement was located in any
filing; every check returned UNAVAILABLE; the raw screen said PASS on a company twelve months from
collapse — and the published verdict would have blamed the company's disclosure for our unreadability.

**The fix is ADR-0046** — extraction is reading: a proposer (LLM or human packet, ADR-0010) locates
statements, quotes headings/columns/units verbatim, and transcribes printed values; `core/ingest/reading.py`
verifies deterministically (heading/year/basis on page · unit in vocabulary · column names its year ·
**every value found verbatim on its claimed page** · balance-sheet identity · P&L sum tie · CFS legs tie ·
magnitude plausibility) and registers only what survives. 260 grade-A facts across the five filings,
zero violations; the cross-filing quarantine (ADR-0036) then caught the one definitional break (I-GAAP
combined cash-and-bank vs Ind AS split cash, FY16) and, live, a per-share unit bug (EPS lakh-scaled to
0.21 — now `PER_SHARE_METRICS` never scales).

**The screen fired: `HARD_FAIL`** — SEVERE `cumulative_cfo_pat_low` **ΣCFO/ΣPAT 0.24** (FY12-FY17) +
HIGH `receivables_divergent` **+57.6% vs revenue +16.1%**, all inputs grade A with page locators. Two
generalisations came out of observing the run, both landed:
- **Stock-flow divergence is UNIVERSAL** (config change + ADR note in `forensic_playbooks.yaml`): the
  jewellery retailer matched no business model (inventory-heavy, PPE-light) and the receivables check
  never ran. LENDER/BANK still suppress it (ADR-0002 intact).
- **`backfill_external_inputs` in `core/pipeline/checks.py`**: checks read the point-in-time fact store
  when the filing walk did not supply their inputs — five years of audited receivables sat in the store
  while the check reported UNAVAILABLE.

**The REJECT report is published (2026-08-31, ADR-0047):** `reports/PCJEWELLER/2017-12-31-cccdf1de45b8/`
— **FORENSIC_CAUTION**, confidence 0.38, three agents narrated, zero graph/publication violations,
grade A throughout, kill/rehab criteria dated 2018-10-27 (history answered them: the collapse came
first). Getting there forced three more pattern→reading fixes, all general: era-gated mandated
disclosures (an FY17 filing was about to be charged with FY22 Schedule III rows and FY18 KAM — a false
accusation), notes + related-party enumeration through the ADR-0046 propose/verify path (52/52 notes,
100% coverage, note 37 read: no lending TO promoters), and `walk_filing(numeric_rows=False)` so the
row-locator cannot re-poison a store a verified reading populated.

**Still open from this run:** interest-income breakout (cash-yield check UNAVAILABLE, honestly); no
business model matched (a RETAIL/jewellery shape is a golden-set calibration question);
`cash_debt_paradox` reads cash-equivalents only while PCJ's encumbered-cash story lives in Other Bank
Balances (₹780cr); CARO triage is era-blind (2016 vs 2020 clause numbering); feasibility gate cannot
run without Operating Profit (compose it on the reading path); ~~prediction resolver still never invoked~~
**RESOLVED 2026-08-31 — the memory loop closed for the first time.** `resolve_due()`
(core/monitoring/resolver.py, point-in-time, idempotent, tested) scored the three PCJ predictions
against the FY18 AR (read via ADR-0046, 45 verified facts) at as-of 2018-10-27: `cum_cfo_pat >= 0.7`
**BROKEN** (actual 0.34, load-bearing), `cfo_pat_latest >= 1.62` **BROKEN** (actual 0.67 — the one
good year reversed immediately), `accrual_ratio_latest <= 0.1` **HELD** (0.02). Brier 0.224.
`memory/lessons.jsonl` now exists with the first three lessons: accrual ratios are weak kill criteria
for payables-funded frauds; per-criterion probabilities are needed (broadcasting report confidence
miscalibrates); CFS comparative restatements are a signal (FY18 restated FY17 CFO +5% and the restated
column fails the V7 tie). Also caught: the FY18 bonus issue halves comparative EPS and the quarantine
cannot distinguish that from a misread (per-share restatement handling is open).

**Lesson 2 is closed (2026-08-31): per-criterion probabilities.** `predictions_from_report` no longer
broadcasts the report confidence: P(holds) = confidence × prior + (1 − confidence)/2, where the prior
is `report.criterion_persistence_prior` (config, provisional) for a criterion its metric satisfies
TODAY (arithmetic over `computed_facts`) and its complement for one already violated; a metric absent
from the run falls back to bare confidence. Everything computed, nothing authored (Law 1). On the
resolved PCJ ledger the new rule scores Brier 0.149 vs the broadcast rule's 0.224 (regression test
asserts the improvement on the real outcomes).

**Lesson 3 is closed (2026-08-31): the restatement log is a report section.** `restatement_log()`
(core/ingest/filings.py) reads the store point-in-time — a revision published after `as_of` does not
exist yet — classifies every same-(metric, period) disagreement with the quarantine's own classifier,
and the 'restated' class renders as "Restatement log — what later filings changed"
(`ResearchReport.restatements`). Republished PCJ report
`reports/PCJEWELLER/2017-12-31-c511ee43f25b/` carries 29 rows: the FY17 filing's Ind AS transition
rewrote FY16 wholesale (Interest +12.2%, Other Expenses −11.7% — ₹30cr moved between lines), and the
FY14/FY15 filings quietly revised each other's CFO/CFF. NOTE the succession: this run supersedes
`2017-12-31-cccdf1de45b8` (same verdict; the fact set changed because the FY18 ingest's EPS quarantine
removed FY17 EPS — see the per-share open item; quarantine deletion is extraction-trust semantics, not
point-in-time semantics, which is documented and acceptable but worth remembering).

## 6d. The Symphony run (2026-08-31) — the affirm side, and three defects a fraud could not have shown

The first company chosen to test **false positives** rather than to catch a fraud: Symphony Ltd
(BSE 517385), `as_of 2018-12-31` — a genuine compounder, deliberately picked as a hard clean case
(asset-light, outsourced manufacturing, large treasury book). Full autopsy in **ADR-0048**. It found:

1. **A nine-month transition period read as a year.** Symphony moved its year-end June -> March and
   filed a 9-month stub to 31 Mar 2016, saying in its own report that the periods "are not comparable".
   The firm had no concept of period length: revenue growth reads -23.0% where it was +2.7% (as-of 2016)
   and +72.4% where it was +29.3% (as-of 2017), receivable days inflate 33%, and a 2016 run would have
   fired `receivables_divergent` **on a clean compounder**. Fixed: `ProposedColumn.months` + **V3b**
   (established from the column's words, then the heading; an unambiguous contradiction is refused), and
   registration refuses to store FLOW figures from a non-12-month period — stocks store normally, since
   *stocks are dated and flows are periodic*. Annualising was rejected as estimation. All seven prior
   readings re-verify unchanged with 12 months inferred from the filings' own words.
2. **The cost base omitted goods bought for resale.** Symphony consumes Rs 93.9cr of materials and
   *purchases* Rs 293.1cr of stock-in-trade. Inventory days read **315 against a true 75**, payable days
   231 vs 55, CCC 112 vs 48 — wrong for every outsourced-manufacturing, trading or franchise model.
   Fixed in `cogs()` + `READ_METRICS` + the V6 sum check.
3. **A cumulative ratio fired SEVERE on a two-year window.** `cumulative_cfo_pat` 0.56 over the two
   years readable from one filing -> SEVERE -> HARD_FAIL, and the ladder short-circuits *above* the
   insufficient-history rung. Any company with two readable years got a fraud flag. Fixed with
   `forensic.cumulative_cfo_pat_min_periods` (3, provisional), refused at the derivation so every
   consumer is honest at once. **Screen went HARD_FAIL -> REVIEW.**

**The honest residue:** Symphony still returns REVIEW (`cfo_pat_low` 0.55, `high_accruals` 0.126).
Probably not fraud either — ~20% of its PBT is treasury income, which the indirect-method cash flow puts
under investing, so treasury-heavy companies systematically convert below 1.0. Changing a threshold on
one observation is the overfitting the golden set exists to prevent, so it is a lesson
(`memory/lessons.jsonl`), not a code change. ~~**Also open:** Symphony's FY13-FY15 report **June**
year-ends~~ **CLOSED 2026-08-31 (ADR-0049): periods are first-class objects.** V3c reads every period
column's closing date from the filing's own verbatim quotes (refused if unstated, never assumed to be
31 March); `facts.period_end` stores it (old DBs migrate in place); CAGRs compound over the true
elapsed years when the stated closes contradict the label count (formula prints the exponent, e.g.
`^(1/2.7516)`); `resolve_by` dates criteria to the company's own next close; and a peer row whose
shared label closes on different dates for the two companies is refused with both dates named.
March-closer behaviour is byte-identical (integer exponents kept; all 8 committed readings re-verify;
verified live against the sha256-pinned Symphony FY18 PDF — 0 violations, 54/54 facts dated). A side
with no stated closes (screener-only) still compares at its grade — the capability-vs-disclosure line.
Residue in the ADR: the legacy walker doesn't date facts, rolling-3y windows still count labels,
quarters carry no close.

**And then the real documents (ADR-0050, same day):** Symphony FY13–FY17 ingested from BSE —
sha256-pinned, propose→verify→register, 280 figures verified first-pass, the nine-month transition
filing and both filings carrying its column refusing 17 stub flows each, 156/156 facts dated, every
CAGR compounding over the true 5.7496 years. `cumulative_cfo_pat` answers over six years now: PASS
0.79. Screen unchanged at REVIEW (the treasury-income calibration residue). Two new guards from the
run: a 1:1 bonus is no longer publishable as dilution (`dilution_drag` refuses when equity capital
moved >2% across the window, asking the bonus-vs-issuance question instead), and
`quarantine_store_contradictions` gives reading-path facts the cross-document control the walker had
— labelling a verified-both-sides contradiction `re_presented` rather than confessing to an
extraction error the V-checks prove we did not make. First real restatement-radar catch: 49 quiet
revisions, led by FY15 revenue 578.89 → 525.87 (₹53cr of discounts renetted).

**The parallel line's version of the same day (merged, ADR-0054).** A sibling session independently
built the end-date half — same `facts.period_end` idea, a declaration-only V3c, and a REFUSAL of every
window rate across a moved year-end. The merge (§6g) kept the trunk implementation (derive-from-words
V3c that refuses an *unestablishable* close; the CAGR exponent corrected to the true elapsed years
rather than refused) and ported the sibling's `fiscal_close_month()/.fiscal_calendar_change()` helpers
as narratable facts. Its ADRs are renumbered 0051–0053 in DECISIONS.

**The affirm answer, finally.** On the trunk's six-filing store Symphony's `cumulative_cfo_pat` reads
**0.79 (PASS)** over FY12-FY18 (the sibling's four-filing run read 0.71 over FY14-FY18) against the
**0.56 SEVERE** the two-year window gave before the floor: *HARD_FAIL -> REVIEW -> cumulative PASS*.
It still returns REVIEW on single-year `cfo_pat` 0.55 and `high_accruals` 0.126, which is the treasury
effect held for golden-set calibration rather than fixed by moving a threshold on one observation.

## 6e. The CreditAccess run (2026-08-31) — the lender path was asserted, not built

The first lender's filing the firm has ever read (CreditAccess Grameen FY25, `as_of 2025-12-31`). Full
autopsy in **ADR-0050**. The headline: `quality.py` has carried seven lender checks since ADR-0002/0012
and `VALIDATION_TIER0.md` has been cited as proof the firm handles lenders — but the **pipeline could
not read a lender at all**, broken in three independent places: no lender line items in the reading
vocabulary, `statement_shape` never computing `loan_book_to_assets` (so LENDER was undetectable however
plainly a filing said so, making the whole ADR-0002 branch unreachable), and **no evaluator for any of
the seven checks** in `checks.py`.

All three are now built. The payoff: **the pipeline independently reproduced the hand-computed
VALIDATION_TIER0 verdict** from the audited statements with no figure typed in — provision-book
divergence FLAG (impairment +327.1% vs book -3.3%, gap 3.30), reserve-suppression PASS (1.80% -> 7.95%,
raised, so correctly NOT the fraud tell), gain-on-sale UNAVAILABLE, screen **REVIEW**. LENDER detected at
a loan book **87% of assets**, and the five ADR-0002 suppressions appeared as NOT_APPLICABLE on a real
filing for the first time. The five note-level checks now name the specific note that would answer them,
so "we cannot read this yet" never reads like "the company did not disclose it".

**The defect the run found:** `cumulative_cfo_pat`/`cfo_pat` were UNIVERSAL and therefore applied to
lenders. Under Ind AS 7 loan disbursement and collection ARE a lender's operating activity, so CFO/PAT
measures BOOK GROWTH: CreditAccess reads **+2.12 in FY25 (book shrank 3.3%)** and **-3.27 in FY24 (book
grew)** — same company, same accounting, opposite verdicts — and the cumulative form is a SEVERE flag, so
**every growing lender would be flagged for growing**. Both are now suppressed for LENDER and BANK. A
lender-appropriate replacement measure is a golden-set calibration question, recorded rather than invented.

**Also worth knowing:** the verifier caught three of *my own* transcription errors (a column-label quote
absent from the page, four cash-flow rows attributed to the wrong page) before anything reached the store.

## 6f. "We could not look" is not "they did not disclose" (2026-08-31, ADR-0051)

Generalising ADR-0050 found four more unwired checks (SERVICES_IT, EPC_INFRA, REAL_ESTATE) — and then
something worse. `unavailable_share` counted every unrunnable check alike and the ladder turned it into
**INSUFFICIENT_DISCLOSURE** reasoning *"the inputs are public by law, so the gap is the finding"*. On
CreditAccess Grameen, **67% of the playbook was unavailable and 0% of it was the company's doing** — the
firm was about to accuse a compliant lender of withholding information it publishes in full. Two notes
rungs had the same defect, firing off a `NotesReview` whose `scanned` flag was False.

Fixed: `CheckRecord.gap` (defaulting to CAPABILITY — blaming ourselves is the safe direction),
`disclosure_gap_share` split from `unavailable_share`, the notes rungs gated on `scanned`, and a new
verdict **`INSUFFICIENT_EVIDENCE`** for "we could not look hard enough to judge". That last one is
load-bearing: removing the false accusation alone made the screener-only run return
`QUALITY_WRONG_PRICE` — a business judgment off 40% of a playbook — so the fix had to prevent a false
thesis as well as a false accusation. CreditAccess now reads *"67% ... for want of this firm's own reach
rather than the company's disclosure — no judgment about the business is supportable yet"*.

`tests/pipeline/test_check_coverage.py` guards the wiring class behaviourally (verified by unwiring a
lender check and watching it fail). The four unimplemented checks are **declared** in
`UNIMPLEMENTED_CHECKS`, not built: an evaluator gets wired when a company that needs it is run, so it is
validated against a document rather than an expectation.

## 6g. The second branch divergence, merged (2026-08-31, ADR-0054)

Two autonomous sessions ran the same priority function from the ADR-0048 base and independently built
first-class periods, collided on ADR numbers for the second time, and independently transcribed the
same Symphony FY15 filing. The merge kept the trunk's period machinery (stricter V3c, exponent
correction over refusal — the one analytical disagreement, argued out in ADR-0054), landed the
sibling's lender path (ADR-0052) and gap-kind verdict fix (ADR-0053) intact, and turned the double
transcription into a free audit: **48 of 50 shared figures agree to the digit**; both disagreements
were one semantic mapping (balance-sheet "Cash and Bank Balances" is NOT cash-and-cash-equivalents —
the cash-flow statement's own closing row is). Process fix, operational: **one session owns the
trunk.** All readings re-verified against their sha256-pinned PDFs under the merged verifier: 0
violations, every stored fact dated.

## 6h. Symphony published, and the CLI owns the reading path (2026-08-31, ADR-0055)

`firm read-packets` / `deep-dive --readings` / `packets --readings` now take any filings manifest to a
published report with no hand-driven Python: sha256-pinned fetch, page-text verification at ingest,
Law 3 at the document level, every non-contribution an explicit status. The acceptance run published
**`reports/SYMPHONY/2018-12-31-65e0f6068121`** — verdict FORENSIC_CAUTION off the deterministic
REVIEW (the treasury-conversion arithmetic, now the top golden-set calibration question) — and caught
three defects on the way, all fixed with tests: a hardcoded `start_year=2015` amputating ingested
history (0.64 SEVERE/HARD_FAIL manufactured against the clean company; the window now defaults to
what the evidence covers), a wrong SA 701 effective year charging compliant FY18 filers with a
disclosure gap (KAM is owed from FY19; verified against the Deloitte-audited filing, not memory), and
a citation grammar that still could not cite the space-bearing ids most audited rows carry (third
instance of that class; the delimiter is now the bracket). The discipline gates rejected four drafts
of the run's own agent answers before passing the fifth — the gate works on its own author.

## 6i. Notes are readable (2026-08-31, ADR-0056 — the sibling line's last commit, merged)

The largest remaining capability gap. Tested a cheap hypothesis first — *a note table is a table, so the
ADR-0046 verifier should already read one* — and it was mostly true: V3 (columns name their year) and V4
(the value is on the page) work unchanged. Two things do not: a note heading names a NOTE, not a period
("7 Loans" carries no year), and it never states its basis (the section does).

Both dropped tests are replaced by something stronger — **the reconciliation gate**: a note figure mapped
to a face metric must equal that metric as already stored, read from the store so the comparison is
against a figure verified independently from another page. That is ADR-0038's standard turned into a
gate, and it settles basis better than a heading could: a standalone note does not tie to the
consolidated face figure. Verified by corrupting a note to claim the gross loan figure as the net one — a
value genuinely printed on the page, so every page-level check passes it; only the face tie caught it.

**The lender family is now real.** With notes 7 and 7(A) read: `gnpa_drift` **FLAG** (Stage-3 share of
the gross book **1.18% -> 4.79%**, +3.61pp vs a 1.00pp limit) and `provision_coverage_low` **PASS**
(allowance Rs 1,308.63cr on Stage-3 gross Rs 1,225.61cr = **107%** coverage). The FY24 figure of 1.18%
**reproduces the GNPA CreditAccess discloses itself**, computed from the staging note rather than taken
from their summary — an independent corroboration of the reading. Capability gap **67% -> 50%**.

**Calibration question recorded, not acted on:** the verdict escalates to FORENSIC_CAUTION on the single
HIGH flag, while every corroborating check says honest recognition (credit-cost rate RAISED 1.80% ->
7.95%, coverage 107%). ADR-0012 encoded that distinction and the screen respects it — **the ladder reads
flags, not the pattern of flags**. That is a golden-set question, not a one-observation threshold change.


## 6j. The golden set is live on the trunk (2026-08-31, ADR-0057)

Ported from a THIRD parallel line (geometry-anchored-pdf-extraction — 11 commits, never merged; its
remainder is an owner decision). `firm eval` / `make eval`: seven cases, two assertions each
(extraction and judgment, scored apart), labels as external dated events, positives traceable to a
BSE register enumeration. First trunk run: 4/7 in band; three failures RECORDED with tracking ids —
PORT-1 (IRACP asset-quality extraction unported: both lender cases), PORT-2 (PCJ FY19-21 unreadable
by the trunk row-locator), EVAL-1 (the bare screen returns PASS on an empty read; only the ladder
refuses). All 17 case PDFs re-fetched against their sha256 pins; five stub source_urls repaired with
URLs that reproduce the pins. `deterministic.py` now holds the ONE deterministic sequence the eval
replays — the same one deep-dive and packets should be refactored onto (their ADR-0060 lesson).

## 6k. The diagnostic pass (2026-08-31, ADR-0058)

One loop per failure, bands untouched: EVAL-1 fixed at the screen itself (INSUFFICIENT on zero-ran
and on a sub-25% ran-share — it converted PC Jeweller's false PASS and CreditAccess's false
HARD_FAIL in one move); PC Jeweller FY19-21 verified readings (198 figures) put the positive case in
band — HARD_FAIL from primary sources on the pre-collapse pattern; CreditAccess FY26 authored through
the reconciliation gate and three judgment defects rooted out (reserve_suppression got the stress
direction its spec always needed; a regex category can no longer be a SEVERE accusation; ageing
schedules are owed only for face rows the company carries). Scorecard 5/7, positives 1/1,
hard_recovery 1/1, 0 regressions. The lesson: every judgment failure was a missing INPUT, not a wrong
threshold. Open: CAL-1, PORT-1b, and human sign-off on all seven cases.

## 6l. CAL-1 closes, and not by moving a number (2026-08-31, ADR-0059)

The set's one calibration failure looked like a threshold argument. Measuring the whole FY19–FY26
series instead of the failing year showed it was not: `cash_interest_inconsistent` divides a year of
interest by the MEAN of two balance-sheet endpoints, and Alkyl Amines' cash fell 71% during FY23, so
the same two endpoints support 1.64% and 5.64% equally. A rate over an average balance is now carried
as the band its endpoints support (`quality.FlowOverStock`), and a threshold claim is asserted only
where every timing story in that band agrees with it — `cash_yield_floor_ratio` untouched at 0.40.

**The uncomfortable half, which is the real result.** 11 of the 12 company-years the firm can read
have bands too wide to test any floor, and the set's one positive (PC Jeweller: 5.34% / 5.38% / 4.23%)
never approached it. The check fired exactly once in twelve years — on the clean company. The floor is
not vindicated; it is **untestable from annual filings alone**. Closing that needs Reg 33 half-yearly
balance sheets or the cash-and-bank note's current-account/term-deposit split — a capability item with
a named remedy, now printed in the check's own UNAVAILABLE reason.

**The second defect the same run exposed** was the standing directive's forbidden move, live on a real
company: Alkyl FY23 carried `disclosure_gap` FLAG MEDIUM reading *"mandated disclosures absent:
balance_sheet:Total Assets ..."* — our row-locator missing a total the page prints, and which the
firm had already recovered from the balancing line. `ExternalInputs.disclosure_gaps` (theirs, may move
a verdict) is now split from `extraction_gaps` (ours, named and never charged). CreditAccess's real
`undisclosed_income` gap still flags, which is the control.

Scorecard **6/7 in band, 0 regressions, positives 1/1**; 836 tests, `core/compute` 100%. Open:
PORT-1b (Five-Star readings unauthored) and human sign-off on all seven cases.

## 6m. Five-Star reads, the set goes fully green, and two checks get honest names (2026-08-31, ADR-0060)

PORT-1b's extraction half closed the only way it could: FY25/FY26 verified readings authored through
the propose→verify gate (148 figures + the security split, 0 violations first pass), the case re-keyed
to the trunk vocabulary, and the golden set's first **7/7 in band** run — `gnpa_drift` firing HIGH on
the real deterioration (Stage-3 1.79% → 3.37%) with the screen at REVIEW, both exactly as
pre-registered. Two findings mattered more than the score:

1. **The coverage check passed for the wrong reason.** It computes whole-book allowance / Stage-3
   gross (never below 55% on any readable lender-year; CreditAccess reads 121%), not the stage-3 PCR
   the case argued about (Five-Star: 54.3% → 51.3% → 41.4%, on a 99.98%-secured book). Recorded as
   **CAL-2**; the detail now names its measure and reports the PCR + secured share non-load-bearing.
   Nothing rewired: the floor waits for a lender positive (wave 3).
2. **Three false disclosure charges, each one character wide.** The Schedule III scan reported CWIP
   ageing, payables ageing and the ratios table absent from a filing that prints all three — as "CWIP
   aging schedule", "Trade payables (Ageing Schedule)" and "Debt/Equity Ratio". The scan now
   canonicalises typography before charging anyone; the CreditAccess control (which prints the same
   tables findably) is what killed the tempting wrong theory that Division III exempts them.

Open: human sign-off on all seven cases — now with nothing red behind it.

## 6n. Wave 3 — the register grows teeth and Gayatri Projects meets the pipeline cold (2026-08-31, ADR-0061)

The twenty largest auditor-resignation candidates' letters were read and durably recorded
(`_letters_read.jsonl`): yield ~1 adverse in 20. So the register was extended to the streams where the
company confesses the event itself — loan/NCD payment defaults and CIRP updates, in BSE's own verbatim
vocabulary — after fixing three silent enumeration defects measured live (page-1 sampling, no retry,
and BSE returning PARTIAL pages under sustained load: enumeration is now two passes unioned). `firm
triage` commits the previously-manual universe filter, with today's-mcap bias named in every floor
exclusion. 265 new company-events → 50 candidates.

**GAYATRI-FY18** — the set's second positive, first EPC: selected by size rank from the loan_default
stream, de-censored per-scrip to the first confession (2020-01-31; default date 31.12.2019; a 12-bank
consortium; an FITL among the defaulted facilities), pre-registered at as_of 2019-01-31, and run COLD.
Screen REVIEW — in band, the firm did not clear it — but for reasons carrying little of the real
signal: the walker missed the FY18 balance sheet and cash flow entirely (5 of 6 verified facts
unreproduced), and every EPC-geometry check the FY18 filing itself confesses against (₹713.8cr of
advances for works never commenced, per the auditor's own Emphasis of Matter) is declared-unwired.
Both halves recorded as CAP-EPC. Bonus find: the FY17 and FY18 ARs disagree by ₹95.7cr on FY17
receivables — a quiet Ind AS-transition re-presentation the walker read faithfully.

Next for this thread: author GAYATRI FY17/FY18 verified readings; wire the EPC playbook from those
documents (ADR-0051 rule); OCR the Sheela Foam letter; historical-mcap triage.

## 6o. Phase 4 opens — a citable price, and a valuation that argues with it (2026-09-01, ADR-0062)

The owner approved Phase 4 and asked whether the project's API needs could be met for free. Answered
from the code, not a vendor list: the LLM half was already solved (`ClaudeCodeAdapter` — no API key,
no per-token billing — plus the ADR-0010 packet flow), and the price half is served by **BSE's own
settled daily closes** (`StockReachGraph?flag=1`, no key, 2,139 closes back to 2018). That matters
beyond money: `sourcing.py` grades an aggregator B, and a grade-B price would undermine every number
downstream of it. The exchange's own close is grade A.

Built and validated on real companies:
- `adapters/india/prices.py` + `core/ingest/prices.py` — `close_on_or_before` is the ONLY accessor
  (a price series is the easiest place in the system to leak the future); registers `market:Close` and
  `market:ADV`, the latter finally giving SPEC §8's Gate A liquidity floor a number to apply to.
- `core/pipeline/valuation.py` — reverse DCF first, a scenario grid anchored to the company's OWN
  realised growth (never a house grid), return multiples as intrinsic value over the quoted price with
  no exit multiple anywhere, and every missing input NAMED rather than defaulted.
- Law 1 tightened, not loosened: the valuation's numbers become `Derivation`s so the existing validator
  polices them, and `ScenarioLine.return_multiple` moved out of the judgment allowlist into a new
  `NESTED_COMPUTED_FIELDS` bucket checked item-by-item against the priced grid.

**ALKYLAMINE, as of 2026-08-30:** price ₹2,044.40, 5.11cr shares (the filing's own PAT/EPS identity),
market cap ₹10,454cr, net cash ₹202cr, base FCF ₹110cr — **the price demands 34.1% FCF growth for ten
years against 5.2% realised.** PC Jeweller returns `unavailable` with all four gaps named. Golden set
8 cases, **0 regressions**, positives 2/2; 864 tests, compute 100%.

**Remaining for Phase 4 acceptance:** wire the four judgment agents to narrate, render the valuation
section, gate D/E, and normalise the base FCF (a single trough year currently flatters the bear case —
the fix is the missing input, per ADR-0059, not a nudged discount rate).

## 6p. The publication ladder closes the completeness hole (2026-09-01, ADR-0065)

The first code to land under the broadened mandate, and it came straight out of ADR-0064's own audit:
`run_deep_dive` wrote nothing when a publication gate (P1-P4) or a graph invariant (R1-R6) refused the
report, so "research this company" could answer with silence. No gate was relaxed to fix it. Instead a
four-rung ladder publishes something the gates already accept — supplement the missing sections,
withhold the verdict, fall to a deterministic floor — with a fifth rung that writes the floor anyway,
naming its own failed gates, because an artifact that admits its limits beats no artifact.

The piece that made it possible is `core/report/narration.py`: **the narration the firm can write with
no agent at all.** P2 demands a thesis, an anti-thesis and open questions, all previously agent-authored,
so an empty floor would have failed the gate it existed to satisfy. The deterministic layer now authors
all three from the check evaluation, the screen, the notes and the interrogation — and its open
questions are already phrased as **questions for management**, split from the firm's own extractor
backlog per ADR-0051. That is the seed of the standing questions-for-management deliverable.

Two invariants are pinned by tests because a careless later change would break them: **degrading never
launders a red flag** (every rung reassembles from the same deterministic checklist, so FLAGs, the
anti-thesis and the replication notes survive at every level), and **the verdict never improves**.
877 tests, compute still 100%.

## 6q. The mandate lands in code — four commits (2026-09-01, ADR-0066/0067/0068)

ADR-0063/0064 broadened the mandate on paper; these closed the gap between the paper and the code. In
order, and each with the flag it retires:

* **Questions for management (ADR-0066)** — a first-class report field, computed on EVERY report from
  the checks that flagged, the checks the filings could not feed, the high-severity line-item questions
  the sources did not answer, and the mandated disclosures the notes walker could not find. Each entry
  carries why it matters, what would answer it, and the check that raised it. Deterministic: an agent
  can neither add a question nor drop one. Only the COMPANY's gaps go to the company (ADR-0051).
* **The four-outcome headline (ADR-0067)** — `Outcome` = PASS / MIXED / FAIL / INSUFFICIENT_EVIDENCE,
  computed from the verdict so the two cannot disagree. `POSITIVE_VERDICTS` had one member, so a clean,
  fairly-priced business that could not compound 5x published as a negative alongside a forensic
  caution. MIXED is now first-class. `Verdict` is unchanged and still load-bearing.
* **Return potential as a section (ADR-0068)** — `render.py` had NO feasibility output at all: SPEC's
  "intellectual centre of the system" reached the reader only through a verdict rationale. The section
  now prints the target, the earnings CAGR it demands, ROIC, the required reinvestment and the gate
  verdict — and prints them even when the gate could not run, naming ROIC as the blocking input. The
  target is a per-run parameter (`--target-multiple` / `--target-years`), defaulting to 5x/7y.

**Known, deliberately unpaid:** `make lint` is red on trunk with ~180 ruff findings, nearly all
version drift (UP035/ISC004/RUF022 — rules that postdate the code). The non-style findings among them
were fixed (`899ebde`: two undefined names in annotations, a dead assignment, stale suppressions); the
mechanical 70-file reformat is left for the owner to schedule. Also unpaid by choice:
`QUALITY_WRONG_PRICE` is named for a price test it does not perform (it fires on the feasibility gate)
— worth renaming when the ladder is next opened for Phase 4, not before.

## 7. Suggested next step

Updated 2026-08-31, in order (the 2026-08-01 list is superseded — the PC Jeweller run reset priorities):

1. **Publish the PC Jeweller REJECT report** — take the verified facts through `run_deep_dive` with
   narration to a published dual-verdict FAIL report; this exercises the verdict ladder + publication
   gates on a HARD_FAIL for the first time and seeds the golden set (n=1).
2. **Wire ADR-0046 reading into the CLI** (`firm read-packets` / `deep-dive --readings`) so the packet
   path works for any company without driving Python by hand; then a compounder and a boring company
   point-in-time (golden set n=3, three business shapes).
3. **Note-level reads for PCJ-class inputs** (interest income on cash, Schedule III promoter rows) via
   the same propose/verify pattern — NOT more hand-coded note parsers.
4. ~~Re-run ALKYLAMINE through the reading path and diff against the walker's facts~~ **DONE
   2026-08-31 — the two extraction lines cross-validate.** The FY26 AR read via ADR-0046 (60 figures,
   3/3 statements verified, zero violations; sha256-verified re-download): **9/9 exact agreement** with
   every walker fact this store holds for that document, including the composed trade-payables total,
   and zero disagreements on the FY25 comparative against the FY25 filing's own facts (two documents,
   two extractors, same figures). The reading added 49 facts this worktree's store lacked (this DB
   carries the pre-ADR-0037 walker era — the whole-filing extraction lived on the sibling branch's
   gitignored DB), lifting 15 derived metrics to grade A here. Payables' Schedule III micro/other split
   is now a composed total like borrowings. The walker's numeric write path can be retired for any
   company a reading covers (`walk_numeric_rows=False`); its notes/CARO/section scanning remains.
   NOTE: the published 2026-07-31 ALKYLAMINE report in this worktree predates these facts — a re-run
   would need fresh agent answers and would now rest on grade-A rows.

The old list, for reference:

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
