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

### ADR-0031 — Enumerate every IR section before calling an input unavailable
**Context.** Phase 3 reported four agents "blocked on data that does not exist": `transcript_analyst`,
`management_analyst`, `ownership_flows_analyst`, `sector_analyst`. That was wrong, and the owner said so.
Discovery had only ever fetched **one** page — `/investors-type/financials/`. The company's own IR nav
carried Corporate Governance, General Meetings, Announcements, Investor Center and Disclosure Reg 46, none of
which had been opened. They hold **622 PDFs**, including 27 shareholding patterns, 15 concall transcripts, 12
voting results and the credit-rating letters.

Three of the four agents were never blocked. The firm had declared a capability gap without looking, which is
precisely the failure ADR-0019 forbids in the other direction — and worse here, because it silently shrank
the firm's own scope rather than a company's score.

**Decision 1 — discovery crawls `IR_SECTIONS`, not one page.** Reg. 46 of the SEBI LODR enumerates what every
listed company must publish on its website; the section list is derived from the regulation, so it
generalises. `DOCUMENT_CLASSES` classifies links into annual report, shareholding, transcript, credit rating,
voting result, presentation, quarterly result, governance and annual return, with rejects ordered before
generals ("Annual Return" must be tested before "annual report").

**Decision 2 — availability is derived from the manifest, never asserted.** `available_inputs_from()` maps
ingested document classes to roster prerequisites, so the roster cannot claim more coverage than the ingest
supports **or less**. A hand-passed list is what produced the false blockage. Two mappings are worth stating
because they are not obvious: a shareholding pattern satisfies `pledge` as well, since SEBI's format carries
pledge as a column ("Whether any shares held by promoters are pledge or otherwise encumbered?") rather than as
a separate filing; and transcripts satisfy `guidance`, because management's forward statements are exactly
what a promise-vs-delivery scorecard is built from.

**Verified on the real documents.** The FY25 Q2 shareholding pattern yields
`(A) Promoter & Promoter Group ... 71.96` and `pledge or otherwise encumbered? No` — the pledge question
answered from the primary source rather than left open. The Nov-2019 transcript extracts 13 pages and 28,735
characters of speaker-attributed Q&A, management against named analysts. (Its text layer shows character
confusion — "Rabul Jain" for "Rahul Jain" — which is survivable for narrative use but must not be trusted for
a name-matching related-party check.)

**Consequence.** Phase-3 coverage rises from 56% to 89%: eight of nine agents run. Only `sector_analyst`
remains blocked, and correctly — a peer set is *another company's* documents, which is an ingest of the same
shape pointed at a different IR site, not a missing capability.

**The rule this encodes.** Before recording any input as unavailable, enumerate every section the regulation
requires the issuer to publish. "We did not find it" is a claim about our search, not about the world.

### ADR-0032 — Shareholding: repair the column with the category identity, or refuse the stake
**Context.** Promoter stake and pledge are the two hardest governance signals, and Reg. 31 of the SEBI LODR
fixes the *format* of the filing that carries them. A parser written against one company's shareholding
pattern is therefore a parser for the market, which is why this was worth doing properly.

**The failure mode is a plausible wrong stake.** 71.96% misread as 17.96% would drive a governance verdict off
a cliff and look entirely normal doing it. The categories are exhaustive by construction — promoter % +
public % + non-promoter-non-public % = 100 — so that identity is used as an acceptance test on **our own
extraction**. Anything that will not reconcile is refused with its reason, never reported.

**The identity also repairs.** On 14 of Alkyl Amines' 27 quarters the text layer loses the column separator
and welds the percentage onto the share count: `3683726872.0265` is `36837268` shares followed by `72.0265`
percent. The token cannot say where to split, and a greedy regex silently picked the one-digit split —
`2.0265` where the truth is `72.0265`, a wrong answer with no outward sign of being wrong. Both readings are
now generated and the pair that sums to 100 is selected. An acceptance test became a repair, and one that
cannot invent a stake: a wrong split simply fails to sum.

**Pledge is tri-state** for the ADR-0027 reason. `False` — the filing was read and answers "No" to
*"Whether any shares held by promoters are pledge or otherwise encumbered?"* — is a real governance finding.
`None` means the question was not located and nothing may be concluded.

**Result on the real filings.** 13 of 27 quarters parse, covering FY23-FY26: promoter holding 71.96%-72.05%
with **no pledge in any quarter read**. A promoter group that has neither diluted nor borrowed against its
stake across the period is a genuine positive, and it is the first governance fact the firm has established
from a primary source.

**Honest remainder.** The other 14 quarters (2019-2022) use an older layout whose category rows the current
patterns do not match at all — they fail at location, not at reconciliation, so no wrong number is produced.
Extending to that layout is the next task and is precisely specified: the files are named in
`data/manifests/ALKYLAMINE-documents.json` and every one fails with "the promoter and public category rows
were not both located".

### ADR-0033 — The roster drives the run, and an unstaffed agent is visible twice
**Context.** ADR-0030 built the roster; nothing consumed it. `deep_dive` still defaulted to `PHASE2_AGENTS`,
so the published report's `agent_versions` listed the same three agents it had since Phase 2 and the roster's
89% staffing existed only in a planner nobody called. That is the Phase-2 gap repeating one level up:
machinery that nothing runs through is unproven machinery.

**Decision 1 — `plan_agents(phase, available_inputs)` selects the roster, and `firm deep-dive` gains
`--phase` and `--documents`.** Availability is the **union** of the filings manifest and the documents
manifest. Reading only one made a Phase-2 run plan *zero* agents, because the annual reports live in the
filings manifest while the governance documents live in the documents manifest, so `financials` looked
unsatisfied while ten annual reports sat in the store.

**Decision 2 — coverage gaps reach the report but never the verdict.** They join `unavailable_items`, so a
reader sees everything unestablished in one place, phrased so the distinction survives: a company's
non-disclosure reads as a disclosure gap, an agent that never ran says in its own words that the gap is
ours. `choose_verdict` deliberately takes no `coverage_gaps` argument, and says so in a comment — ADR-0019
forbids charging a company for the firm's own missing extractor, and the cleanest way to enforce that is to
make the data unavailable at the point of decision.

**Decision 3 — pre-flight before any agent call.** An agent with no answer used to fall through to whatever
provider was configured; by default the local stub, whose output fails schema validation. The run burned
three retries per unstaffed agent and died with *"agent output failed validation after 3 attempts"* — naming
no agent and giving no hint of the cause. Now that the roster grows with the build phase, planning more
agents than the operator has answered is an ordinary situation, so it fails immediately with the agents
named and the remedy stated.

**Verified end to end.** `--phase 2` plans 3 agents, staffs all 3, and publishes a byte-identical report.
`--phase 3` plans 8 and stops at once: *"no prepared answer for 5 planned agent(s): macro_strategist,
unit_economics_analyst, management_analyst, transcript_analyst, ownership_flows_analyst."* An intermediate
run also proved the publication gate independently — with zero agents staffed it refused to ship, citing
`P2_asymmetric @ thesis: thesis is empty`, rather than publishing an empty report.

**What this does NOT yet do.** The five new agents have prompts, schemas and a place in the run order, but no
answered packets, so no new narration reaches a report. Phase 3 is wired, not staffed.

### ADR-0034 — Staffing Phase 3: packets follow the roster, and the discipline layer caught the narrator
**Context.** ADR-0033 wired the roster into the run, leaving Phase 3 "wired, not staffed": five agents had a
place in the run order and no answered packets, so `agent_versions` still listed the same three agents. Two
plumbing defects kept it that way, both mine:

* `firm packets` had no `--phase` and wrote packets for the fixed trio, so the five could never be answered.
* `firm deep-dive` called `read_answers(answers)`, which defaults to the Phase-2 trio — it silently ignored
  the five answer files sitting in the same directory and then failed pre-flight claiming they were never
  written. Answers are now read **after** the roster is known.

**The part worth recording is what happened when the answers arrived.** I wrote the five agents' output
myself — that is the designed Claude-in-the-loop path (ADR-0010) — and the discipline layer rejected three
separate violations in it before anything reached a report:

1. `unit_economics_analyst` — `narrative: number '7' — no_citation`. The prose named the schema field
   `units_plausible_in_7y`, and the digit read as an uncited figure. I considered exempting backticked spans
   and **rejected it**: an agent could then hide numbers in code formatting to evade citation entirely. The
   validator is right and the prose was wrong.
2. `management_analyst` — `narrative: number '134' — value_mismatch`. The claim "borrowings fell by 134
   crore" cited `debt_delta_window`, whose value is **-134**. Semantically correct, numerically mismatched,
   and refused. This is the ADR-0021 value check doing precisely the job it was built for, on a real
   plausible-sounding sentence rather than a synthetic one.
