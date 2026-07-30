# DECISIONS.md — Architecture Decision Record log

Append-only. Each entry: context → decision → consequences. Newest last.

---

### ADR-0001 — Python lives under `src/firm/`; content stays at repo root
**Context.** SPEC Law 6 mandates `python -m firm run`, but SPEC §3 placed `core/`, `adapters/`,
`schemas/` at the repo root with no `firm` package — the documented entrypoint could not resolve.
**Decision.** All importable Python moves under `src/firm/`. Non-code content (`agents/` markdown,
`config/` yaml, `docs/`, `data/`, `memory/`, `evals/`, `reports/`, `runs/`) stays at repo root.
`pyproject.toml` sets `pythonpath=["src"]` and a `firm` console script.
**Consequences.** `python -m firm` and `firm` both work; a clean split between code and content; the
100%-coverage gate targets `firm.core.compute` unambiguously.

---

### ADR-0002 — Forensic models branch by sector; financials get lender-specific checks
**Context.** SPEC's `forensic_accountant` applies Beneish M-score, Piotroski F, and conventional
accruals to the entire universe, but the universe includes banks/NBFCs/insurers. Those models assume
gross margin, inventory, and a non-financial accrual structure that lenders don't have. Literature
confirms the M-score loses reliability for financial-sector firms.
**Decision.** `core/compute/quality.py` reads a `sector_class` (`FINANCIAL` vs `NON_FINANCIAL`) and
suppresses inapplicable models for financials, substituting GNPA/NNPA drift, provision coverage,
restructured-book, and slippage checks. `config/sectors.yaml` maps sectors to `sector_class`.
**Consequences.** No false forensic verdicts on banks; a second, smaller lender-forensic path to build.

---

### ADR-0003 — Benford's Law is demoted to a non-load-bearing flag
**Context.** SPEC §5 lists Benford among forensic tools. Benford requires large transaction-level
datasets; a company's ~50–200 reported, largely-derived summary numbers violate its assumptions and
produce false positives.
**Decision.** Benford stays available as an optional **grade-F** signal that can never, alone, trigger
a forensic veto or a hard fail. It is excluded from the deterministic Gate-B kill set.
**Consequences.** Fewer false alarms; the veto rests on stronger signals (accruals, CFO/PAT, M-score).

---

### ADR-0004 — Homes for monitoring, evolution, and the deterministic screener
**Context.** Stage 9 monitoring, the weekly post-mortem, prediction resolution, and the
`prompt-evolution` job (SPEC §7) had no directory; the `screener` is code but sat among LLM agents.
**Decision.** Add `core/monitoring/` (prediction resolver, watch triggers, Brier scoring),
`core/evolution/` (clustered-lessons → agent-diff proposals), and `core/screen/` (deterministic
universe screen). `screener` is NOT an `agents/*.md` file.
**Consequences.** Every referenced job has an owner; the 14 agent count in SPEC §11 is unchanged.

---

### ADR-0005 — Gate B is deterministic (no LLM in the quick-kill)
**Context.** SPEC §8 Gate B ("forensic quick-kill") on ~400 companies risked being an LLM call.
**Decision.** Gate B uses only `core/compute/quality.py` (pure math). The LLM `forensic_accountant`
runs later, at Stage 4/5, on ~150 survivors, for narrative/related-party/auditor work.
**Consequences.** Order-of-magnitude cheaper filtering; clean Law-1 boundary.

---