3. `management_analyst`, `transcript_analyst`, `ownership_flows_analyst` — bare document counts ("15
   transcripts", "27 filings") with no fact behind them. Every one removed; the firm ingested those
   documents but never registered the counts as facts, so they were uncitable by construction.

**Consequence.** Eight agents now appear in `agent_versions` of a published report, and `sector_analyst`'s
absence is published as the firm's own coverage gap, worded against us. The verdict is unchanged at
`INSUFFICIENT_DISCLOSURE` on the 9%-substantive-notes floor — five new narrators did not talk the company
into a better verdict, which is the separation of powers working.

**What the new agents honestly say.** Three of the five report that their inputs exist but are unparsed —
`transcript_analyst` scores no guidance drift, `ownership_flows_analyst` cites no holding, and
`unit_economics_analyst` reports both unit counts as zero-meaning-unknown. That is the correct output for
this state of the ingest, and far more useful than invented tonnage or a tone reading from a skim.

### ADR-0035 — A parsed figure nothing can cite is not a fact
**Context.** ADR-0032 parsed the SEBI shareholding pattern; nothing wrote the result anywhere an agent could
reach. So `ownership_flows_analyst` ran and abstained — *"filings ingested, none registered as facts, so no
holding may be cited"* — honest and useless. A parser whose output no report can quote has not closed the gap
it was written for.

**Decision — register quarterly governance facts, with three constraints that each caught something.**

*Publication date is the filing deadline, not the quarter end.* SEBI Reg. 31 allows 21 days. Dating the
filing at quarter end would place it public before it can exist, breaking Law 3 in the only direction that
matters — the one that permits look-ahead.

*Quarterly facts need a quarterly read path.* `load_company_facts` iterated fiscal years only, so
`Q2FY25` was never queried and the facts loaded into nothing. A second pass reads quarter labels, and
deliberately does **not** add them to `periods_with_data`: `history_years` counts annual periods, and a
quarterly filing must not inflate the apparent length of the record.

*Pledge stays tri-state through storage.* Stored 1.0/0.0 with unit `bool`, and **only when the filing
answered**. An unanswered pledge question writes no fact, so silence can never be read as "no pledge"
(ADR-0027 preserved past the parser).

**The defect worth recording.** The fact ids were built straight from the metric name — `governance:Promoter
Holding` — which contains a space, and the citation grammar cannot parse one. The gate that exists to let an
agent quote a number rejected these facts outright: governance metrics that no report could ever cite, in a
system whose entire premise is that every number carries a citation. Ids are now slugged
(`…:promoter_holding:Q4FY26`); the metric name is unchanged, so queries and report tables read as before.
The lesson generalises: a fact id is an opaque token consumed by a strict grammar, and deriving it from a
human-readable label couples two things that have no reason to agree.

**Result.** 12 quarters registered grade-A, spanning Q2FY23-Q4FY26. The report now carries its first
primary-source governance claim: *"Promoter holding at the latest quarter read is 72.05%
[fact:SHP-Q4FY26-…:promoter_holding:Q4FY26]"* — grade A, and the pledge question answered no in every
quarter that answers it. The verdict is unchanged; a positive governance finding did not buy a better one.


> **Numbering note.** ADR-0036-0038 below and ADR-0039-0043 after them were written on two branches in
> parallel and both claimed 0036-0038. The extraction line (`claude/alkyl-amines-report-dddcec`, written
> 2026-07-31) keeps the original numbers; the ingest line (`claude/loop-engineering-technique-d90b3c`,
> 2026-08-01) was renumbered to 0039-0043 on merge. Commit `3b25966`'s message cites ADR-0036/0037/0038
> and is correct; commits `c743062`, `8ca1a40`, `5b43c45`, `a1a83f9` and `ee2c537` cite 0036-0040 and
> mean what are now **0039-0043**.

---

## ADR-0036 — The filings check each other, and a contradiction quarantines both figures

**Date** 2026-07-31 · **Status** accepted

**Context.** Ten annual reports overlap by one year each: filing *N*'s comparative column restates filing
*N−1*'s reported figure. `crosscheck_overlaps` could already classify a disagreement as `rounding`,
`restated` or `extraction_error`, and its docstring said an extraction error "must be quarantined, never
published" — but nothing called it. The function had no caller anywhere in `src/`. So the FY18 report's
trade payables of ₹67.18cr and the FY19 report's comparative of ₹0.67cr — a 90% gap that no company
restates — both sat in the store at grade A, out-ranking the very screener figure that would have
contradicted them.

**Decision.** `quarantine_extraction_errors` runs after every manifest ingest and **deletes both sides**
of an `extraction_error` overlap. Not the larger, not the smaller, not the newer: which document was
misread is precisely what the disagreement does not say, and any tie-break would be a guess dressed as a
rule. A metric-year the sources cannot agree on becomes UNAVAILABLE, the disagreement is printed, and the
grade-B screener fills the hole if it has one. `restated` overlaps are untouched — a real restatement is a
finding about the company, and the resolver already prefers the later filing within a grade.

**Consequence.** Ten quarantines on Alkyl Amines, and the interesting ones are honest: FY18/FY19 trade
payables (a genuine misread — the FY19 layout splits the row and we caught only one half), FY21 EPS
(₹144.68 against ₹57.90, a real restatement for a face-value split that the 25% band cannot distinguish
from a misread), and FY17 operating profit (the excise-duty presentation change at the GST transition).
The cost is real: a legitimate restatement wider than 25% loses its grade-A fact. That is the correct
direction of failure for a fraud detector, and the threshold is in `config/thresholds.yaml`, provisional
until Phase 6.

---

## ADR-0037 — Read the whole filing, not the four rows the checks needed

**Date** 2026-07-31 · **Status** accepted · **Supersedes the scope of** ADR-0024

**Context.** `FILING_ROWS` mapped four metrics: revenue, receivables, inventory, cash. Everything else in
every published report — profit, operating profit, borrowings, total assets, cash flow, the entire expense
structure — still resolved to the grade-B screener snapshot, *while ten audited annual reports sat in the
store*. The first report's numbers table carried thirty-odd rows and almost every one said "grade B".
Owner directive 1 was satisfied in architecture and defeated in practice.

**Decision.** Four changes, each of which was load-bearing:

1. **Layout-mode extraction** (`extract.py`). pypdf's default reading order *splits table rows*: on the
   FY21 balance sheet "Property, Plant and Equipment" arrives as three lines and `Inventories 7` ends up
   with its figures on the next one — which is how FY21 inventories entered the store as ₹0.07cr against
   a true ₹121.90cr, at grade A. Layout mode reconstructs the row on all ten filings. A page whose
   laid-out text is materially shorter than the plain read falls back, because layout mode silently drops
   rotated text.
2. **Forty-plus rows across three statements**, including a `cashflow` locator that spans the page break
   (the financing section, and with it borrowings movement and dividends, is on the continuation page).
   Rows that are a total the filing never prints — trade payables, borrowings — are summed from their
   parts, each part named in the locator.
3. **Composed metrics.** No Ind AS P&L prints operating profit or an effective tax rate; it stops at
   "Total Expenses", which bundles the finance costs and depreciation an operating margin must exclude.
   Five metrics are therefore composed by one subtraction or division over figures on a single audited
   page, with the formula and every contributing line in the locator. These are not estimates and they
   are not LLM output; they are arithmetic the reader can redo from the page.
4. **The balance sheet must balance** (`reconcile_to_identity`). Layout reflow can hand a subtotal's
   figures to the next section's heading: on FY22, "TOTAL ASSETS 53,757.00" is the *current-assets*
   subtotal and the real total sits on the "EQUITY AND LIABILITIES" line below it. Nothing about that row
   is malformed — statement scoping, the note-column guard and the unit check all pass it. The
   liabilities-side total is an independent statement of the same figure, so a candidate that disagrees
   with it is either repaired from the row that satisfies the identity, or not stored at all.

**Consequence.** From 4 metrics to 36, FY16-FY26, essentially all grade A. Working-capital days, the cost
breakup and its movement, capex against depreciation, net cash and the yield on it are all derivable for
the first time; `tests/test_line_item_registry.py`'s `known_capability_gaps` allowlist is now empty.

**The cost, stated plainly.** Reading more rows means more ways to read one wrongly. Three defences are
what make this safe rather than reckless: the balance-sheet identity, the cross-filing quarantine
(ADR-0036), and the note reconciliation (ADR-0038) — each of which checks a figure against something the
same document says elsewhere, rather than against our confidence in the parser.

---

## ADR-0038 — A note is "read" when it reconciles to the face of the statements

**Date** 2026-07-31 · **Status** accepted · **Extends** ADR-0017

**Context.** `substantive_share` — the share of notes a deterministic check actually looked at — was 9%
against a 50% floor, and it was the sole reason Alkyl Amines returned INSUFFICIENT_DISCLOSURE. Two causes.
The heading pattern was `$`-anchored, and a real note heading is followed by the table's unit declaration
("3. Property, Plant and Equipment  ` In Lakhs"), so it found 11 of 63 notes. And the only way a note
could earn a substantive disposition was a forensic check on its taxonomy category, which covers a dozen
categories out of forty-five notes.

**Decision.** Two mechanisms, neither of which lowers the bar:

*Enumeration.* The heading pattern ends the title at a column gap rather than at end-of-line, and the
enumerated notes are then filtered to the **longest ascending run** of note numbers in document order.
Notes are numbered in sequence and printed in that sequence, so a "note 5" appearing between 39 and 40 —
which is what an actuarial-assumptions table inside the employee-benefits note looks like — is not a note.
Any text-shape rule loose enough to catch the real headings catches some of these; the filing's own
ordering is a check that costs nothing and typography cannot fool.

*Disposition.* A note exists to break one figure on the face of the statements into its parts, so that
figure must appear somewhere in its body. `reconcile_notes` looks for it. A note that ties has been read
in the only sense that matters, and this is a stronger claim than "a check touched its category", not a
weaker one — it is the note's own arithmetic, tested. A note that does NOT tie is reported `unknown` with
the figure that was sought, never `flag`: a non-tie is far more likely to be a continuation table this
reader missed than a company misstating its own subtotal, and charging that to the company is the
capability-versus-disclosure confusion ADR-0022 exists to prevent.

**Consequence.** 45 notes enumerated, 64% substantive, verdict `QUALITY_WRONG_PRICE`. The sixteen notes
still `unknown` are honest ones — accounting policies, critical judgements, actuarial tables, segment,
tax, leases, derivatives — none of which details a single face figure.

**Found on the way, and worse than the thing it was blocking.** The Schedule III scan reported six
mandated disclosures "absent" and fired a MEDIUM `disclosure_gap` — *unexplained opacity* — at a company
that had disclosed all six. It was matching the name of the rule rather than what a company writes:
Alkyl Amines heads its ageing tables "Outstanding for following periods from due date of payment" and
answers the promoter-lending row as "advances in the nature of loans". A false forensic flag on a real
listed company, produced entirely by our own pattern list.


### ADR-0039 — The transcript parser: guidance is a quote with a date, never a paraphrase
**Context.** STATUS §3 Phase 3 remainder: `transcript_analyst` and `management_analyst` need concall
transcripts parsed. Thirteen Alkyl Amines transcripts sat in bronze, satisfying the roster prerequisite on
paper while the agents had nothing they could cite — the ADR-0035 gap again, one document class over.

**Decision — `adapters/india/transcripts.py` extracts dated, verbatim, unit-anchored guidance.** A guidance
statement is a sentence that attaches a number to the future, recorded exactly as printed with its page. Four
refusals define the parser more than its extractions:

*A question is not guidance.* An analyst asking "do we expect 21%?" must never be counted as management
guiding 21%. Sentences are classified statement/question — by final punctuation AND by interrogative
phrasing, because real asks trail off without a question mark ("Sir, just wanted to ask, any guidance
regarding this FY.").

*An announcement is not a transcript.* The May-2022 intimation letter names an "earnings conference call"
and parsed as a transcript with zero guidance. Refused now: a document must carry the transcript itself
(the word in the Reg-30 letter, or the moderator's dialogue), or it is not read for guidance.

*No speaker attribution.* The text layer detaches the speaker column from the dialogue (every name first,
then every utterance), and "the CFO said" is a claim about a person. Quotes carry a page, not a name.

*Only unit-anchored values.* "15%" and "Rs. 150 crores" become values; bare numbers, calendar years and
dial-in codes stay in the quote. An unanchored figure has no meaning an agent could safely cite.

**Three parsing defects the real filings caught.** (1) The sentence splitter broke at the dot in "Rs. 150
crores", stranding every rupee figure from its anchor — abbreviation dots no longer end sentences. (2)
"Q4 FY23-24" read as FY23: the range form names the FY twice and the Indian FY is named for the year it
ends in, so the second token wins. (3) "held on Thursday, November 7, 2019" — the weekday broke the
held-on pattern and every call date silently fell back to the letter date.

**Result.** All 13 real transcripts parse: call dates from the cover letter's own "held on" sentence,
submission dates strictly after them, 12 of 13 quarters stated (one inferred and labelled
`derived-from-call-date`), 77 guidance statements with 57 unit-anchored values across FY20-FY26. The
announcement is refused with its reason. Registration as citable facts is the next step — this ADR ends
where ADR-0035 began.

### ADR-0040 — Guidance registered: a promise is a fact about management, dated when it became public
**Context.** ADR-0039 parsed the transcripts and ended where ADR-0035 began: a parsed quote nothing can cite
is not evidence. `transcript_analyst` still could not write "management guided 15%" because no fact carried
that value.

**Decision.** `core/ingest/transcripts.py` registers each guided figure as a grade-A fact — grade A because
the transcript is the company's own Reg-30 filing: the provenance of the *statement* is primary even though
the statement itself is a promise, and the house standard already frames it as data about management, not
the business. The verbatim sentence and its page travel in the locator, so the citation gate holds an agent
to exactly what was said and where. Only parser-classified `statement` sentences register; an analyst's
question never does. `published_at` is the Reg-30 letter's own date, falling back to the five-working-day
deadline taken as seven calendar days — the same never-earlier-than-public direction as Reg. 31 in
ADR-0035.

**The resolver would have eaten the series.** One call quarter carries several guided figures under one
topic ("10% to 15%" is two facts), and `query_fact`'s per-(metric, period) resolution — right for a
balance-sheet row — would return one and silently drop the rest. `FactStore.query_metric_prefix` reads the
whole series point-in-time, oldest call first, and `run_deep_dive` feeds it to the packet as
`management_guidance` (quote, value, `cite_as`), extends the known-citation set with it, and keys the run
id on the guidance ids (Law 5: different transcript inputs are a different run).

**Result.** On the real manifest: 57 guided figures registered across 13 quarters FY20-FY26; the May-2022
announcement refused with its reason; the one transcript without a letter date dated by deadline. A
scripted agent citing "15% [fact:TRN-Q4FY25-…:guidance_volume_growth:…]" passes the citation gate — the
test the whole chain exists to satisfy. Known cosmetic debt: a running header occasionally joins a quote
("Alkyl Amines Chemicals Limited May 06, 2026 And given…"); values and pages are unaffected.

### ADR-0041 — The shareholding parser reads the layout the filings use, not the one we met first
**Context.** STATUS §3 carried "the older shareholding layout (14 quarters that fail at location)" as
Phase-3 remainder. Fourteen of Alkyl Amines' 27 shareholding patterns were refused with *"the promoter and
public category rows were not both located"* — the parser had been written against the 2023-onward layout
and quietly could not read the seven years before it.

**Decision — scan whitespace-collapsed page text with bounded category regions.** The pre-2023 filings wrap
both the category label and its figures across a dozen physical lines ("A Promoter &\nPromoter\nGroup\n13
1513278\n8 ..."), so a line-anchored pattern can never see a whole row. Collapsing each page to one string
makes both layouts read alike; collapsing *per page* rather than per document keeps the page number the
locator needs. Each row is then bounded by the next category label, because Table II — the promoter
breakdown by name — follows Table I in the same document, and its per-shareholder percentages must never
compete with the category's own.

**The wrapped digits were not the problem.** The text layer splits share counts across line breaks
("1513278\n8"), which no join rule repairs: joining without a space glues the next line's percentage onto
the count, and joining with one splits the count in two. It did not need repairing. The parser wants the
*percentage*, the percentage survives unwrapped, and ADR-0032's category identity (promoter + public = 100)
was already there to choose among readings. The fix was locating the row, not reconstructing it.

**A whole-number percentage needed a second reading.** Two quarters print "72" and "28" rather than
72.05/27.95, and the decimal-in-range discriminator rejects an integer by construction — correctly, since
share counts are large integers and the shareholder count is a small one. So the integer reading is
consulted **only** where the decimal reading fails to reconcile, and it must still satisfy the identity,
which for two integers means summing to exactly 100. The count (13) can never be mistaken for the stake
(72): pairing it with the public reading sums to 41.

**SEBI restructured the pledge question and we were reading silence.** From 2025 the single declaration
("pledge or otherwise encumbered?") became three — encumbered under "Pledged", under "Non-Disposal
Undertaking", and otherwise. The old pattern matched none of them, so the two most recent filings reported
pledge as *unknown* while the page in front of us answered "No". Both wordings are now read. NDU and
other encumbrance are deliberately **not** folded into a field named `pledged`: SEBI separates the
instruments, and aliasing them would misreport a governance fact. They are an open gap, stated as one.

**Result.** 27 of 27 filings located, every one reconciling to exactly 100.0, pledge answered in all of
them. Registered facts go from 12 quarters to **26**, Q1FY20-Q4FY26 — the promoter stake drifting 74.19%
to 72.05% with a visible step between Q1FY22 and Q2FY22, which is a series `ownership_flows_analyst` can
finally read as a trend rather than a point. Also deleted `_holding_pct`, dead since the identity-based
pairing replaced it.

**Two gaps left standing, both stated rather than papered over.** One filing (Q3FY26) has its reporting
date scrambled out of position by the text layer; it is refused and skipped, because a wrongly dated
filing breaks Law 3 more quietly than a missing one, and that quarter is duplicated by another file
anyway. And the NDU / other-encumbrance answers are parsed by nobody yet.

### ADR-0042 — Peer comparison: one period, both companies, or it is not a comparison
**Context.** The last Phase-3 prerequisite with nothing behind it. `sector_analyst`'s mandate is to locate
the sector's profit pool and say who holds pricing power — both *relative* claims — so the roster gave it
a `peers` prerequisite that no ingest satisfied, and the agent never ran. Balaji Amines' annual reports
were already in the fact store, grade A, FY21-FY25, read by nobody: the ADR-0035 pattern a third time.

**Decision — `core/pipeline/peers.py`, and the invariant is the period.** The obvious implementation
compares each company at *its own* latest year. The subject files before its peer, so that silently
compares ALKYLAMINE FY26 against BALAMINES FY25 — two different years of a chemicals cycle — and the
output looks entirely normal while measuring nothing. On the live data it would also have been *wrong in
the flattering direction* for the peer: the subject's FY26 revenue is ₹36cr **below** its FY25, so the
naive read understates the gap between them. Every row therefore carries ONE period, used for both sides,
chosen as the latest period where both companies disclose every input that row needs. `PeerMetric.period`
is a single field precisely so the dangerous object cannot be constructed.

Growth is compared over the longest window BOTH cover (FY21-FY25 here, not the subject's FY15-FY26): a
peer with five years and a subject with twelve, each measured over its own record, compares a half-cycle
against a full one.

**No proxies, and no arithmetic in this module.** Inventory days needs COGS, which neither company's
ingested metric set carries cleanly, so it is not compared rather than computed off an "expenses"
stand-in that would make two firms' working capital differ where only the approximation does. Every
figure comes from `core/compute/ratios.py` (Law 1). `cagr` moved there from a private copy in `derive.py`
— a third copy was about to exist, which is exactly what Law 1 forbids.

**A measure that cannot be compared says so.** An absent row reads as "these companies are alike here".
`incomparable` carries the reason instead, and a *named* peer we hold no facts on returns an empty
comparison with its own reason — that is a gap in the firm's coverage, not a row to drop.

**Availability is earned, not asserted.** `peers` is satisfied by another company's facts rather than by
a document in this company's manifest, so the CLI resolves it — and only when the comparison actually
yields a row. Naming a peer we have no data on must not let the roster claim coverage that produces
nothing citable.

**Result.** `sector_analyst` is staffed for the first time. Against BALAMINES on FY25, all grade A except
net margin: Alkyl Amines is the larger business (₹1,571.8cr vs ₹1,273.6cr), earns slightly *less* per
rupee of sales (11.83% vs 12.27%), collects markedly faster (53.6 days vs 70.4), and grew sales at 6.1%
CAGR against the peer's 0.9% over FY21-FY25. Both sides of every row are citable, and a scripted agent
quoting the peer's figure passes the citation gate.

### ADR-0043 — Every numeric agent field is classified, or the build fails
**Context.** `_numeric_discipline` validates only the fields present in `NUMERIC_FIELD_SOURCES`, and the
citation validator walks only strings. A numeric schema field in neither place is therefore a number
nobody checks. Thirteen sat in that gap — including every numeric field of the Phase-4 judgment tier
(`base_case_value_per_share`, `reverse_dcf_implied_growth`, `position_size_pct`, `expectancy`) — latent
only because Phase 4 has not run. This is the ADR-0021 defect class again: coverage that lives in a
hand-enumerated list rots as schemas grow, and the audit that found fabricated figures walking through
`what_it_does` proved where that ends.

**Decision.** Three parts, the third being the one that matters:
1. Every top-level numeric field is registered. The judgment tier's are `None` — null-only — until
   Phase-4 wiring gives each a real compute source (`reverse_dcf`, `scenarios`); relaxing an entry is
   part of that wiring, never a default.
2. Nested numeric fields get an explicit classification: `JUDGMENT_NUMERIC_FIELDS` names the bounded
   scores an agent is *permitted* to author (`Confidence.value`, `SectorScore.tailwind_score`, scenario
   probabilities) — Law 1 governs financial numbers, and the house style requires numeric confidence.
   `ScenarioLine.return_multiple` is flagged in place: it must move to a compute source when valuation
   wires.
3. `tests/schemas/test_numeric_registry.py` walks every agent schema recursively and fails when a
   numeric field is neither registered nor classified — and fails on ghost entries too, since a registry
   row naming a renamed field silently validates nothing. Adding a number now forces a decision at
   build time instead of a hole at publish time.

**Also fixed while here:** `UnitEconomicsOutput.units_today` / `units_plausible_in_7y` were required
ints, so 0 meant both "counted, and zero" and "never counted" — the `ForensicMetrics` boolean defect in
integer form. They are `int | None` now; unknown is None.

### ADR-0044 — An agent that runs and is not rendered reads exactly like one that never ran
**Context.** The phase-3 acceptance run staffed nine agents and published. `sector_analyst`,
`macro_strategist` and `unit_economics_analyst` validated, entered `agent_versions` — so the report
*named them as contributors* — and then had their narratives dropped, because `_narration` read six
agents by name. The peer comparison the sector agent exists to make reached no page at all.

**Decision.** A `## Sector and competitive position` section, composed from the agents whose work is
comparative rather than company-only, and a test asserting that **every agent the current build phase can
run** appears somewhere in the rendered narration. The test walks `config/roster.yaml`, so a new phase-3
agent fails it until it is rendered rather than being silently dropped. The Phase-4 tier has no section
either — correct while it is unwired, and raising `MAX_PHASE` in that test is how wiring it gets caught.

**Why this is the ADR-0034 failure inverted.** That ADR fixed a report that *said* three agents had not
run when they had. This is the same lie told the other way: the masthead credits an agent whose work is
nowhere in the document, and a reader has no way to tell that from an agent that was never staffed.

**Also found by the same run, and fixed:** layout-mode extraction (the whole-filing work) renders the
shareholding category row as `A  Promoter &  13  1513278 ...` with the words "Promoter" and "Group"
pushed onto continuation lines beside the wrapped digits. The pattern from ADR-0041 required the full
"Promoter & Promoter Group" phrase, so it found the row in reading-order mode and silently lost it in
layout mode — 26 registered quarters fell to 14 on merge. The conjunction is now the anchor and the rest
of the label optional; a bare `A\s+promoter` was rejected because it also matches prose like "held by a
promoter". Both extraction modes are now covered by fixtures.

### ADR-0045 — 100% coverage of the notes we found is not 100% of the notes
**Context.** STATUS §0b said substantive note coverage was 9% against a 50% floor and prescribed content
readers, one category at a time. The acceptance run reported **64%** — the merge's note-reconciliation
work had already cleared the floor — so the prescribed milestone was chasing a number that no longer
existed. Checking what was actually left surfaced something worse.

**What was actually wrong.** The enumerated note numbers had holes: 10, 36, 44, 45, 46, 50 were absent
from a 1..51 sequence, and `coverage` still reported **100%**, because it measures dispositions against
the notes the parser FOUND. Three enumeration defects, each invisible:

* **A note number may carry a letter suffix.** Alkyl Amines files contingent liabilities as
  `36a  CONTINGENT LIABILITIES AND COMMITMENTS`. The heading pattern demanded digits-then-whitespace, so
  **the entire hidden-liability disclosure was never enumerated, never dispositioned, and never read** —
  behind a perfect coverage score. For a firm whose premise is forensic reading, this is the worst class
  of defect: not a wrong answer, an unasked question wearing the costume of a complete one.
* **Sibling sub-notes were merged.** `45a` and `45b` share a number, and both `enumerate_notes` and
  `coverage` keyed on the number — so the second was discarded and the denominator was quietly wrong.
  Notes are now identified by `label` ("36a"), never by `number`.
* **Titles carry dots.** `44  VALUE OF IMPORTS CALCULATED ON C.I.F. BASIS` failed a character class that
  excluded the period.

**Decision — and the structural half is the important one.** Fixing the three patterns is worth little on
its own: the next filing will use a shape nobody anticipated. `sequence_gaps` reports note numbers missing
from the filed run, `NotesReview.unenumerated` carries them, and the report **prints them beside the
coverage figure**. A hole in a consecutively-numbered sequence is direct evidence of a note that exists and
was not read, so the reader now sees "coverage 100%" and "notes the parser could not locate: [10, 46, 50]"
together, and cannot mistake one for the other. Classified a CAPABILITY gap (ADR-0022): it lowers our
confidence and never the company's verdict.

**Result, and it is the right direction.** Enumeration went 45 → **59** notes; substantive share went
64% → **51%** and confidence 0.55 → 0.51. Finding more notes made the score *worse and truer* — the 64%
was a share of an incomplete denominator. It also puts the reading barely above the 50% floor, which
makes the note-content readers genuinely load-bearing rather than a nice-to-have: one more note found
and this report stops publishing.

---

### ADR-0046 — Extraction is reading: an LLM proposes transcriptions, the deterministic layer disposes

**Date** 2026-08-31 · **Status** accepted · **Amends the practice under** Law 1/Law 7 · **Supersedes the
statement-location role of** the `filing.py` row-locator (which remains as a fallback proposer and for
notes/CARO/Schedule III scanning)

**Context — the PC Jeweller run (the second real company, and the first known fraud).** FY13–FY17 annual
reports from the BSE archive, `as_of 2017-12-31`, through the existing walker:

* FY13–FY15 refused wholesale — figures printed in *plain rupees*, a unit the scanner does not know.
* FY16 yielded 4 P&L rows; no balance sheet; no cash flow.
* FY17 stored 25 grade-A facts **from the wrong table**: the row-locator matched the Ind AS transition
  note ("Effect of Ind AS adoption on the balance sheet as at 31 March **2016**"), mapped its
  `Previous GAAP | adjustment | Ind AS` columns to `FY17 | FY16`, and the store then carried
  `Total Assets FY16 = −6.41cr` and `Trade Payables FY17 = 3.00cr` (a note reference) — at grade A.
* The balance-sheet identity defence **passed**, because the transition table balances. Identity
  reconciliation proves a table is *a* balance sheet, never that it is *the right* balance sheet.
* The cash-flow statement — the load-bearing statement for this exact fraud — was located in none of the
  five filings. Every check returned UNAVAILABLE and the deterministic screen returned PASS with zero
  flags on a company twelve months from collapse; the publication ladder would have converted that to
  INSUFFICIENT_DISCLOSURE, wrongly charging a company whose filings print every needed row.

**The category error.** Statement *location* ("which of the fifteen balance-sheet-shaped tables in 193
pages is the audited standalone FY17 balance sheet?") and column *semantics* ("is this column the year,
the comparative, or a GAAP-transition adjustment?") are reading-comprehension questions. Hand-coded
patterns answer them wrong with full confidence, and every internal-consistency defence validates the
wrong answer, because the wrong table is also internally consistent. Each new layout family (pre-2016
plain-rupee statements, scrambled-case small-caps fonts, transition-note tables) costs another hand fix,
and n companies × m eras of typography is a fight the firm loses by design.

**Decision.** Split extraction into *proposal* and *verification*:

1. **An LLM (or a human answering a packet — ADR-0010) proposes**: which pages carry each audited
   statement (standalone and consolidated), quoting the statement heading verbatim; what each figure
   column means, quoting its label; the unit declaration, quoted; and per required metric a transcription
   of the printed value **exactly as printed**, with its page and row label. The proposer never computes,
   never converts units, never nets rows — it transcribes.
2. **The deterministic layer disposes** (`core/ingest/reading.py`), refusing any proposal that fails:
   * V1 the heading quote appears on the claimed page;
   * V2 the unit quote appears on the page and resolves in the unit vocabulary (now including plain ₹);
   * V3 every column-label quote appears on the page, and the column claimed for a fiscal period names
     that period's calendar year — the check that kills the transition-note error, whose columns say
     "Previous GAAP" and "adjustments" and name no year;
   * V4 every transcribed value appears **verbatim** on the claimed page (whitespace-normalised) — an
     LLM cannot invent a figure that survives literal search of the page it cited;
   * V5 the balance sheet satisfies assets = equity + liabilities in the declared unit;
   * V6 P&L sum ties (total expenses vs its parts) where the rows were transcribed;
   * V7 cash-flow tie (CFO+CFI+CFF ≈ Δcash) where the rows were transcribed;
   * V8 the existing cross-filing comparative quarantine (ADR-0036), unchanged, over the verified facts.
3. Only verified figures reach the fact store, `extractor_version = llm-read@…+verified`, locator carrying
   page, printed row label and the heading of the statement it came from. A refused proposal is recorded
   with the violated rule — the honest UNAVAILABLE path, never a silent blank.

**Why this does not breach Law 1.** Law 1 exists so no financial number is *authored* by a model.
Transcription is not authorship: the figure exists on an audited page, the model's claim is "this printed
string, on this page, is this metric", and the acceptance test for that claim is literal string search
plus arithmetic identities plus cross-document ties — all deterministic. The number that enters the store
is `parse(printed_string) × declared_unit`, computed by the same trusted code as ever. Law 7 is likewise
intact: proposers read extracted page *text* from bronze, never raw HTML, and agents downstream still see
gold only.

**Grade.** A verified transcription from an audited annual report is grade A: the grade belongs to the
document; the verifier is what earns the right to store at all.

**Consequence.** Generality stops being O(hand-written patterns per layout era). The wrong-table failure
class dies at V3; the fake-note-number-value class dies at V4 (a "3, 5" note reference is not the printed
figure of the payables row); plain-rupee eras become readable by declaring one more unit, not one more
parser. The walker's row-locator remains as a zero-cost proposer whose output faces the same verifier,
and remains authoritative for note enumeration, CARO and Schedule III scanning, which are pattern
problems, not reading problems.

---

### ADR-0047 — The law knows what year it is, and the notes are read the way the statements are

**Date** 2026-08-31 · **Status** accepted · **Extends** ADR-0046 · **Delivers** the first published
REJECT-class report (`reports/PCJEWELLER/2017-12-31-cccdf1de45b8/`, FORENSIC_CAUTION, confidence 0.38)

**Context.** Taking the PC Jeweller HARD_FAIL through to a published report hit three defects, all of the
same family as ADR-0046's: pattern scans asserting things reading would refute.

1. **The disclosure scan charged an FY17 filing with FY22 law.** Every Schedule III row the scanner
   demands (benami, crypto, ageing schedules, ratios…) is the MCA amendment effective 1 April 2021, and
   Key Audit Matters is SA 701, first mandatory in the FY18 report. PC Jeweller FY17 was about to be
   published with a dozen "missing mandated disclosures" it could not lawfully have carried — a false
   accusation, and the exact class the disclosure-vs-capability rule exists to prevent.
2. **The note enumerator "found" ten notes that were not notes** (transition-note sub-items, auditor
   paragraphs, AGM-notice items) and missed the real 1–52 — so coverage arithmetic would have been
   theatre with a wrong denominator, on the report where the line-by-line rule (owner directive 6) is
   load-bearing: a FORENSIC_CAUTION cannot publish below 100% note coverage (P1).
3. **The Ind AS 24 reader knew one note format** (Alkyl's) and returned "not located" on a promoter
   company whose related-party note sat plainly on p.165.

**Decision.**
- `disclosure_gaps` and `schedule_iii_gaps` take the filing's fiscal year; a requirement whose
  effective-from postdates the filing is not a gap (`DISCLOSURE_EFFECTIVE_FY`,
  `SCHEDULE_III_EFFECTIVE_FY`). Section search is casefolded — a small-caps font is not non-disclosure.
- Notes and the related-party summary join ADR-0046's propose/verify path: `verify_notes` (title on the
  claimed page, unique labels, pages and numbers non-decreasing — the filing's own ordering as the
  check) and `verify_related_party` (title and printed KMP remuneration found verbatim). Verified
  enumerations enter `walk_filing(notes_override=, related_party_override=)`; disposition, coverage,
  NOTE_CHECKS routing and the substantive gate run unchanged on top.
- `walk_filing(numeric_rows=False)` + `run_deep_dive(walk_numeric_rows=False, …)` keep the row-locator
  from re-poisoning a store a verified reading populated. The walker keeps CARO/Schedule III/section
  scanning either way.

**Result.** PC Jeweller FY17: 52 of 52 notes enumerated and dispositioned (100% coverage, 25%
substantive), the related-party note read (rent, dividend, remuneration ₹6.95cr, loans TAKEN from a
promoter — no lending to promoters, so `promoter_lending` runs and passes), `disclosure_gap` passes on
era-correct law, and the report published through every gate: FORENSIC_CAUTION on SEVERE
`cumulative_cfo_pat_low` (ΣCFO/ΣPAT 0.24) + HIGH `receivables_divergent` (+57.6% vs +16.1%), grade A
throughout, kill and rehabilitation criteria dated 2018-10-27 — a date by which, historically, the
collapse had already answered them. The dual-verdict directive now has its first FAIL publication, and
the golden set its first point-in-time true positive.

**Open, stated plainly.** CARO clause triage is still era-blind (CARO 2016 vs 2020 numbering) — it is
narration-tier input, not a deterministic flag, and is noted on the report only as a candidate; the
`cash_debt_paradox` check reads `Cash Equivalents` alone while the encumbered-cash story of this era
lives in `Other Bank Balances`; and the FY16-and-earlier combined "cash and bank balances" mapping to
`Cash Equivalents` is a definitional boundary the quarantine currently resolves by refusing FY16 cash.

---

### ADR-0048 — A period label is not a period, and a cost base is not one line

**Date** 2026-08-31 · **Status** accepted · **Extends** ADR-0046 · **Source** the Symphony Ltd
affirm-side run (the first company chosen to test FALSE POSITIVES rather than to catch a fraud)

**Context.** Symphony Ltd (BSE 517385) was picked deliberately as a hard clean case: a genuine
compounder, but asset-light with outsourced manufacturing and a large treasury book — several
superficial trip-hazards. It surfaced three defects, none of which any prior company could have shown.

**1. A stub period read as a year (severity: false positive AND false negative).**
Symphony moved its year-end from June to March and filed a **nine-month transition period** to
31 Mar 2016, saying so in its own report: *"the current financial year ended on March 31, 2017
(12 months) figures are not comparable with figures of previous financial year (9 months) ended on
March 31, 2016."* The firm had no concept of period length. Read as FY16, the stub produces:

| | as the firm would compute | like-for-like |
|---|---|---|
| revenue growth into FY16 | **−23.0%** | +2.7% |
| revenue growth into FY17 | +72.4% | +29.3% |
| receivables-vs-revenue gap FY17 | −60.8% (masked) | −17.7% |
| receivable days on a 9-month base | 42.9 | 32.1 |

A run as-of 2016 would have fired `receivables_divergent` on a clean compounder — revenue "collapsing"
against flat receivables — and a run as-of 2017 masks a gap in the other direction. One defect, both
error directions.

**Decision.** Period length becomes part of a reading's claim. `ProposedColumn.months`, verified by
**V3b**: for a FLOW statement the length must be established — declared, or stated by the column's own
words, or by the statement heading, in that precedence (the column beats the heading precisely because
a transition filing says "year ended" at the top and "Nine months ended" over the stub column) — and a
declaration the filing's own unambiguous words contradict is refused. `months_stated()` returns None
when a quote states two different lengths, which is not a corner case: split header rows mean a quote
long enough to carry a column's year may also carry its neighbour's length, and contradicting the
proposer requires an unambiguous contradiction.

Registration then **refuses to store a flow figure from a non-twelve-month period**, returning it in
`skipped_stub_flows` so the caller publishes the reason. Stocks from the same filing store normally:
**stocks are dated, flows are periodic**, and a balance sheet closing a stub period is an ordinary
balance sheet. Annualising was rejected — it is estimating a number that would carry a forensic
conclusion (owner directive 3); a hole the checks report as UNAVAILABLE is the honest alternative.

All seven pre-existing readings (PC Jeweller FY13–FY18, Alkyl Amines FY26) re-verify unchanged, every
flow period correctly inferred as 12 from the filings' own words, with no manual annotation.

**2. The cost base omitted goods bought for resale (severity: 4x wrong ratios).**
`cogs()` was materials-consumed plus the FG/WIP change. Symphony consumes ₹93.9cr of materials and
**purchases ₹293.1cr of stock-in-trade** — it outsources manufacturing, so most cost of goods is bought
finished. Inventory days read **315 against a true 75**, payable days 231 against 55, and the cash
conversion cycle 112 against 48. Not a Symphony quirk: it is wrong for every outsourced-manufacturing,
trading or franchise model. `pnl:Purchases of Stock-in-Trade` is now in the reading vocabulary, in
`READ_METRICS`, in the V6 sum check and in `cogs()`, whose formula string names every line summed.
`material_cost_ratio` is deliberately unchanged — it is correctly named and correctly computed; it is
simply not the whole cost base for such a model, which the cost-structure narration must say.

**3. A cumulative ratio fired SEVERE on a two-year window (severity: false positive).**
`cumulative_cfo_pat` computed over however many periods existed. On the two years readable from one
Symphony filing it returned 0.56 against a 0.70 floor → SEVERE → `HARD_FAIL` → the verdict ladder
short-circuits to FORENSIC_CAUTION *before* the insufficient-history rung it would otherwise have hit.
A user pointing the tool at any company with two readable years got a fraud flag.

**Decision.** `report.criteria`-style policy again: `forensic.cumulative_cfo_pat_min_periods` (3,
provisional). Below the floor the metric is **not derived** and the check reports UNAVAILABLE naming
the window — refusing at the derivation keeps every consumer honest at once rather than patching the
screen. On Symphony the screen went **HARD_FAIL → REVIEW**.

**Consequence, and the honest residue.** Symphony still returns `REVIEW` on `cfo_pat_low` (0.55) and
`high_accruals` (0.126). That is *probably* not fraud either: roughly a fifth of its pre-tax profit is
treasury income, which the indirect-method cash flow classifies under investing, so a treasury-heavy
company systematically converts below 1.0. That is a calibration question, and changing a forensic
threshold on a single observation is exactly the overfitting the golden set exists to prevent — so it
is recorded in `memory/lessons.jsonl` and left to Phase 6, not fixed here.

**Still open, named rather than fixed:** Symphony's FY13–FY15 filings report **June** year-ends, so the
`FY{YY}` label silently assumes a March close for every company. Within one company the labels stay
self-consistent, but a CAGR spanning the June→March discontinuity is wrong, `resolve_by` computes the
wrong filing date, and a peer comparison across differing year-ends compares different twelve-month
windows. The real fix is periods as first-class objects `(start, end, months)`; this ADR delivers the
`months` half, which is the half that was producing false positives.

### ADR-0049 — Periods become first-class objects: the close is read, never assumed

**Date** 2026-08-31 · **Status** accepted · **Completes** ADR-0048 · **Source** the open item ADR-0048
named rather than fixed: Symphony's FY13–FY15 filings close on **30 June**, and `FY{yy}` label
arithmetic silently assumes 31 March for every company.

**Context.** ADR-0048 made period *length* part of a reading's claim (`months`, V3b) — the half that
was producing false positives. The date half remained: within one company the labels stay
self-consistent, but the moment label arithmetic is used as *time* arithmetic it lies in three places
at once. A CAGR spanning a June→March year-end change compounds over fewer years than the labels count
(FY15–FY18 is 2.75 years lived, 3 counted — the label exponent understates growth on every such
window). `resolve_by` dates every criterion to a 31-March filing a June closer will never make. And a
peer comparison across differing year-ends compares different twelve-month windows through different
price environments under one shared label — the exact trap `peers.py` was built to refuse, one level
down.

**Decision, in four layers.**

1. **The close is part of the reading's claim (V3c).** `end_stated(text, year)` reads the closing date
   from the same verbatim quotes V1/V3 already pin to the page, in every form Indian filings print
   ('31/03/2016', '31st March, 2017', 'March 31, 2017', '30th June, 2015'). Precedence mirrors V3b:
   declared `end`, then the column's own words, then the heading — but both text sources are filtered
   to the period's **own calendar year**, which is what makes the heading fallback safe: "year ended
   March 31, 2026" can date the FY26 column and never the FY25 one beside it. A period column whose
   close cannot be established is **refused**, not assumed to be 31 March; a declaration the column's
   own unambiguous words contradict is refused; two dates in the same year are ambiguous and decide
   nothing. All eight committed readings (PCJ FY13–FY18, Alkyl FY26, Symphony FY18) re-verify
   unchanged, every close read from the filings' own words. Verified live against the real Symphony
   FY18 PDF (sha256-pinned): 0 violations, 54 of 54 registered facts dated.

2. **The store carries what the filing stated.** `facts.period_end` (nullable; guarded `ALTER TABLE`
   migrates pre-ADR-0049 stores in place). `Period(label, end, months)` with its derived `start` lives
   in `core/compute/periods.py` — pure stdlib date arithmetic, 100% covered. A screener fact has no
   stated close and stores NULL; nothing is ever inferred from a label.

3. **CAGRs compound over lived time.** `span_years(label_span, first_end, last_end, tolerance)`
   returns the *integer* label span when the stated closes agree with it (March-to-March windows keep
   the exact exponents they always had — no drift to 4.9994), and the true elapsed years when they
   contradict it beyond `periods.label_span_tolerance_days`. The corrected exponent is printed in the
   derivation's formula (`^(1/2.7516)`) so a third party can replicate from the formula alone. Ends
   unknown → label arithmetic, the status quo, at the grade the sourcing already carries.

4. **`resolve_by` and peers use the company's own calendar.** A criterion resolves against the next
   occurrence of the company's *stated* close (`DerivedSet.fy_close`) plus the filing lag; 31 March
   remains only the statutory default for a company no filing has dated. A peer row whose shared label
   closes more than `periods.peer_close_tolerance_days` apart on the two sides is **not compared**,
   with the sentence naming both dates; the growth window's exponent uses the stated closes for both
   companies at once or not at all.

**The capability-vs-disclosure line, held.** A side with no stated closes (screener-only history) is
the firm's own extraction gap, so it is *not* refused — it compares and derives exactly as before,
at its grade. Only a contradiction between stated closes changes an outcome.

**Residue, named:** the legacy `walk_filing` extraction line does not date its facts (the reading line
does); the rolling three-year incremental-ROIC windows still count labels; and quarterly labels
(`Q1FY20`) carry no close. None of these currently crosses a discontinuity in the ingested corpus.
The live June-year-end target is Symphony's own FY13–FY15 filings, not yet ingested.

### ADR-0050 — The Symphony transition ingest: the period machinery meets the real documents, and two new guards

**Date** 2026-08-31 · **Status** accepted · **Extends** ADR-0048/0049 · **Source** ingesting Symphony's
real FY13–FY17 consolidated filings from BSE (sha256-pinned), through propose→verify→register, as-of
2018-12-31 — the first run whose corpus *contains* the June→March year-end change rather than a
filing on either side of it.

**What the run validated (all live, none from fixtures).** Five readings, 280 figures, verified
first-pass against the actual page text — including the FY16 filing headed "for the nine months ended
31st March, 2016" and the FY17 filing whose split header reads "Year ended / Nine Months ended".
Registration refused the nine-month flows **from both filings that carry them** (17 each); every one
of 156 stored facts carries the close its filing stated; every CAGR compounds over the true 5.7496
years from 30-Jun-2012 to 31-Mar-2018 and prints that exponent in its formula. `receivables_divergent`
— the check ADR-0048 showed would have fired on the stub-as-year misread — passes at +13.2% against a
25% limit. `cumulative_cfo_pat`, refused at two readable years in ADR-0048, now answers over six:
**PASS at 0.79.** The screen lands on the same honest residue as before (REVIEW: `cfo_pat_low` 0.55,
`high_accruals` 0.126 — the treasury-income calibration question that belongs to the golden set).
A declared `months` on a JSON column — added incidentally in ADR-0049 — turned out to be
load-bearing: the stub filing's FY15 comparative and the FY17 filing's FY16 comparative are refused
without it, because in both the filing's own heading states the *other* column's length.

**Finding 1 — a bonus issue read as dilution (fixed).** Symphony's FY17 1:1 bonus doubled the share
count; PAT compounded 25.1% across FY12–FY18 and as-filed EPS 10.9%, so `dilution_drag` = 14.2pp and
`line_items.yaml:capital_dilution` (severity HIGH) would have published *"a material wedge —
shareholders funded part of this growth and did not keep it"* about shareholders who kept every new
share pro-rata and funded nothing. A bonus and a placement are indistinguishable from the EPS series
alone. Guard: when `balance_sheet:Equity Capital` moved more than
`forensic.dilution_drag_max_capital_change` (2%, provisional) across the window, the wedge is
**refused** with the corporate-action question, never derived — for a genuine issuer too, where the
refusal surfaces the same question instead of an unproven number. The CAGRs themselves still derive;
they are facts as filed.

**Finding 2 — the reading path had no cross-document control, and the label lied (fixed).**
`quarantine_extraction_errors` requires walker ingest results, so ADR-0046 reading facts were never
reconciled: six Symphony (metric, period) pairs disagree across consecutive filings beyond any
restatement band — FY13 materials ₹165.88cr vs ₹41.15cr (the FY13 filing prints traded-goods
purchases inside materials consumed; FY14 splits them), FY15 other expenses ₹163.04cr vs ₹107.90cr
(the FY17 ad-spend reclass reaching back) — and both sides sat at grade A.
`quarantine_store_contradictions` is the store-driven sibling: works for facts however they arrived,
point-in-time filtered, removes both sides. And where **both** sides carry a `+verified` extractor —
every figure found verbatim on its page, statements internally reconciled — the honest kind is
**`re_presented`**, not `extraction_error`: the company printed different figures for the same
period, and confessing to a misread we demonstrably did not make would be its own false claim.

**The restatement radar's first real catch:** 49 quiet revisions logged across the six filings, led
by FY15 revenue 578.89 → 525.87 (₹53cr of discounts moved from other expenses into a revenue
deduction — a 9.2% presentational cut the resolver now correctly serves point-in-time).

**Residue, named:** (a) revenue basis is mixed across the FY12–FY18 window — FY12–FY14 gross of the
discounts the company later netted, never restated that far back, so the 17.6% CAGR slightly
overstates like-for-like growth and only note-level reading could reconcile it; (b) ROIC is
unavailable through the reading path (no Operating Profit / Tax % rows in the vocabulary, and a
debt-free company prints no borrowings row to transcribe — absence-means-zero needs a claim type the
verifier cannot yet check); (c) `detect_models` returns nothing for Symphony, so only the universal
playbook ran; (d) bonus-vs-issuance stays open until a corporate-action source exists. All are
capability gaps and none moved a verdict.

### ADR-0051 — When a company closes its books is read, never assumed (parallel line; committed as "ADR-0049" in `7545c68`)

**Date** 2026-08-31 · **Status** superseded by ADR-0049 + ADR-0054 (the branch merge) · **Completes** the open item ADR-0048 named

**Context.** ADR-0048 fixed the *length* half of "a period label is not a period" and named the other
half as open: Symphony Ltd closed on **30 June** through FY15 and on **31 March** from FY17, so `FY15`
means a different twelve months for it than for almost every other Indian company. `FY{YY}` silently
assumed a March close for everyone. The damage is narrower than the stub's — it does not manufacture a
forensic flag — but it is real: a growth rate across the change compares windows that do not line up
(Symphony FY14→FY18 is four years and nine months of trading wearing a five-year label), `resolve_by`
dates a criterion against the wrong filing, and a peer comparison across differing year-ends compares
different twelve-month windows while looking perfectly ordinary.

**Decision.** The period end becomes a stored, verified property of a fact.

* `facts.period_end` (ISO date, `''` when the source did not state it) with an `ALTER TABLE` migration,
  so a store written before the column is still readable and its facts honestly say "unknown".
* `ProposedColumn.ends`, verified by **V3c**: the declared end must be a date the column label or the
  statement heading actually *names* — month and year, spelled ("30th June, 2015") or numeric
  ("30/06/2015", matched as a whole date so a stray `06` elsewhere in a quote cannot vouch for a June
  close) — and its year must agree with the column's own FY label.
* `CompanyFacts.fiscal_close_month()` / `.fiscal_calendar_change()` read the calendar off the facts.
  **Only periods whose close month is actually known participate**: an unstated close is unknown, never
  assumed to agree, so a fact set with no end dates can never fabricate a change.
* `derive_metrics` refuses every rate-of-change metric spanning a moved year-end — `revenue_cagr`,
  `pat_cagr`, `eps_cagr`, `expense_cagr`, `dilution_drag`, `opm_delta_window` — with the reason naming
  both months. Single-period metrics (days ratios, margins, single-year conversion) are untouched,
  because a ratio of two figures from the *same* statement does not care when the year ended.

**Why refuse rather than adjust.** The same reasoning as the stub: annualising or pro-rating is
estimating a number that would carry a conclusion. A refusal with the reason printed is an honest gap
that the report already knows how to publish.

**Result on real filings.** Symphony FY14/FY15 register with `2014-06-30`/`2015-06-30` and FY17/FY18
with March ends; `fiscal_calendar_change('FY14','FY18')` returns `(6, 3)` and all four growth metrics
are refused, naming the June→March move. Every single-period metric still computes. All seven prior
readings (PC Jeweller FY13–FY18, Alkyl Amines FY26) re-verify with zero violations and keep their
CAGRs — their end dates are simply unstated, which the calendar logic treats as unknown.

**And the affirm answer the run was after.** With the fuller, calendar-aware window,
`cumulative_cfo_pat` reads **0.71 — a PASS** over FY14–FY18, against the **0.56 SEVERE** the two-year
window produced before ADR-0048's floor. The arc is the case for both ADRs in one line: *HARD_FAIL
(false positive) → REVIEW (window guard) → cumulative PASS (honest window)*. More correct data moved
the verdict toward the truth, and the guards prevented a confident wrong answer in the meantime.
Symphony still returns **REVIEW** on single-year `cfo_pat` 0.55 and `high_accruals` 0.126 — the treasury
effect recorded as a calibration lesson for the golden set, deliberately not fixed by moving a
threshold on one observation.

**Open, and worth stating.** Refusing a CAGR across a calendar change is the safe answer, not the best
one: a growth rate over the longest sub-window with a *consistent* calendar (Symphony FY17→FY18) is
computable and would be more useful than nothing. Left for when a real run needs it.

---

### ADR-0052 — The lender path was asserted, not built; and cash conversion is not an earnings-quality test for a lender (committed as "ADR-0050" in `bc8f3c4`)

**Date** 2026-08-31 · **Status** accepted · **Extends** ADR-0002/0012 · **Source** the CreditAccess
Grameen FY25 run — the first lender's filing the firm has ever read

**Context.** `quality.py` has carried seven lender checks since ADR-0002/0012, `config/forensic_playbooks.yaml`
has selected them by business model, and `VALIDATION_TIER0.md` has been cited as evidence the firm works
on lenders. All of that was true of the *check functions*. The *pipeline* could not read a lender at all,
in three independent places:

1. the reading vocabulary had no loan book, no credit-cost line, no lender borrowings family;
2. `statement_shape` never computed `loan_book_to_assets` or `interest_income_to_revenue`, so
   `detect_models` could not return LENDER however plainly a filing said so — the entire ADR-0002
   branch, suppression included, was unreachable from a real document;
3. `checks.py` had **no evaluator for any of the seven**, so each fell through to the
   "no evaluator wired for this check" branch.

The honest reading of the old state: the firm reported lender checks as UNAVAILABLE and could never have
done otherwise.

**Decision — build the path.** Lender line items in the reading vocabulary
(`balance_sheet:Loans`, `pnl:Impairment on Financial Instruments`, `pnl:Interest Income`, and the
`Debt Securities` / `Borrowings (other than debt securities)` / `Subordinated Liabilities` family, which
compose into `balance_sheet:Borrowings` — the composition rule generalised to N parts and ordered so the
three-part lender form is tried before the current/non-current one). `statement_shape` computes the two
lender ratios. `checks.py` evaluates the two checks whose inputs are on the **face** of the statements —
`provision_book_divergent` and `reserve_suppression`, both needing only the credit-cost line and the loan
book — and gives the other five a **specific** reason naming the note that would answer them, because
"we cannot read this yet" and "the company did not disclose it" are different findings and only one is
about the company.

**Result: the pipeline independently reproduced the hand-computed verdict.** Reading the audited
consolidated statements, with no figure typed in:

| `VALIDATION_TIER0` (hand-fed, investor presentation) | this run (read from the AR) |
|---|---|
| provision divergence gap 3.30 ≫ 0.50 → FLAG | impairment **+327.1%** vs book **−3.3%**, gap **3.30** → FLAG |
| reserve suppression: rate rose → no flag | **1.80% → 7.95%** (raised) → PASS |
| gain-on-sale → UNAVAILABLE | UNAVAILABLE, naming the revenue note |
| **REVIEW** | **REVIEW** |

The small differences are a real and worth-recording sourcing choice: `VALIDATION_TIER0` used gross loan
portfolio (25,948 → 25,948/26,714, −2.9%) from the presentation; the pipeline uses **net loans from the
audited balance sheet** (24,274.45 → 25,104.99, −3.3%). The audited figure is the better source and the
conclusion is identical. LENDER was detected at a loan book **87% of assets**, and the five ADR-0002
suppressions appeared as NOT_APPLICABLE on a real filing for the first time.

**And the defect the run found.** `cumulative_cfo_pat` and `cfo_pat` were UNIVERSAL, so they applied to
lenders. Under Ind AS 7 a lender's loan disbursement and collection **are** its operating activity, so
CFO/PAT measures book growth, not earnings conversion. CreditAccess reads:

* FY25: CFO 1,125.24 / PAT 531.40 = **+2.12** — a comfortable PASS, and only because the book *shrank* 3.3%;
* FY24: CFO −4,733.78 / PAT 1,445.93 = **−3.27** — far below the 0.70 floor, on a lender doing nothing
  but growing.

Same company, same accounting, opposite verdicts, decided entirely by the direction of the book — and
`cumulative_cfo_pat_low` is a **SEVERE** flag, so *every growing lender* would be flagged for growing.
Both are now suppressed for LENDER and BANK, which is ADR-0002's own reasoning ("Beneish and accruals are
invalid for a lender") applied to the check that had escaped it. A lender-appropriate earnings-quality
measure is a golden-set calibration question and is recorded as such rather than invented here.

**A note on the verifier.** Three of my own transcription errors were caught before anything reached the
store: a column-label quote that did not appear on the page, and four cash-flow rows I attributed to the
wrong page. The propose/verify split is doing its job on its author, which is the strongest evidence it
will do it on a model.

---

### ADR-0053 — "We could not look" is not "they did not disclose" (committed as "ADR-0051" in `d04dac7`)

**Date** 2026-08-31 · **Status** accepted · **Extends ADR-0022's rule from line items to checks and to
the verdict ladder** · **Found by** generalising ADR-0050

**Context.** ADR-0050's lesson was that a capability can look finished at every layer and be unreachable
from a real document. Generalising it, an audit found four more checks a playbook can select with no
evaluator (`contract_asset_divergent`, `guarantees_heavy`, `capitalised_cost_heavy`,
`adjusted_ebitda_gap`) — covering SERVICES_IT, EPC_INFRA and REAL_ESTATE. But the audit surfaced
something worse than the wiring gap.

**The prohibited failure, live.** `CheckEvaluation.unavailable_share` counted every unrunnable check
alike, and the verdict ladder turned that share into `INSUFFICIENT_DISCLOSURE` with the rationale *"the
inputs are public by law, so the gap is the finding"*. On CreditAccess Grameen — a lender that discloses
its asset quality in full — **67% of the playbook was unavailable and 0% of it was the company's doing**:
every one of those checks needs a note this firm does not read. The report would have accused a
compliant company of withholding public information. `GapKind`'s own docstring forbids exactly this
("otherwise the firm rejects every business it cannot yet read and calls that rigour"); the distinction
had been applied to line-item questions since ADR-0022 and never to checks.

Two further rungs had the same defect: notes coverage and substantive share both produced
`INSUFFICIENT_DISCLOSURE` from a `NotesReview` whose `scanned` flag was **False** — "0% of 0 notes carry
a substantive disposition" is a sentence about a filing nobody opened.

**Decision.**

1. `CheckRecord.gap: GapKind`, and `_Recorder.unavailable(..., gap=GapKind.CAPABILITY)` — **CAPABILITY
   is the default**, so a caller must state positively that it looked in the right place before the
   company can be held responsible. The reason's wording follows the classification: a report never says
   "not disclosed" about a note it never opened.
2. `disclosure_gap_share` (verdict-moving) is split from `unavailable_share` (confidence-moving, and
   still counting both kinds — whoever the gap belongs to, the firm knows less for it).
3. `INSUFFICIENT_DISCLOSURE` requires the **disclosure** share to breach the ceiling, and names the
   checks. The notes rungs are gated on `scanned`.
4. A new verdict, **`INSUFFICIENT_EVIDENCE`**, for the case the split exposes. Removing the false
   accusation alone would have replaced it with a false *thesis*: the screener-only regression run
   promptly returned `QUALITY_WRONG_PRICE` — a business judgment off a playbook that ran 40% and never
   opened a filing. The new rung sits after the disclosure rungs (a genuinely opaque company is still
   reported as opaque) and before every rung that asserts anything about the business.

**Result.** CreditAccess moves from `INSUFFICIENT_DISCLOSURE` to `INSUFFICIENT_EVIDENCE`: *"67% of the
applicable playbook could not be evaluated, and 67% of it for want of this firm's own reach rather than
the company's disclosure — no judgment about the business is supportable yet"*. That sentence is true;
the one it replaces was false about the company and true about us. The screener-only path — which
STATUS §6b had already caught empirically on Alkyl Amines ("INSUFFICIENT_DISCLOSURE — the opacity was
ours") and worked around by improving extraction — is now correct by construction rather than by luck.

**And the guard.** `tests/pipeline/test_check_coverage.py` runs the real evaluator over every model's
real playbook and asserts each selectable check either has an evaluator or is declared in
`UNIMPLEMENTED_CHECKS` with what it specifically needs. It is behavioural, not textual, so a refactor of
the dispatch cannot fool it; it was verified by unwiring a lender check and watching it fail. The four
unimplemented checks are declared rather than built: the lender path is the pattern — wire an evaluator
when a company that needs it is actually run, so it is validated against a document instead of an
expectation.

### ADR-0054 — The second branch divergence, and what the merge kept from each line

**Date** 2026-08-31 · **Status** accepted · **Records** the merge of
`claude/equity-research-architecture-3600e7` (`7545c68`..`d04dac7`) into the trunk at `0f68c24`

**What happened.** Two autonomous sessions ran the same priority function from the same ADR-0048 base
and independently built the same top item — periods as first-class objects — converging on the same
`facts.period_end` column, colliding on ADR numbers for the second time (both minted an ADR-0049 and
an ADR-0050), and independently hand-transcribing the same Symphony FY15 annual report. The first
divergence (recorded under the ADR-0036–0038 collision) was an accident of a gitignored `reports/`
directory; this one was structural: two loops, one backlog, no shared coordination point. The process
fix is operational — one session owns the trunk — and this ADR is the numbering record:
`7545c68`'s "ADR-0049" is filed here as **ADR-0051**, `bc8f3c4`'s "ADR-0050" as **ADR-0052**,
`d04dac7`'s "ADR-0051" as **ADR-0053**.

**What the merge kept, and why.**

* **Periods: the trunk implementation (ADR-0049) stands.** Both lines verify the close against the
  filing's words; the trunk's V3c additionally *derives* it (declared → column words → heading, each
  filtered to the column's own calendar year) and **refuses a column whose close cannot be established
  at all** — the sibling's V3c checked only closes the proposer volunteered, so an undeclared column
  silently stored an unknown close. The sibling's `Period` storage type (`''`-sentinel string) gave way
  to the trunk's typed `date | None`.
* **The one analytical disagreement, resolved for correction over refusal.** Across the June→March
  change the sibling refused every window growth rate ("the windows do not line up"); the trunk
  computes them with the exponent set to the true elapsed years between the stated closes (5.7496 for
  FY12→FY18) and prints that exponent in the formula. Refusal was argued from the estimation ban, but
  no figure is estimated: both endpoint flows are used exactly as filed and each covers every season
  exactly once — only the *clock* is corrected, from a label count the filings contradict to the count
  they state. Refusing would discard a well-defined answer the company's own filings support.
* **The sibling's lender path lands intact (ADR-0052)** — vocabulary, three-part composed borrowings
  (tried before the current/non-current pair), shape-detector inputs, playbook branch, CreditAccess
  reading — re-keyed to the trunk's `end`/typed-date reading layer.
* **The sibling's verdict fix lands intact (ADR-0053)** — a check whose inputs the firm merely could
  not read reports the firm's gap, never the company's non-disclosure. The trunk's own Symphony run
  had printed the symptom it fixes.
* **The Symphony FY15 double-transcription became a free audit.** 48 of 50 shared figures agree to the
  digit across two blind readings of the same PDF. Both disagreements are ONE semantic choice: the
  sibling mapped the balance sheet's "Cash and Bank Balances" row to `Cash Equivalents`; the trunk
  takes the cash-flow statement's own "Cash & Cash Equivalents at the end of the year" row. The
  balance-sheet row includes earmarked accounts and, in FY16, ₹24.00cr of fixed deposits — the FY16
  gap is ₹46.48cr printed against ₹18.21cr of true C&CE, which would corrupt the cash-yield check.
  The trunk mapping stands; the trap ("a vocabulary row is the row the filing MEANS, not the row that
  sounds like it") is the lesson worth keeping.

**Residue.** The sibling's `fiscal_close_month`/`fiscal_calendar_change` helpers and its refusal tests
were adapted to the trunk semantics rather than dropped — the calendar-change *fact* still matters for
narration even where the rate is computable. The trunk's ADR-0050 dilution-drag guard and the
sibling's ADR-0053 gap-kind fix overlap in spirit (both stop a firm-side gap reading as a company-side
finding); neither subsumes the other.

### ADR-0055 — The reading path reaches the CLI, and the acceptance run caught three defects green tests never would

**Date** 2026-08-31 · **Status** accepted · **Extends** ADR-0046/0050/0054 · **Source** wiring
`firm read-packets` / `--readings` and then actually driving Symphony through it to a published report

**The wiring.** `ingest_readings_manifest` takes a filings manifest to verified, dated, grade-A facts:
bronze-cached PDFs fetched from the manifest's `source_url` when absent and REFUSED unless they hash
to its pinned sha256; every reading verified against the actual page text at ingest (a reading that
fails today's verifier never registers, however it got on disk); Law 3 at the document level (a filing
after `as_of` is not even opened); every non-contribution an explicit status — `no_reading`,
`refused` (violations attached), `pdf_mismatch`, `not_yet_published` — never a silent skip.
`firm read-packets` writes proposer packets for exactly the filings that lack readings;
`deep-dive --readings` and `packets --readings` share the ingest and set `walk_numeric_rows=False`,
so the walker cannot re-register unverified rows beside verified ones and the agent packet remains
the run's evidence, not a variant of it.

**Defect 1 — a hardcoded window amputated the evidence (the serious one).** `start_year: int = 2015`
in `load_company_facts` (and four siblings) silently excluded Symphony's ingested FY12–FY14 filings.
Cumulative cash conversion computed over the truncated tail: **0.64, SEVERE, screen HARD_FAIL** — a
fraud-class flag against the clean company, out of a store that held the full passing history at
grade A. The three-period minimum ADR-0048 added could not see this: the truncated window HAS three
periods; the defect is exclusion, not brevity. Fixed: `start_year=None` now means **the window is
what the evidence covers** (`FactStore.earliest_annual_year`, Law-3-filtered); an explicit year
narrows deliberately; the constant is gone from every default. Full run: 0.79, PASS, screen REVIEW.

**Defect 2 — a wrong statutory date, charging compliance as concealment.** The mandated-disclosure
scan flagged Symphony FY18 for missing Key Audit Matters. SA 701 was deferred by ICAI to audits of
periods beginning on/after 1 April 2018 — FY19 is the first AR that owes a KAM section — and the
empirical check settles it: Symphony's Deloitte-audited FY18 report contains zero occurrences of the
phrase, and a Big-4 auditor does not skip a mandatory section. `DISCLOSURE_EFFECTIVE_FY` corrected to
2019. A statutory date is a fact to verify against filings, not to recall from memory.

**Defect 3 — the citation grammar excluded most audited rows (third instance of its class).** The
`[fact:...]` token's character class had already been widened once for the colons every namespaced id
carries; it still excluded SPACES, and most raw filing metrics are multi-word
(`pnl:Cost of Materials Consumed`) — so an agent quoting an audited row verbatim could not cite it at
all, and the validator was once again satisfiable only by not writing such numbers. The delimiter is
now the bracket, not a character class; unknown ids still fail loudly, and the value check is
untouched.

**The acceptance run** (`reports/SYMPHONY/2018-12-31-65e0f6068121`, packets under
`runs/SYMPHONY-packets/`): six filings, 284 verified facts, stub flows refused, six re-presentations
quarantined, 43 notes enumerated, three agents through every discipline gate — the gates rejected
four successive drafts of this run's own answers (uncitable space-bearing ids, policy thresholds
written as digits, a citation to the filing the resolver does not serve) before passing the fifth.
Verdict **FORENSIC_CAUTION** off the deterministic REVIEW + one HIGH flag. That flag,
`cfo_pat_low` 0.55, is the treasury-classification arithmetic named in ADR-0048's residue: a
treasury-heavy company converts below the floor in any single year while converting 0.79
cumulatively. The verdict is conservative in the right direction and the prose carries the benign
explanation, but the class — every treasury-heavy clean company earning FORENSIC_CAUTION — is now the
**top golden-set calibration question**, recorded again rather than threshold-hacked on n=1.

**Residue:** ROIC and the cash-interest check stay unrunnable through the reading vocabulary (no
operating-profit/tax/interest-income rows), which caps Symphony's evaluable playbook at 70% and its
note substantive share at 12% — the report says so on its face.

**Addendum (same day) — the sharpest test came alive.** The residue above said the cash-interest
check was unrunnable through the reading vocabulary. It was a one-row gap: `cashflow:Interest Income`
(the investing section's positive "Interest Received" line — not the negative operating add-back) is
now in the vocabulary and transcribed into all six Symphony readings from their own pages, and
`backfill_external_inputs` fills it from the store on the same period as the cash balance it divides.
On the re-run, "is the cash real?" answers **PASS: implied yield 13.41% on average cash-and-bank
against the 2.60% floor**, five verified inputs cited; unavailable checks fell 30% → 20% and the
mandated-disclosure scan passes. The verdict stays FORENSIC_CAUTION off single-year `cfo_pat_low` —
the published report now carries the direct counter-evidence beside the flag, which is exactly the
shape the golden-set treasury-conversion calibration question needs
(`reports/SYMPHONY/2018-12-31-e2051e41d639`).

### ADR-0056 — Notes are read the way statements are, and trusted because they reconcile (sibling line, committed as "ADR-0052" in `b6f0244`)

**Date** 2026-08-31 · **Status** accepted · **Extends** ADR-0046 · **Enforces** ADR-0038's standard ·
**Closes** two of the five note-level gaps ADR-0052 (its "ADR-0050") declared

**Context.** ADR-0053 (its "ADR-0051") left CreditAccess at 67% of its playbook unavailable, every point of it the firm's
own reach: the checks that would judge a lender's asset quality live in the loans and ECL-staging notes,
and the pipeline read only the face of the statements. The same is true of contingent liabilities,
segment revenue and every other note — the largest remaining capability gap in the firm.

**The hypothesis worth testing first.** A note table is a table with a heading, columns and figures, so
the ADR-0046 verifier ought to read one already. Tested against CreditAccess's note 7: mostly true, and
the exceptions are informative.

* **V3 (columns name their year) and V4 (the value is on the page) work unchanged.** Note tables label
  their columns exactly as statements do.
* **V1's year test cannot apply.** A note heading names a *note*, not a period — "7 Loans", "46
  Contingent liability" — so a note is identified by its **label** instead, which must appear in its own
  heading.
* **V1's basis test cannot apply either.** A note heading never says "consolidated"; the *section* does,
  and the filing prints the same note twice under both bases.

**Decision.** `statement="note"` with a `note_label`, and — replacing both dropped tests with something
stronger — **the reconciliation gate**: a note figure mapped to a face metric (`NOTE_RECONCILES_TO`)
must equal that metric as already stored, read from the store so the comparison is against a figure
verified independently from a different page. This is ADR-0038's standard ("a note is read when it
reconciles to the face of the statements") turned from a principle into a gate. It also settles the
basis question better than a heading would: a standalone note does not tie to the consolidated face
figure, so a note that reconciles has *demonstrated* which statements it belongs to rather than
asserting it.

The gate was verified by corrupting a note to claim the gross loan figure as the net one — a value
genuinely printed on the page, which every page-level check therefore passes. Only the tie to the
balance sheet caught it.

**Result — the lender family becomes real.** With notes 7 and 7(A) read (Stage-3 gross composed in
trusted code from the group and individual lending books, both rows named in the locator):

| check | outcome | detail |
|---|---|---|
| `gnpa_drift` | **FLAG** | Stage-3 share of the gross book **1.18% → 4.79%** (+3.61pp vs a 1.00pp limit) |
| `provision_coverage_low` | **PASS** | allowance ₹1,308.63cr on Stage-3 gross ₹1,225.61cr = **107%** coverage |

The FY24 figure of **1.18% reproduces the GNPA CreditAccess discloses itself** — computed here from the
staging note rather than taken from the company's summary, which makes it an independent corroboration
of the reading. (FY25 reads 4.79% against their stated 4.76%; the small gap is a denominator definition,
and the locator names exactly what was computed.) The capability gap fell from **67% to 50%**.

**The calibration question this raises, recorded and NOT acted on.** The verdict moved to
`FORENSIC_CAUTION`, because `gnpa_drift` is HIGH severity and one HIGH flag escalates the ladder. Yet
every corroborating check says honest recognition rather than concealment: reserve suppression PASSES
(the credit-cost rate was *raised* 1.80% → 7.95%), and coverage exceeds the impaired book at 107%. That
is ADR-0012's own distinction — rising provisions are honest, a *cut* is the tell — and the screen
respects it while the ladder does not: **the ladder reads flags, not the pattern of flags.** Whether one
HIGH flag should escalate when the exculpatory checks all pass is exactly the kind of question a single
observation must not answer, so it goes to `memory/lessons.jsonl` for the golden set. The published
checklist shows all six checks, so a reader sees the whole pattern either way, and FORENSIC_CAUTION is
by construction an invitation to investigate rather than an accusation.

**Merge note (ADR-0054 continued).** This landed from the sibling session after the trunk merge — the
loop over there kept firing after the owner paused it (a scheduled self-wakeup; now stood down at the
owner's instruction) and minted "ADR-0052" a second time. Filed here as ADR-0056 with its tests
adapted to the trunk's typed `end` field. The reconciliation gate composes with the trunk verifier
unchanged: V3c dates a note's columns like any table's, and the note's basis is proven by the tie to
the face rather than claimed by a heading.

### ADR-0057 — The golden set lands on the trunk, and its first run maps what the trunk cannot do

**Date** 2026-08-31 · **Status** accepted · **Ports** the eval work of a THIRD parallel line
(`claude/geometry-anchored-pdf-extraction-47ba81`, its "ADR-0059..0064") · **Extends** ADR-0054's
process record

**The third line.** A third session had diverged from the pre-ADR-0046 base (`c9863ab`) and built,
among 8.6k insertions: geometry-anchored PDF extraction, a third lender implementation, a
point-in-time disclosure rulebook, and — the part ported here — the golden set: `firm eval` /
`firm register`, `core/eval/{golden,run}.py`, seven cases with human-verified facts and
pre-registered verdict bands, and `docs/GOLDEN_SET.md`. Its design survived its own first contact:
wave 1 caught five facts fabricated by the case author (the `method` field made them checkable), and
wave 2's register check caught an invented citation URL. The two-assertion scoring — EXTRACTION
(verified facts reproduced) and JUDGMENT (verdict in band) scored apart — is what makes improving an
extractor distinguishable from improving calibration.

**What was ported and how.** The eval core, register adapter, cases, manifests and design doc land
almost verbatim; `deterministic.py` (their ADR-0060 insight — one deterministic sequence, three
callers) was REWRITTEN against the trunk pipeline (detect_models/build_playbook, walker AND
ADR-0055 reading routes, both quarantines) rather than ported, because their version called their
own classify/screen APIs. All 17 pinned PDFs were re-fetched and hash-verified; five manifest
`source_url`s were directory stubs that could not reproduce their own pins — repaired with the BSE
archive URLs that do, since a pin without a reproducing URL is provenance theatre.

**The first trunk run, unvarnished:** 4 of 7 in band (three clean ALKYLAMINE years, plus FY23 as the
pre-existing CAL-1 threshold question). Three failures, recorded with tracking ids rather than
weakened bands:
* **PORT-1** (CREDITACC-FY26, FIVESTAR-FY26): the RBI IRACP asset-quality table extraction exists
  only on the unported third line; the trunk's ADR-0056 note-reading covers staging under different
  ids and different filings. The lender screen-calibration fixes on that line are likewise unported.
* **PORT-2** (PCJEWELLER-FY21): the FY19-FY21 filings yield ZERO facts through the trunk row-locator
  — the sibling's geometry extraction read them; an ADR-0046 verified reading would too.
* **EVAL-1**: exposed by PORT-2 — the bare forensic screen returns PASS on an empty read. The
  verdict ladder above it refuses honestly (INSUFFICIENT_*), but the screen alone overclaims, and
  the eval scores the screen. A screen-level insufficiency guard is an open design question, not a
  patch to apply blind.

**What was NOT ported, deliberately — the owner's call, not the loop's.** The third line's
geometry-anchored extraction and its lender/classify implementation overlap the trunk's chosen
propose→verify architecture and the ADR-0052/0056 lender path. Merging three lender implementations
silently is how ADR-0054 happened. The branch stays intact for that decision.

### ADR-0058 — What the golden set's first diagnostic pass taught the architecture

**Date** 2026-08-31 · **Status** accepted · **Extends** ADR-0057 · **Method** observe → diagnose →
generalize → fix → re-run, once per failure, bands never touched

**EVAL-1, in two layers (the safety one).** The bare forensic screen minted PASS on an empty read —
and then, with the zero-floor fix in, minted PASS again on a 1-of-10 read where the single evaluated
check was a text-section scan. Root cause: `ForensicMetrics`' not-evaluated defaults erase the
evidence-quantity information exactly at the boundary where the verdict is minted — the same boolean
ambiguity the checks layer fixed long ago, surviving one level up. The screen now carries the claim
itself: INSUFFICIENT on zero checks ran (unconditional), and below
`forensic.screen_min_ran_share` (0.25, provisional) of the applicable playbook. The fix converted two
live wrong verdicts at once: PC Jeweller's false PASS and CreditAccess's false HARD_FAIL (lender
misread as a non-financial, judged on the sliver that ran).

**PORT-2 closed through the trunk's own architecture.** PC Jeweller FY19–FY21 verified readings —
198 figures, all page-anchored, all V-checks — took the positive case from "zero facts, screen PASS"
to **extraction 6/6 and HARD_FAIL inside the pre-registered band**: cumulative CFO/PAT deeply
negative with inventory absorbing the gap, the exact pre-collapse pattern. The set's one positive is
now caught from primary sources, not from memory of the story.

**PORT-1 closed the same way, and the diagnosis ran three layers deep.** CreditAccess FY26 authored
as statements + loans + staging notes through the ADR-0056 reconciliation gate (64 figures). Then,
in order: (1) `reserve_suppression` fired on a credit-cost cut into a book whose Stage-3 share FELL
a third — the check's own spec (ADR-0012: Sezzle cut into RISING delinquency) always needed the
stress direction, and the staging series the trunk now reads finally supplies it; with no staging
the cut alone still flags, the conservative direction. (2) `promoter_lending` turned a regex
category read ("the note mentions guarantees") into a SEVERE siphoning accusation with no amount
and no direction — ground truth on p.167 is KMP salaries of ₹2.57cr and the parent relationship. A
category is not a finding: category-only now reports a CAPABILITY gap naming what a flag would
need; disclosed-nothing-but-remuneration still PASSes (the real Alkyl finding). (3) `disclosure_gap`
charged an NBFC for CWIP and trade-receivables ageing schedules — rows its Division III balance
sheet does not carry; an ageing schedule is owed only for a face row the company has, answered from
the store. Case ends **REVIEW, in band, extraction 6/6**, with the expected disclosure_gap on
undisclosed_income intact.

**The pin system paid for itself.** Two different documents both named `CREDITACC-AR-FY25.pdf` —
the eval manifest pinned one, the verified reading was authored against the other — and the
refuse-on-hash-mismatch gate held: nothing wrong was read, the reading refused loudly, the manifest
was re-pinned to the document the reading reads. Also fixed en route: glued header text
("As atMarch 31, 2026") defeated the date parser's word boundary — a full month name as a glued
token's suffix now parses.

**Scorecard: 4/7 → 5/7 in band, positives 1/1, hard_recovery 1/1, zero regressions.** Open and
tracked, not hidden: CAL-1 (the FY23 cash-yield floor missed by 0.05pp — a threshold question the
invariants forbid resolving on one observation) and PORT-1b (Five-Star's readings unauthored; behind
them a provision-coverage floor calibrated on microfinance applied to a secured lender). Every
verified fact in the closed cases was re-verified against pages during authoring; human sign-off on
all seven remains open for the owner.

**The architecture lesson.** Every judgment failure decomposed into a MISSING INPUT, not a wrong
threshold: the screen lacked evidence-quantity; reserve_suppression lacked stress direction;
promoter_lending lacked amounts; disclosure_gap lacked face-row existence. The golden set's real
output is a list of inputs the verdict layer was silently doing without — which is exactly what a
calibration instrument should find before anyone tunes a number.