### ADR-0006 — Add "cash-reality" forensic checks
**Context.** The project owner's primary interest: catching companies where the cash isn't real and
the cash-flow statement contradicts the P&L. SPEC has CFO/PAT<0.7 and contingent-liability checks but
lacks the sharpest "is the cash there?" tests.
**Decision.** `quality.py` adds: cash-vs-interest-income consistency, simultaneous high-cash +
high-cost-debt, multi-year cumulative CFO/PAT, and ageing-CWIP checks. Thresholds in
`config/thresholds.yaml`.
**Consequences.** Directly detects the fraud pattern the firm most cares about; needs a risk-free /
cost-of-debt reference (see PLAN OQ#3).

---

### ADR-0007 — Institutional signals are quality-weighted, not binary
**Context.** SPEC's `ownership_flows_analyst` tracks which funds enter/exit but treats all entries
alike.
**Decision.** Weight an entry by the fund's historical small-cap track record and its size relative to
its own fund. "Smart money entered" becomes a scored input to the thesis, and institutional *absence*
is explicitly disambiguated (undiscovered opportunity vs. looked-and-passed).
**Consequences.** A track-record data set per fund is now a Phase-5 dependency.

---

### ADR-0011 — Primary audited documents (grade A) are ingested; screener is a grade-B cross-check
**Context.** Screener (ADR-0009) gives fast summary tables, but real analysis — and *especially* the
forensic work — lives in the primary sources: the auditor's report, key audit matters, related-party
transactions, contingent liabilities, notes to accounts, MD&A, and concall transcripts. Numbers alone
don't reveal fraud; the notes do. These are public by law (company site + BSE/NSE).
**Decision.** `adapters/india/filings.py` fetches the audited annual-report PDF (and concalls, same
mechanism) → bronze; extracts text (pypdf) → silver; and locates the forensic-critical sections
(`forensic_sections`: auditor opinion, qualified/emphasis, KAM, related-party, contingent liabilities,
auditor resignation). The annual report is **grade A**; concall transcripts **grade C**; screener stays
as the grade-B quantitative cross-check. The forensic_accountant reads primary source, not an aggregator.
Also added common-size statement analysis (deterministic) for statement-level deep dives.
**Proven:** pulled Alkyl Amines' FY2025-26 audited AR (137pp, filed 2026-06-09) from NSE archives and
extracted a clean read — unqualified opinion, no auditor resignation, arm's-length RPTs, litigation the
sole KAM, routine contingent liabilities — which **confirmed** the deterministic screen. Written into
`reports/ALKYLAMINE.md`.
**Caveat.** PDF *table* extraction (exact contingent-liability figures, segment tables) is noisy with
pypdf; qualitative sections extract cleanly. Structured numeric extraction from AR tables (and OCR for
scanned filings) is future work; screener remains the numeric source until then.

---

### ADR-0010 — Claude Code (subscription) is the agent runtime; no API key required
**Context.** The owner has no LLM API key and works on a Claude Code Pro plan. The spec assumed agents
call a paid API (`AnthropicAdapter`/`OpenAIAdapter`). That is neither available nor necessary.
**Decision.** The firm's Law-1 split (deterministic compute vs LLM narration) means the narration can
come from Claude Code itself. Two runtimes, both keyless:
1. **`ClaudeCodeAdapter`** (`core/llm/provider.py`) — shells out to the headless `claude -p` CLI on the
   subscription. Use when running inside a Claude Code terminal. Subprocess runner is injectable → unit
   tested without the CLI. `config/models.yaml` provider defaults to `claude_code`.
2. **Claude-in-the-loop** — the pipeline computes everything deterministically and emits an agent
   *prompt packet* (`core/agents/packet.py`: house style + agent mandate + computed facts + schema);
   Claude Code answers in-conversation and the output is schema-validated. This is what produced the
   first real artifact: `reports/RELIANCE.md` / `.json` — three agent outputs (financial, forensic,
   thesis) grounded in live FY26 screener data, each validated against its Pydantic schema (Law 4).
**Consequences.** Zero marginal cost on the Pro plan; subject to subscription rate limits (fine for a
handful of companies, not a 3,000-name batch). The paid adapters remain for anyone who later wants
unattended batch runs. Numbers still come only from `core/compute` (Law 1) regardless of runtime.

---

### ADR-0009 — screener.in is the primary fundamentals source; broker API for market data
**Context.** The project owner has no data and directed us to pull from public sources (screener,
moneycontrol, BSE/NSE), with a broker API available. Probed live: screener.in serves the full 10-year
consolidated P&L / balance sheet / cash flow / quarterly / shareholding / ratios **without login**
(verified — parsed 336 facts for RELIANCE end-to-end). NSE's direct API blocks non-browser requests.
**Decision.**
- **Fundamentals (10-yr financials + shareholding): screener.in**, graded **B** (aggregator of audited
  filings; provenance points to screener, ideally cross-checked against the primary AR at grade A).
  Implemented in `adapters/india/screener.py` (pure parser tested against a saved HTML fixture; live
  `fetch` separated out; SSL via certifi).
- **Prices / liquidity / corporate actions: a broker API or `jugaad-data`/`bse`** — best for the
  market-data side (ADV, mcap, GSM/ASM). A broker API does **not** provide deep financials or concalls.
- **Concalls / annual-report PDFs: BSE/NSE announcement feeds + IR pages** (later).
**Point-in-time caveat (Law 3).** screener is a *current snapshot* — honest for as-of=today (all shown
data predates today), NOT for historical eval (Phase 6), which needs archived filings. Stated in
`docs/PLAN.md` §9.
**ToS caveat.** Automated access to screener/moneycontrol may be restricted by their terms; usage is for
the owner's personal research, behind an adapter, with caching and rate limits. A paid data licence or
the broker API is the clean path if this scales.
**Consequences.** A working live fundamentals pipeline today; the broker choice + key is still needed for
the market-data adapter (owner sets the key in `.env` — Claude never handles it).

---

### ADR-0008 — Short-history companies get a real "emerging" pipeline, not a black hole
**Context.** SPEC routes companies with <5 years of history to `INSUFFICIENT_HISTORY` and a "separate
lighter pipeline" that SPEC never designs. For a *multibagger discovery* engine that is a serious blind
spot: recent IPOs and new-age businesses — where much future compounding hides — would effectively be
unseen. The project owner explicitly flagged this: "some listed companies don't have enough track record
but may have a good business for the future — will you not see them?"
**Decision.** Companies are **routed, never dropped**. `core/screen/pipeline.py` classifies each into
`MAIN` (≥ `min_history_years`) or `EMERGING` (< `min_history_years`). EMERGING is a first-class,
cheaper track that produces a real thesis with kill criteria, but changes method:
- **Suppress multi-year-trend forensics** (10-yr accrual trends, decade cumulative CFO/PAT) — no data.
  **Keep point-in-time cash-reality checks** (cash-vs-interest, cash+debt paradox) — those read a single
  balance sheet and work fine (ADR-0006).
- **Lean on** the DRHP/IPO prospectus (grade A), unit economics + cohorts (SPEC §5), bottom-up TAM,
  promoter/management track record **in their other ventures**, anchor / pre-IPO institutional quality,
  and the §6.3 feasibility gate using whatever ROIC exists (even 2–3 yrs).
- **Wider confidence intervals**, and the thesis must state "short history — execution/re-rating
  dependent" explicitly (house style).
- **Own gate thresholds** (`config` `emerging` block) — cannot demand 10-yr history or 12 concalls.
- **Graduates to MAIN** automatically once history reaches `min_history_years`; re-checked every quarter.
**Consequences.** No good young business is silently excluded; a second, lighter agent path and an
`emerging` threshold set to build; the DRHP becomes a required grade-A source for this track
(DATA_SOURCES).

---

### ADR-0012 — Originate-to-sell forensic checks apply by business model, not by sector label
**Context.** Reverse-engineering two short-seller reports (`docs/FORENSIC_METHODOLOGY.md`) showed the
frauds hid in a *lender* profile even when the issuer called itself something else: Carvana ("a used-car
dealer") was, per its own former directors, "more of a subprime finance business than a car dealership."
The firm's forensic branch keyed everything off a coarse `FINANCIAL` / `NON_FINANCIAL` label (ADR-0002),
which would apply lender checks to Carvana's NON_FINANCIAL label — i.e. never.
**Decision.** Added a third forensic category in `core/compute/quality.py` — **originate-to-sell /
lender earnings-quality checks** — that fires whenever the *inputs are present* (a loan/receivable book,
loan-sale gains, provisions), regardless of `sector_class`. Checks: `gain_on_sale_reliance` (Carvana:
gain-on-loan-sale = 2.2× net income), `provision_book_divergence` (Sezzle: provisions +130% on a +6%
book), `reserve_suppression_flag` (Sezzle: provision rate cut 3.5%→1.2% to manufacture profit),
`held_for_sale_reserve_flag` (Carvana: growing on-book loans with ~zero CECL reserve). Thresholds in
`config/thresholds.yaml` → `originate_to_sell`. These apply in `forensic_screen` unconditionally.
**Consequences.** A "dealer" that is really a lender is no longer invisible to the lender checks.
Two HIGH originate-to-sell flags hard-fail (the Carvana/Sezzle profile). Validated live on real
primary-source data (`docs/VALIDATION_TIER0.md`): PASS on Bajaj Finance, REVIEW on CreditAccess Grameen's
FY25 stress — no false positive, and the reserve-suppression check correctly stayed off for a conservative
provisioner. 100% compute coverage retained.

---

### ADR-0013 — Exogenous-series divergence scanner (the P1 generative engine)
**Context.** Both reports' hypotheses were generated the same way (`FORENSIC_METHODOLOGY.md` §3 P1): a
reported metric moving *confidently against* the exogenous force that should drive it — Carvana's
gross-profit-per-unit +209% while the Manheim used-car index fell 20.3%; Sezzle's revenue +71% while its
own merchant and customer counts fell. Exogenous forces are not issuer-manipulable, so a decoupling is
either a genuine edge or an artifact, and the base rate favours artifact. The firm had no such detector.
**Decision.** Added `core/compute/divergence.py` (pure stdlib, no numpy — the compute layer keeps zero
third-party runtime deps so it stays trivially offline-testable): `realized_correlation`,
`divergence_flag` (flags a metric that is *confidently, |corr|≥threshold* correlated in the *wrong*
direction with its driver), and `cochange_divergence` (two-point sign check for start/end readings).
Threshold in `config/thresholds.yaml` → `divergence.min_abs_correlation`. Needs an exogenous-series
source (`config/exogenous.yaml`, PLAN follow-up).
**Consequences.** The cheapest, highest-value forensic add and fully deterministic (Law 1). Correctly
flags the Carvana GPU-vs-Manheim divergence in a back-test against the source report. 100% covered.

---

### ADR-0014 — Missing legally-public disclosure is a signal, never a silent skip
**Context.** Project-owner directive: for a listed company, all mandated data is public by law; when an
agent cannot find it, the historical failure mode was silently prioritising a secondary/aggregator source
or leaving a blank — masking the real question, "why is this not disclosed / what is being hidden?"
**Decision.** Added `disclosure_completeness(required, present)` to `core/compute/quality.py` (returns the
missing fields + a flag) and a `disclosure_gap` signal in `ForensicMetrics`/`forensic_screen` (MEDIUM →
REVIEW). Ingestion adapters must pass the set of *found* mandatory disclosures so an unexplained gap
surfaces as a flag rather than a blank. Live test underscored the plumbing risk: primary-filing PDFs are
often image/dynamic-render and not cleanly text-extractable, so the ingestion layer needs OCR / direct
PDF parsing or it will silently fall back to secondary sources — the exact failure this ADR guards against
(`docs/VALIDATION_TIER0.md`).
**Consequences.** Opacity becomes an explicit, gradable forensic input. A follow-up is required on the
`adapters/` side (OCR / robust PDF parsing) so "unavailable" reflects genuine non-disclosure, not a
parser giving up.

---

### ADR-0015 — Harden primary-source ingestion (OCR fallback, primary-first policy, disclosure-gap wiring)
**Context.** The live validation (`docs/VALIDATION_TIER0.md`) reproduced the owner's #1 pain: primary
filings (Bajaj Finance, CreditAccess investor decks) are image/dynamic-render PDFs whose text layer is
near-empty, so a naive `extract_text` returns almost nothing — and an agent then silently substitutes a
*secondary* source. ADR-0014 flagged this as the plumbing to fix under Track 1.
**Decision.** Three market-agnostic additions (all pure/injectable, 100%-tested offline):
1. `adapters/base/extract.py` — `extract_document()` detects a text-poor PDF (chars/page below a floor),
   falls back to an injectable `OcrBackend` (per-page merge: keep good text-layer pages, OCR the image
   ones), and when still unreadable returns `complete=False` — an explicit **signal**, never a silent
   blank. Real Tesseract backend in `adapters/base/ocr_tesseract.py` (optional extras, pragma-no-cover).
2. `adapters/base/sourcing.py` — `resolve_primary_first()` prefers the most-primary grade (A>B>C>D) among
   sources for the *same* fact, and `assess_sourcing()` raises `secondary_only=True` when a fact rests
   only on an aggregator/media where a primary should exist. Screener stays a grade-B *cross-check*,
   never the source of record for a claim that has an audited primary.
3. `adapters/india/filings.disclosure_gaps()` bridges the AR section-finder to the Track-0
   `disclosure_completeness` check: a missing mandated section (auditor opinion, related-party, contingent
   liabilities, KAM) flags `disclosure_gap` — whether from non-disclosure or an unreadable filing.
**Consequences.** An unreadable or under-sourced primary filing now surfaces as a flag, closing the
silent-fallback hole. **Still open (the hard part):** provenance-locked *numeric* extraction from AR
tables — binding each figure to `(doc_id, page)` — remains noisy (ADR-0011); scaffolding is in place
(page-level text), robust table→(label, value, page) parsing is the next Track-1 piece.

---

### ADR-0016 — Dual-verdict publishing: the firm publishes on PASS as well as FAIL
**Context.** Owner directive (2026-07-30): the product is the firm's own professional report line —
published when a company passes ("good fundamentals, good management, here is the thesis") just as much
as when red flags are found. The reference short-seller reports were method examples only; a
fraud-only publisher was never the goal, and the SPEC's output (thesis + kill criteria) already implied
positive artifacts.
**Decision.** `docs/REPORT_ARCHITECTURE.md` defines the publishable report: a five-class verdict taxonomy
(`COMPOUNDER` / `QUALITY_WRONG_PRICE` / `WATCH` / `FORENSIC_CAUTION` / `INSUFFICIENT_DISCLOSURE`), a fixed
11-section structure, and symmetric standards — positive reports must show the **Verified-Clean Checklist**
(every check run, passes included; a clean verdict with an invisible process is worthless) and carry kill
criteria; negative reports must carry **rehabilitation criteria** and the bull rebuttal. Same validators,
same evidence-graph invariants, same red-team, both directions. Never "buy"/"sell" (SPEC §1 unchanged).
**Consequences.** Publication gates gain three validators (verified-clean completeness, symmetry, legal
framing). Published verdicts feed predictions → Brier scoring, making the firm's public calibration part
of the memory loop. The gate funnel still decides *whether* a full report exists (Gates A–C exits get a
one-line record, not a report).

---

### ADR-0017 — Business-model-adaptive forensics + enforceable line-by-line note coverage
**Context.** Owner directive (2026-07-30): n companies, n business structures — the system must adapt its
investigation to the structure it is reading, and must read statements and notes-to-accounts line by
line, not by keyword windows. Current state: checks are model-aware for lenders only (ADR-0002/0012),
and `filings.py` spot-checks six sections. Calibration evidence so far is n=2 US lender-shaped reports —
a generalisation risk if left as-is.
**Decision.** `docs/ADAPTIVE_FORENSICS.md`: (1) deterministic **business-model detection** from statement
shape (loan book, contract assets, inventory intensity, gross-vs-net pattern…) → model tags →
config-driven **playbooks** (which checks apply/suppress per model + model-specific checks) across 10
initial models (manufacturer, lender, bank, EPC, retail/jewellery, trader, IT, pharma, real estate,
platform); conglomerates = union of playbooks. (2) The **notes-walker**: enumerate every numbered note,
classify against a fixed taxonomy (incl. Schedule III 2021 mandatory disclosures — struck-off-company
transactions, CWIP/receivable ageing, benami, wilful-default), force a `{clean, flag, unknown}`
**disposition per note** with figures bound to (doc_id, page); a report cannot publish below 100% note
coverage. (3) **CARO 2020 clause parsing** — any adverse clause auto-flags with the clause quoted.
**Consequences.** Universal checks SPEC named but never coded (receivable/inventory-days divergence,
other-income share, gross-vs-net) become the next compute work; numeric table extraction (ADR-0015
remainder) becomes a hard prerequisite for the notes-walker; per-model thresholds are explicitly
provisional until the Phase-6 golden set (which must span fraud types beyond lenders) calibrates them.

---

### ADR-0018 — Point-in-time source of record: BSE/NSE archives + official filings (owner decision, closes PLAN OQ#1)
**Context.** PLAN OQ#1 — the authoritative source for historical, point-in-time filings — had been open
since Phase 0. screener.in (ADR-0009) is a *current snapshot*: honest for as-of=today, useless for the
Phase-6 golden-set eval, which needs archived filings carrying their original `published_at`. The owner
decided (2026-07-30): **BSE/NSE archives + official company filings, free tier.**
**Decision.** The exchange archives become the point-in-time spine: BSE corporate-announcement archives
(announcement JSON with exchange receipt timestamps; attachment PDFs under
`bseindia.com/xml-data/corpfiling/AttachHis/…`) and NSE archives (`nsearchives.nseindia.com`, already used
for the Alkyl Amines AR, ADR-0011). `published_at` = the **exchange dissemination timestamp**, not the
fetch date — which is exactly what Law 3 needs for honest historical eval. Implemented behind the existing
`FilingsSource` protocol in `adapters/india/exchange.py` (pure parser fixture-tested; injectable fetcher;
NSE's bot-blocking handled with browser-like headers and treated as best-effort). Grades: the announcement
row = B (exchange filing); an audited AR/results attachment = A. screener remains the grade-B quantitative
cross-check only.
**Consequences.** The golden-set eval becomes buildable without a paid licence. Rate limits and endpoint
fragility are real (both exchanges change/block APIs) — hence adapter-isolated with cached bronze copies
(SHA-256, immutable) so a dead endpoint never destroys already-archived history. Bulk backfill must be
polite (throttled, cached, resumable).
**Verified live (2026-07-30, RELIANCE/500325):** announcements API returns dated rows with PDF
attachments (both AttachLive and AttachHis serve 200/`application/pdf`; downloaded size matched the
API's `Fld_Attachsize` byte-for-byte). Annual-report endpoint **lists** 1997–2026 but rows before 2012
carry no authorise date and/or no PDF link — the honest dated-and-downloadable depth is **2012–2026
(15 years)**, above the 10-yr target. The parser drops undated/linkless rows by design: an AR that
cannot be dated or fetched is not archive material. Real API responses are frozen as
`tests/fixtures/bse_*.json` so the parsers are tested against the production schema.
Implemented: `adapters/india/exchange.py` (`BseFilingsSource` implements `FilingsSource`; 100% cov).


---

### ADR-0019 — Dual-verdict report is code, not just a spec; publication is gated
**Context.** ADR-0016 defined the dual-verdict product (publish on PASS as well as FAIL) but left it a
document. A spec that isn't enforced is a preference; the owner's directive — *"we will also publish a
report if a company passes all the things"* — only becomes real if a positive report is held to the same
evidentiary bar as a negative one.
**Decision.** Implemented as three modules with blocking gates:
- `schemas/report.py` — `ResearchReport` (5 verdicts × 11 sections), `VerifiedCleanChecklist` (every
  check that ran, **passes included**), `CheckRecord` with `NOT_APPLICABLE`/`UNAVAILABLE` requiring a
  stated reason, `Criterion` (dated, filing-resolvable), `ReportClaim` (grade rendered inline).
- `core/validators/publication.py` — **P1** verified-clean completeness (every playbook-expected check
  accounted for; 100% note coverage required), **P2** symmetry (positives ≥3 dated kill criteria incl. one
  load-bearing; negatives need rehabilitation criteria; both need the opposing case and non-empty
  `open_questions`), **P3** legal framing (unhedged fraud accusation blocked; a `FORENSIC_CAUTION` needs
  replication steps, ≥1 FLAG, and may not rest solely on grade C/D).
- `core/report/render.py` — markdown + JSON; `write_report()` runs the gates and **refuses** to write an
  invalid report (`ReportNotPublishable`), so a misleading artifact cannot reach disk by accident.
  Uncited numbers render as `**UNCITED**` rather than passing as sourced.
**Consequences.** "We found nothing" is now falsifiable — the reader sees the check list. A `force=True`
escape hatch exists only to persist a failing draft for debugging. Predictions/Brier wiring (SPEC §7)
remains to be connected to `Criterion`.

---

### ADR-0020 — Model-specific checks land behind the playbook, with an anti-typo guard
**Context.** ADAPTIVE_FORENSICS §2 named model-specific checks that no code implemented; playbooks
referenced them by name. A playbook naming a check that doesn't exist is the worst failure mode in a
fraud detector: the report claims a check ran while nothing was evaluated.
**Decision.** Coded `contract_asset_divergence` (EPC: unbilled vs billed revenue),
`guarantees_to_net_worth` (off-balance-sheet SPV exposure; non-positive net worth with guarantees =
unbounded → flag), `capitalised_cost_share` (R&D/dev capitalisation), `adjusted_ebitda_bridge_gap`
(add-backs scaled by *revenue*, which stays stable for loss-making companies where EBITDA does not), and
`promoter_loan_share` (**SEVERE** — the Schedule III siphoning channel; applies universally, not per
model). Thresholds in `thresholds.yaml` → `model_forensic`; selection in `forensic_playbooks.yaml`.
Added a test asserting **every check named in any playbook is a real `ForensicMetrics` signal** (verified
non-vacuous: a typo'd name fails it).
**Consequences.** The §2 matrix is now executable for EPC/IT/real-estate/platform models, not just
lender/manufacturer. Remaining matrix items (same-store-growth gap, ECL stage migration, RERA/USFDA
ground-truth cross-checks) need external data and are deferred with that reason stated.

---

### ADR-0021 — Phase 2: agents are wired to the evidence graph and the report, and are held to the laws by code
**Context.** STATUS §3A named the real gap: nothing in `core/agents/` referenced `EvidenceGraph` or
`ResearchReport`, so the compute layer, the six graph invariants and the three publication gates had never
actually judged an agent's output. Phase 2 (SPEC §11) is `financial_statement_analyst`,
`forensic_accountant`, `business_analyst` — "full schemas, full validators" — ending in a published
report. Four sub-problems had to be decided, each of which the existing code left open.

**Decision 1 — a derived number carries its own provenance.** Law 2 says "provenance or it doesn't exist",
but a *ratio* had nowhere to put it. `core/pipeline/derive.py` introduces `Derivation(metric, value,
formula, inputs)` where `inputs` are the actual `Fact` rows, and synthesises a `Citation` whose **grade is
the worst input grade** and whose **`published_at` is the latest input date** — a ratio is exactly as
reliable as its weakest input and exactly as recent as its newest one. A metric whose inputs are absent
lands in `DerivedSet.missing` with the input names, never as a zero.

**Decision 2 — "did not fire" and "was never evaluated" must be different values.** `ForensicMetrics`
booleans default to `False`, so a check that never ran looked identical to a clean pass — fatal in a
published Verified-Clean Checklist. `core/pipeline/checks.py` evaluates every playbook-selected check
explicitly into `PASS` / `FLAG` / `UNAVAILABLE(reason naming the missing inputs)` /
`NOT_APPLICABLE(reason naming the suppressing models)`, and builds the screen's `ForensicMetrics` **only
from checks that ran**. A playbook check with no evaluator surfaces as `UNAVAILABLE`, never silently.

**Decision 3 — an agent may narrate, and only narrate.** `core/pipeline/deep_dive.py` enforces this
rather than requesting it: every numeric schema field an agent returns is re-checked against the compute
layer with the arithmetic validator (a field the compute layer cannot produce **must** come back `null`);
every number in **every string the agent authored** must carry a `[fact:...]` token resolving to a fact id
known to the run; a citation to an unknown fact id is a `FragmentProblem`; and the forensic agent returning
`PASS` over a deterministic `HARD_FAIL` is an `AgentDisciplineError`. One corrective retry is issued with
the specific violations appended before the run fails. The citation surface is computed from the schema
(`authored_texts()` walks every `str`/`list[str]`/claim-text field, skipping only the harness-set identity
fields) rather than from a hand-written list of field names — an independent audit of the first version,
which checked only `narrative` and the claim texts, walked fabricated percentages into a published
`COMPOUNDER` report through `what_it_does` and `disconfirming_search`, both of which `render.py` publishes.
A name list re-opens that hole every time a schema grows a field; deriving it from the schema does not.
A re-audit then exposed two defects in `core/validators/citation.py` itself, both repaired here: its fact-id
grammar excluded the colons that every real id contains (`derived:cum_cfo_pat`,
`screener-X:pnl:Sales:FY26`), so *no* number could ever be legally cited and the validator passed by vacuum
rather than by provenance; and its number pattern ignored digits glued to a preceding word, so "Rs9999
crore" — ordinary Indian financial prose — carried an uncited figure through. Both are fixed, the citation
window now bounds where a token may *start* rather than truncating the search, and a **value check** was
added: a number citing a real fact must state that fact's figure (rounding to the precision written is
accepted; changing the digits is not), because keeping the citation and altering the digits is the most
plausible way an LLM corrupts a number it was handed.
Load-bearing promotion is also code's decision, not the agent's:
inference/observation only (never speculation), confidence above the config floor, ≥1 grade A/B citation —
so R1 is satisfied by construction — then deduplicated by statement and capped run-wide.

**Decision 4 — the verdict and the criteria are computed, not written.** `core/report/assemble.py` holds a
fixed ladder: `FORENSIC_CAUTION` (a fired flag at or above the config severity, or the agent's veto) →
`INSUFFICIENT_DISCLOSURE` (too much of the playbook unevaluable, or the notes not read) →
`QUALITY_WRONG_PRICE` (the §6.3 gate fails) → `WATCH` (no gate result, or too little history) →
`COMPOUNDER`. The forensic veto can only make a verdict worse. `core/report/criteria.py` generates the
kill and rehabilitation `Criterion` objects from computed metrics plus `thresholds.yaml`, dated to the next
FY close plus the statutory filing lag, with a tripwire set inside today's value but never below the
published policy floor — because a criterion is a *number* and Law 1 forbids an LLM authoring one. A failed
feasibility gate becomes the re-entry trigger REPORT_ARCHITECTURE §2 asks for.

**Two honesty mechanisms worth naming.** (a) `NotesReview.substantive_share`: 100% note coverage is a
publication gate, and dispositioning every note `unknown` would satisfy it while reading nothing — so the
verdict ladder consults the share of notes a real check actually looked at, and a coverage-without-reading
run is `INSUFFICIENT_DISCLOSURE`. (b) Law 3 is applied to the **document**: a filing disseminated after
`as_of` is not walked at all, because filtering only its facts would still leak its notes and auditor
language into the run.

**Amendment to ADR-0019.** P1 previously required 100% note coverage from every report, which made the
`INSUFFICIENT_DISCLOSURE` verdict unpublishable — the gap that verdict reports was the thing blocking it.
That verdict is now exempt from the coverage gate and must instead be *evidenced* by an `UNAVAILABLE` check
or a named disclosure gap, exactly as `FORENSIC_CAUTION` must carry a `FLAG`.

**Consequences.** Phase 2's acceptance test is met offline and deterministically: five companies produce
five different verdicts, the accounting-fraud pattern (profit that never becomes cash, receivables
absorbing the gap) produces `FORENSIC_CAUTION` with the flags shown, and every string in every agent output
passes the citation validator. One deviation from SPEC's wording is stated rather than papered over: SPEC
wants the fraud case to come *from the golden set*, which does not exist yet, so the case is a synthetic
series built to the pattern the check library was back-tested against — the pipeline is exercised, the
historical calibration claim remains Phase 6's. The first real artifact through the pipeline —
`reports/ALKYLAMINE/2026-07-23-433c94208117/` — returned `INSUFFICIENT_DISCLOSURE` on grade-B screener data
with four of seven checks unevaluable, which is the correct and useful answer rather than a thesis built on
what was easy to fetch. Costs: agent prompts must now avoid restating numbers without citation tokens
(strict, and intentional); `working_capital_days`, Beneish and the lender checks stay `UNAVAILABLE` until
the AR-notes numeric extraction improves; `Criterion` objects still are not logged as predictions
(Phase 5).

### ADR-0022 — Line-by-line interrogation: publish the questions, not just the answers
**Context.** The first real artifact through the Phase-2 pipeline
(`reports/ALKYLAMINE/2026-07-23-433c94208117/`) was arithmetically sound and analytically shallow. It
reported `revenue_cagr 0.11` and moved on. The owner's objection, verbatim: *"we can't just see the revenue,
we have to see WHY the revenue is increasing... if the debt is increasing we can't consider it wrong, we
have to find the answer why the debt is increasing"* — along with the substance a revenue line actually
requires: what the company does, where the revenue comes from, whether the buyer base is concentrated or
spread, whether related parties are involved, and whether growth is volume or price. That is a correct
diagnosis of a real defect: a ratio table with narration is a screener with prose attached. The research is
the *cause*, and the report never asked for one.

**Decision 1 — the question is the unit of work, not the answer.** `config/line_items.yaml` holds the
analyst questions per statement line (revenue, margins, other income, debt, capital allocation, working
capital, cash, tax, related parties). `core/pipeline/interrogate.py` resolves each one exactly three ways
and never by silence: **ANSWERED** (a provenance-locked derivation answers it, rendered with its fact ids),
**UNANSWERED** (printed anyway, with `needs:` naming the exact filing row that would close it), or
**NOT_APPLICABLE** (invalid for the detected business model, suppressed with a reason — ADR-0002/0017). A
question dropped is a question that looks answered — the same defect ADR-0021 fixed for the forensic checks,
one layer up.

**Decision 2 — derivations that answer "why", not "what".** Four screener rows the pipeline already ingested
were read by nothing: `EPS in Rs`, `Expenses`, `Dividend Payout %`, `Cash from Investing Activity`. From
them: `dilution_drag` (PAT CAGR − EPS CAGR — the firm's question is a 5–10x *per share*, and aggregate growth
flatters a serial issuer), `self_funding_ratio` and `debt_funded_investment_share` (the cash-flow identity
answering *what the debt bought* — capacity, or distributions), `expense_cagr` / `opm_delta_window` (the
deterministic half of "why did the margin move"), `payout_share_of_cfo`, `effective_tax_rate_latest`. On
ALKYLAMINE these produced findings the previous report could not: growth was **not** bought with equity
(drag ≈ 0.1pp), and operating cash covered **1.48×** the entire FY15–FY26 investment programme while
borrowings *fell* ₹134cr. "Why is the debt increasing?" — it isn't.

**Decision 3 — refuse to narrate a meaningless number.** ALKYLAMINE's implied cost of debt computes to 100%
because year-end borrowings are near zero against a full year of interest. Arithmetically correct,
informationally empty, and a `bands:` clause would have dressed it in confident prose. `plausible:` declares
the range in which a ratio carries information; outside it the question is UNANSWERED and says why. A
confidently-worded garbage number is worse than no answer, because the prose lends authority to a degenerate
denominator.

**Decision 4 — DISCLOSURE gaps and CAPABILITY gaps are not the same thing, and only one may move a
verdict.** The subtlest decision here, and the first implementation got it wrong. An unanswered question is
either (a) one the pipeline put to the sources, which did not carry the row — evidence about the *company*,
allowed to degrade the verdict; or (b) one the firm has no extractor for, so it was never really asked —
evidence about *us*. `DerivedSet.missing` discriminates them exactly and automatically: a metric lands there
only because `derive_metrics` tried to build it and found an input absent. The first cut consulted all
unanswered questions and turned every verdict into `INSUFFICIENT_DISCLOSURE`, including for the clean
synthetic acceptance company; three failing tests said so. A firm that marks companies down for its own
unfinished note-parser will reject every good business it cannot yet read and call that rigour. So CAPABILITY
gaps lower `report_confidence` — the honest place for "we know less" as against "they disclosed less" — and
only DISCLOSURE gaps reach the ladder. ALKYLAMINE's confidence fell 0.21 → 0.14 accordingly.

**Decision 5 — ladder position is load-bearing.** The line-item rung sits *below* the short-history rung. A
three-year-old company cannot have a three-year incremental return on capital, and calling that a disclosure
failure would punish a business for its age; ADR-0008 routes short history to `WATCH`, never dropped. What
remains at that rung is the real case: a company with the history, clean checks and a passing feasibility
gate whose *business* is still unread.

**Decision 6 — P4, and two magic numbers retired.** A new publication gate requires every UNANSWERED question
to name what would answer it, every NOT_APPLICABLE to say why, and blocks a positive verdict carrying
unanswered high-severity DISCLOSURE questions — a backstop for the ladder, so a disagreement between the two
fails the run rather than publishing through. `_MIN_KILL_CRITERIA` and `_MIN_REHAB_CRITERIA` were module
constants in Python, which CLAUDE.md forbids; both now live in `thresholds.yaml`.

**Also fixed here.** `_as_fraction` reads the stored `unit` instead of guessing from magnitude. The old
`v / 100 if v > 1 else v` idiom (present in the ROIC path) silently mangles exactly the anomalous inputs a
forensic report exists to surface: a 120% effective tax rate or a 150% payout ratio became 1.2% and 1.5%.
And `make cov` invoked a bare `python`, which does not exist on stock macOS — the Phase-1 coverage gate had
been failing before it measured anything, so 100% on `core/compute` was an assertion rather than a check.

**Consequences.** The report now leads with the business rather than the fraud tests, and its
`disclosure_backlog` is a deduplicated, ordered extraction list generated by the questions themselves — so
"improve the data layer" (STATUS §3A) stops being a vague instruction and becomes a worklist. 563 tests
pass; `core/compute` holds at 100%, now verifiably. Costs: on a screener snapshot ALKYLAMINE answers only
32% of its questions and most of the remainder are CAPABILITY gaps — the registry asks for more than the
firm can currently read, which is the intended pressure but leaves `max_unanswered_high_line_items`
effectively inert until the AR extractors land. `receivable_days`, `receivable_days_delta` and
`inventory_days` are named in the registry with no derivation behind them, guarded by an explicit allowlist
in `tests/test_line_item_registry.py` so a typo cannot hide there. Every band threshold in the new registry
is PROVISIONAL until the Phase-6 golden set calibrates it.

### ADR-0023 — Kill criteria become the prediction ledger, on publish only
**Date** 2026-07-30 · **Status** accepted · **Extends ADR-0021 decision 4; opens Phase 5**

**Context.** ADR-0021 made the kill and rehabilitation criteria *computed* — dated, numeric,
filing-resolvable. Nothing consumed them. `core/monitoring/{predictions,resolver,brier}.py` was built and
`memory/predictions.jsonl` did not exist, so the criteria were prose in a markdown file and the calibration
loop (SPEC §7) had no input. STATUS §3C called this a small wire-up; the wiring is small and the two
judgment calls inside it are not.

**Decision 1 — kill criteria only.** A kill criterion is the firm's actual forecast: *this load-bearing
number continues to hold, and if it stops the thesis is dead.* A rehabilitation criterion is its opposite —
a counterfactual the firm expects **not** to occur, published so a future upgrade cannot be ad hoc. Logging
both would fill the Brier record with events nobody forecast, and a calibration score computed over them
would measure nothing. Rehabilitation criteria stay in the report and out of the ledger.

**Decision 2 — `probability` is the report's own `Confidence.value`.** The field is required and a Brier
score against an invented probability is worse than no Brier score. Law 1 forbids an LLM authoring the
number, and manufacturing a per-criterion figure in code would be arbitrary precision with nothing behind
it. `Confidence.value` already answers the right question — how much the firm believes the evidence beneath
these claims, computed from playbook evaluability, note-review share, line-item coverage (ADR-0022) and the
weakest grade relied on. It also creates the correct incentive: a shallow report logs a low-confidence
prediction and is scored gently; a confident one is scored hard.

**Decision 3 — log on publish, and only on publish.** A run blocked by a publication gate never shipped, so
the firm never stood behind it. Logging it would let the ledger fill with theses that were deliberately
withheld. `prediction_id = (run_id, metric)` makes the write idempotent (Law 5), so replaying a run appends
nothing and the ledger records what was forecast once rather than how often the pipeline ran.

**Decision 4 — attribution is to `core.report.criteria`, not to an agent.** These numbers are code's
(ADR-0021 decision 4). Crediting an agent would be a lie that `brier_by_agent` then compounds into a
per-agent score, punishing or rewarding a model for arithmetic it never touched.

**A test-isolation bug found and fixed in the same change.** The first wiring defaulted the ledger path to
`repo/memory/predictions.jsonl` unconditionally, so one run of the suite appended 35 synthetic predictions
for ACME/YOUNGCO/CLEANCO to the real calibration record. `run_deep_dive` now takes `memory_root`, the e2e
helper points it at `tmp_path`, and two tests pin the behaviour: a published report logs where it was told,
a blocked one logs nothing. The ledger is the one artifact where silent test pollution would be invisible
and permanent — every future Brier number would have been computed over fiction.

**Consequences.** ALKYLAMINE's five kill criteria are now rows in `memory/predictions.jsonl`, dated
2027-10-27, at p=0.14 (the report's confidence after ADR-0022's coverage damping). 573 tests pass. What is
still missing for Phase 5 to close: `resolver.py` is never invoked against a later filing, so nothing is
*resolved* yet; `memory/lessons.jsonl` does not exist; and `core/evolution/` is still empty. The ledger has
inputs and no loop — but the inputs are real, dated and idempotent, which is the part that had to be right
before anything scored them.

### ADR-0025 — A deterministic check may not fire on a degenerate input
**Context.** The first primary-source run of ALKYLAMINE published `FORENSIC_CAUTION` on `cash_debt_paradox`
with the detail `cash/assets 496.6% at cost of debt 100.0%`. Neither number was real. Cash cannot be five
times total assets, and the 100% cost of debt was Interest ₹1cr ÷ Borrowings ₹1cr — two *rounded* grade-B
screener figures whose ratio carries no information. On a real listed company that is a defamatory output,
and no existing gate could stop it: P3 checks the *prose*, which was correctly hedged, and the verdict came
from a deterministic check, which the architecture treats as authoritative.

Two distinct causes, both fixed here.

**Cause 1 — the unit fix was half-done (ADR-0024 follow-through).** `register_filing_facts` normalised the
figures it wrote to the fact store, but `walk_filing` still built `ExternalInputs` from `row.values`, i.e.
the figure *as printed* in lakh. The checks then mixed scales: a lakh cash figure divided by a crore asset
base gives exactly 496.6%. Ratio-of-pairs checks (receivables vs revenue growth) are scale-invariant, which
is precisely why the bug hid until a check compared across two sources. Everything crossing into
`ExternalInputs` is now canonical ₹ crore, so no check can see two scales at once.

**Cause 2 — the plausibility guard existed in only one layer.** ADR-0022 gave the *narration* layer a
`plausible:` precondition, and it worked: the line-by-line section correctly **refuses** to narrate this same
100% cost of debt, saying the ratio is uninformative because interest is a flow and borrowings a year-end
snapshot. The *check* layer had no equivalent, so the identical input produced an accusation instead of an
abstention. `config/thresholds.yaml:check_inputs` now carries two preconditions:

* `min_debt_to_assets` (2%) — below this the implied cost of debt is an artefact of rounding rather than a
  rate the company pays, so the paradox check declines to run. ALKYLAMINE's borrowings are 0.05% of assets.
* `max_cash_to_assets` (1.0) — an arithmetically impossible ratio is a fault in OUR pipeline, never a
  finding about the company. It reports unavailable and says the inputs are on different scales or a row was
  misread, which is what a reader needs in order to fix it.

**Consequence.** ALKYLAMINE returns `INSUFFICIENT_DISCLOSURE` (43% of the playbook unevaluable) with
`disclosure_gap` as the one live flag — the Schedule III rows genuinely are not in the filing text. The
unavailable share *rose* from 29% to 43% because a false flag became an honest abstention, which is the
right direction: 29% was cheaper and wrong.

**The general rule this establishes.** A precondition on an input is not the same thing as a threshold on a
result, and the firm needs both. Every check added from here states what its inputs must look like to be
worth believing, and mixed-grade arithmetic (a grade-A filing figure over a grade-B screener figure) is a
smell that deserves the same treatment — noted in STATUS as the remaining piece.

### ADR-0026 — Primary-source discovery works for any listed company, and dates what it can evidence
**Context.** Owner: *"the data is publicly available... as like that, you can find data of the publicly listed
company."* The Alkyl Amines IR page was an example of a pattern, not a special case — Reg. 46 of the SEBI LODR
requires every Indian listed company to publish its annual reports on its own website. The primary-source
ingest built in ADR-0024 already took any manifest path, but the manifest itself was hand-built, which made
the pattern unreusable in practice.

**Decision 1 — discovery reads a page, and downloads nothing.** `firm discover-filings --ticker --url` parses
an IR page, recognises the annual reports among the other PDFs, and writes
`data/manifests/{TICKER}-filings.json`. Retrieval stays a separate step. Pulling tens of megabytes from a
company's servers is a decision a human should take per company, and a discovery pass that fetched silently
would remove the moment where that decision is made.

**Decision 2 — a publication date carries its basis, and a re-upload is not a publication.** Law 3 turns on
`published_at`, so each entry records how its date was arrived at: `upload-path` where the publisher's own URL
encodes the month (`/uploads/2026/06/`), `statutory-proxy` where it does not. Crucially the upload month is
believed only if it falls inside a credible window — on or after the financial year closed, and no later than
the 30 September AGM deadline plus a grace quarter for a late filer. On the real site the FY17-FY21 reports
all live under `/2022/03/`, a bulk migration: believing it would date the FY17 report five years late and tell
a Phase-6 historical replay that it did not exist until 2022, silently deleting five years of point-in-time
evidence. Outside the window the statutory deadline is used, which is the latest date the report can lawfully
have appeared — conservative in the direction that prevents look-ahead — and it is labelled so no reader
mistakes an inference for an observation.

**Decision 3 — reject rather than guess.** "Annual Return" (MGT-7) and "Annual Secretarial Compliance Report"
are different documents and are excluded by name; a report whose fiscal year cannot be read off the link is
dropped, because a PDF that cannot be placed in a point-in-time series is worse than an absent one. Where two
links cover the same year (a migration copy and the original), the entry whose date rests on evidence wins.

**Consequence.** Verified against the live page: ten annual reports discovered, FY22-FY26 dated from the
upload path and FY17-FY21 from the statutory proxy — independently reproducing the manifest that had been
built by hand. `certifi` is now used for the TLS context, because a framework Python on macOS ships no CA
bundle for urllib and the fetch failed with CERTIFICATE_VERIFY_FAILED; verification is never disabled, since
a research firm reading a company's disclosures must know it reached that company.

### ADR-0027 — Read inside the notes, and enumerate the right ones
**Context.** After ADR-0024 the FY26 Alkyl Amines filing reached **100% note coverage and 0% substantive**.
Every note enumerated, not one read — so the highest-severity questions (related-party quantum, promoter
lending, director pay) stayed unanswered while the report could claim full coverage. `substantive_share`
(ADR-0017) is what stopped that from buying a positive verdict, and it did its job.

**Decision 1 — a note-body reader whose result distinguishes absent from empty.** `notes_content.py` reads the
Ind AS 24 note and returns `located`, the transaction categories present, and total KMP remuneration. The
failure mode here is not a wrong number but a **false clean**: "I read the related-party note and found no
loans to promoters" and "I could not find the note" produce the same empty result and mean opposite things.
`has_promoter_lending` is therefore tri-state — `False` is a publishable governance finding, `None` is a
refusal to conclude.

On Alkyl Amines FY26 the answer is a real finding: the note discloses **only** director remuneration
(₹27.69cr) — no related-party sales, purchases, loans, guarantees or investments — and states no amounts were
written off. That channel is the route almost every Indian promoter-level fraud uses, and here it is empty.
`promoter_lending` can now run, so unavailable checks fell 43% → 29%.

**Decision 2 — enumerate only the notes to the ACCOUNTS.** The unscoped scan was enumerating the wrong
document entirely: 17 "notes" from pages 5-44 — e-voting instructions, ACKNOWLEDGEMENTS, the chairman's other
directorships — and none of the 49 real notes on pages 87-133. Every one came back `uncategorised`, which is
why nothing could be dispositioned. The audited notes always follow the audited statements, so
`notes_section_start` anchors on the balance sheet. Same class of bug as ADR-0024's statement scoping, same
fix: a label search over a whole annual report finds the wrong table.

**Two bugs the tests caught that the real filing hid.**
* Summing lines that *name* a category caught the "Sitting Fees" sub-labels and missed every director,
  reporting ₹2.86cr against ₹27.69cr. These notes are block-structured — heading names the category, rows
  carry the figures — so the category is now carried as state.
* `find_note_body` stopped at the next heading only on *following* pages. On FY26 note 41 ends on p.121 and
  note 42 begins on p.122, so it worked by coincidence. Where two notes share a page it swept the neighbour
  in — and a related-party note's neighbour is Earnings Per Share, whose first row is net profit: ₹17,999.91
  lakh landing in directors' pay. Also removed page furniture from the sum (a page number "119" and "26" from
  "Report 2025-2026Website:" inflated ₹27.69cr to ₹52.27cr).

**Consequence and what is still open.** The related-party note is read and evidenced; the notes section is
correctly located (p.86 for FY26). But `notes.py:_NOTE_HEADING` does not match this filing's real note
headings — scoped enumeration finds 3 notes where there are ~49 — so `substantive_share` is still 0% and the
verdict remains `INSUFFICIENT_DISCLOSURE` on that basis. The pattern in `notes_content.py:_NOTE_HEADING` DOES
match them (it locates notes 38-49 reliably), so the fix is to port it. That is the next task, and it is now a
one-file change rather than an open question.

### ADR-0028 — Note headings come in three forms, and a check must declare its provenance span
**Decision 1 — the bare-number heading.** `notes.py` matched "Note 9: Inventories" and "9. Inventories" but
not the form these filings actually use for the audited notes: a bare number, whitespace, then the title —
"41 RELATED PARTY DISCLOSURES", "38 EMPLOYEE BENEFITS". Scoped enumeration found **3 notes where there are
~49**, so `substantive_share` sat at 0% and ALKYLAMINE was `INSUFFICIENT_DISCLOSURE` for a *formatting* reason
dressed up as a disclosure finding — the worst kind of wrong answer, because it is unfalsifiable from the
outside. Adding the third form takes FY26 to 11 notes with `related_party`, `tax`, `segment`, `leases` and
`employee_benefits` correctly categorised, and substantive coverage from 0% to 9%.

The bare form is the loosest of the three, so it is anchored hard: the line must END after the title, which
keeps it off balance-sheet rows ("9 Inventories 12,213.07 16,478.08" carries figures and is rejected). With
`notes_section_start` scoping it does not reach the AGM notice or the BRSR.

**Decision 2 — surface mixed-grade arithmetic rather than refuse it.** `cash_debt_paradox` divides cash read
from the audited filing (grade A) by total assets from the screener snapshot (grade B) and reports the ratio as
one measurement. That silently launders the weaker source: Law 2's chain says "filing-backed check" while half
the denominator came from an aggregator. Every `CheckRecord` detail now carries its provenance span —
`(grade B)`, or `(grades A+B — mixed provenance, weakest is B)`.

Surfacing was chosen over refusing deliberately. Refusing would disable the cash checks entirely until an AR
total-assets row exists, trading a *visible* weakness for an *invisible* gap — and ADR-0025 was caused by an
invisible gap. The rule is the one ADR-0021 already applies to `Derivation.citation`: a derived figure may
never look better-sourced than its worst input. It is now true of checks as well as derivations.

**Consequence.** `promoter_lending` reports real content ("categories disclosed = remuneration; KMP
remuneration ₹27.69cr"). Reaching the 50% substantive floor needs content readers for most note categories —
inventory, receivables, borrowings, contingent liabilities, tax, leases, employee benefits, segment — which is
several sessions of work, not one fix. Recorded honestly in STATUS rather than papered over by lowering the
floor: the floor is right and the coverage is not there yet.

### ADR-0029 — Provenance outranks recency in the fact resolver
**Context.** `FactStore.query_fact` resolved ties with `ORDER BY published_at DESC`. A screener snapshot taken
today therefore outranked an audited annual report published last month. Owner directive 1 is the opposite: the
filing is the source of record and screener.in is a grade-B **cross-check**. Ten annual reports were being
ingested and the published report still quoted the aggregator wherever both carried a row — ALKYLAMINE FY26
revenue resolved to ₹1,536cr instead of the filing's ₹1,535.86cr, and `fact_citations` held zero grade-A
entries. The forensic layer was reading primary sources while the report cited the secondary one.

Found by auditing the build against the constitution rather than against the test suite, which was green
throughout: nothing in it asserted *which source* should win.

**Decision.** Resolve by `(grade ASC, published_at DESC)` — best grade first, most recent within a grade.

Two behaviours are preserved deliberately, and both are now pinned by tests:
* **Law 3 is untouched.** `published_at <= as_of` still filters first, so no source can be seen before it
  existed, at any grade. A grade-A filing published after the query date stays invisible.
* **A restatement still wins within its grade.** Two audited filings, the later correcting the earlier: the
  correction is returned. What no longer happens is a lower-grade source overriding an audited figure by being
  fresher.

**Consequence.** `pnl:Sales`, receivables, inventory and cash for FY26 now resolve grade A from the filing.
Derived *ratios* stay grade B, and correctly so: `revenue_cagr` spans FY15-FY26 and the early years exist only
in the screener, so the worst-input rule (ADR-0021) puts the ratio at B. Grade A will propagate into the ratios
as the AR ingest widens to more metrics and years, not by relaxing that rule.

One existing test had to change rather than the code: it seeded a grade-C investor-deck figure alongside the
grade-B screener and expected the derived ratio to inherit C. The resolver now declines to select a C source
when a B exists, so to test worst-grade propagation the low-grade input must be the only source — the screener
row is now withheld. The old test was asserting the resolver's bug as if it were the contract.

### ADR-0030 — The roster is config, and a skipped agent is a published fact
**Context.** Phase 3 grows the firm from three agents to fourteen. The run order was `PHASE2_AGENTS`, a tuple
in `deep_dive.py` — right for three, wrong for fourteen. Sequencing is policy, and policy in Python is the
least reviewable place for it (CLAUDE.md already requires every threshold to live in config).

**Decision 1 — `config/roster.yaml`.** Each agent declares its SPEC §8 stage, the gate that must pass before
it runs, the build phase that introduces it, and its data prerequisites. Ordering is by stage, then by file
order within a stage.

**Decision 2 — build order is enforced, not remembered.** `plan_run(..., max_phase=N)` refuses every agent
above phase N, so a Phase-3 run cannot quietly recruit the Phase-4 judgment tier because a caller passed the
wrong list. CLAUDE.md forbids skipping phases; this makes the prohibition executable.

**Decision 3 — three kinds of skip, kept distinct.** They mean different things to a reader, so collapsing
them would destroy the signal:
* *out of phase* — the build has not reached it. Not a coverage gap; following the build order is not a
  failure to look.
* *gate not passed* — the funnel rejected the company upstream (SPEC §8). Also not a coverage gap.
* *missing inputs* — the agent could have run and we could not feed it. **This alone** is a coverage gap, and
  it reaches the report worded against the firm: *"…this is a gap in our coverage, not in the company's
  disclosure"* (ADR-0019 — never charge a company for our own missing extractor).

The alternative was to run whoever can run and let the rest fall away. That yields a report with no
governance section and no visible reason for it, which is ADR-0027's false-clean problem again: a reader
cannot distinguish "management looked fine" from "nobody looked at management".

**A bug the tests caught immediately.** Gates are ordered A→E and a failure stops everything below. Checking
only `gates[entry.gate]` meant that with Gate B failed and Gate C merely unevaluated, the Gate-C management
agents fell through to the input check and were reported as coverage gaps — the firm blaming itself for not
examining a company the funnel had already rejected. A run that never reaches Gate C cannot have a coverage
gap at Gate C.

**Consequence, measured on ALKYLAMINE.** Phase 2: 3 agents, 100% staffed. Phase 3: 5 agents run
(`macro_strategist` and `unit_economics_analyst` join), **coverage 56%** — `sector_analyst` needs a peer set,
`transcript_analyst` needs concalls, `management_analyst` needs guidance history, `ownership_flows_analyst`
needs shareholding and pledge. None of those four are ingested, and the honest reading is that Phase 3 is
half a data problem: wiring the prompts is the small part.
