# ADAPTIVE_FORENSICS.md — business-model-adaptive checks + line-by-line note coverage

> **Owner directive (2026-07-30).** The two reference reports were examples, not the goal. There are
> n companies with n business structures; the system must **adapt its investigation to the structure of
> the business it is reading**, and must investigate the financial statements and notes-to-accounts
> **line by line** — not by keyword-spotting. Ratified as ADR-0017. This doc is the spec; code lands
> incrementally under the ADR-0002/0012 pattern (deterministic, thresholds in config, 100% tested).

## 1. The principle: detect the model, then select the playbook

ADR-0012 already established "checks apply by business model, not sector label." This generalises it:

**Step 1 — deterministic model detection** from the shape of the statements (no LLM):
loan book / total assets · interest income / revenue · contract assets present · inventory intensity ·
order book disclosed · rental/lease share · R&D share · gross-vs-net revenue pattern. Output: one or
more model tags. A conglomerate gets multiple tags → the union of playbooks, segment-level where
segment data exists.

**Step 2 — playbook selection**: each model tag maps to (a) which universal checks apply / are
suppressed, (b) model-specific checks, (c) which notes matter most for line-by-line priority.
Config-driven (`config/forensic_playbooks.yaml`, to be added with the code) — never hardcoded.

## 2. The playbook matrix (initial 10 models, India-first)

| Model (detect by) | Where manipulation typically hides | Model-specific deterministic checks (build) | Existing checks that apply |
|---|---|---|---|
| **MANUFACTURER** (inventory+PPE heavy) | expense capitalisation, CWIP games, channel stuffing, RM-spread vs margin games, export-incentive accruals | receivable-days & inventory-days divergence vs revenue (SPEC §5 — **not yet coded**); margin-vs-input-commodity divergence (use `divergence.py` + commodity series); other-income/PBT share (**not yet coded**) | cash-reality set, accruals, Beneish, CWIP ageing |
| **LENDER** (loans/assets high) | provision timing, evergreening, off-book via DA/securitisation, gain-on-sale upfronting | DA/assignment-income share of PAT; ECL stage-migration drift; implied-yield vs stated-rate consistency | full originate-to-sell set (ADR-0012), GNPA/PCR/restructured (ADR-0002) |
| **BANK** | divergence vs RBI inspection, treasury-income dependence, SMA/restructured bucket games | RBI divergence-disclosure flag; other-income (treasury) share of PBT | lender set; Beneish suppressed |
| **EPC / INFRA** (contract assets, order book) | POC revenue aggressiveness, unbilled revenue, SPV maze, guarantees to SPVs | contract-assets growth vs revenue growth; book-to-bill realism; retention + mobilisation-advance trends; guarantees-to-SPVs vs net worth | accruals, cash-reality, CWIP |
| **RETAIL / CONSUMER / JEWELLERY** | channel stuffing, franchise receivables, inventory valuation (jewellery = the classic), cash-sales opacity | same-store vs total growth gap; inventory-days divergence; (jewellery) inventory+pledge+WC-debt triple | cash-reality, accruals, pledge trajectory |
| **TRADER / DISTRIBUTOR** | **gross-vs-net revenue** (agency booked as principal → fake scale), circular trading, common counterparties both sides | near-zero gross margin on exploding revenue flag; counterparty overlap (needs entity graph) | cumulative CFO/PAT (usually the tell) |
| **IT / SERVICES** | unbilled revenue, acquisition accounting, revenue-per-employee inflation | unbilled-revenue vs revenue divergence; goodwill/intangible share post-M&A; DSO drift | accruals, cash-reality |
| **PHARMA** | R&D capitalisation, loan-licensee RPTs, regulatory non-disclosure | capitalised-R&D trend; USFDA action vs disclosure-timing cross-check (ground truth — FDA database is public) | full non-financial set |
| **REAL ESTATE** | revenue-recognition method games, inventory (unsold stock) valuation, land-bank claims, promoter LAS | customer-advances vs delivery reconciliation; RERA registry cross-check (ground truth); completed-vs-POC method flag | cash-reality, pledge, RPT |
| **PLATFORM / NEW-AGE** (EMERGING track, ADR-0008) | "adjusted EBITDA" bridges, capitalised CAC, founder-entity RPTs, cohort-disclosure gaps | adjusted-vs-statutory EBITDA bridge dissection; capitalised-cost share; disclosure-gap on cohorts/unit economics | cash-reality (works on one balance sheet), dilution |

The matrix is a living spec: the Phase-6 golden set (30 Indian cases across these models — receivable
frauds, cash frauds, guarantee frauds, inventory frauds, not just lender frauds) is what calibrates
thresholds per model. **Until then every threshold is provisional and says so.**

## 3. Line-by-line: the notes-walker (what makes "line by line" enforceable)

Keyword-window section-spotting (today's `filings.py`) finds six sections. Line-by-line means:
**enumerate every numbered note in the financial statements and force a disposition on each.**

- **Note enumeration.** Parse the AR's notes-to-accounts into a list of (note_no, title, pages, text),
  classified against a fixed taxonomy: accounting policies · revenue · PPE/CWIP (+ ageing schedule) ·
  investments · loans & advances (incl. to promoters/KMP) · inventory · **receivables + ageing** · cash ·
  borrowings & defaults · provisions · **contingent liabilities & commitments** · **related parties** ·
  segment · tax · employee benefits/ESOP · fair value/financial instruments · ECL · **Schedule III
  mandatory disclosures** · subsequent events · going concern.
- **Schedule III (2021 amendments) is a forensic gift and is mandatory:** CWIP ageing, receivables/
  payables ageing, ratio explanations, **transactions with struck-off companies**, benami proceedings,
  wilful-defaulter status, undisclosed income, loans to promoters/directors/KMP %. Each is a required
  row: found → extract; absent → `disclosure_gap` (ADR-0014).
- **Disposition per note — the coverage validator.** Every enumerated note gets exactly one of
  `{clean, flag, unknown}` plus extracted key figures bound to `(doc_id, page)` (Law 2). A report cannot
  publish with note coverage < 100% — un-dispositioned notes are listed, never skipped. This is the
  citation-validator pattern applied to *reading completeness*.
- **CARO 2020.** The auditor answers ~21 specific clauses (fixed assets, inventory verification, loans to
  related parties, defaults, fraud noticed/reported, resignation of auditors…). Parse each clause response
  into structured clean/adverse; **any adverse CARO clause is an automatic flag with the clause quoted.**
  Plus: AOC-2 (RPT justifications), secretarial-audit qualifications, Board's-report consistency.

## 4. Build order for this spec (respects phases; each lands with tests)

1. ✅ **Universal checks named by SPEC but not yet coded** — BUILT 2026-07-30: `stock_flow_divergence`
   (receivables & inventory vs revenue), `other_income_share`, `revenue_inflation_tell` in
   `core/compute/quality.py`, wired into `forensic_screen` (suppressed for FINANCIAL), thresholds in
   `config/thresholds.yaml` → `universal_forensic`. 100% covered.
2. ✅ **Provenance-locked numeric table extraction** — BUILT 2026-07-30: `adapters/base/tables.py` —
   line-anchored (label, values, page, line) rows; Indian formats (lakh grouping, paren negatives,
   ₹/%/FY-token masking); page-level unit hints; `find_row` returns None → UNAVAILABLE, never guessed.
   100% covered.
3. ✅ **Notes-walker + coverage + CARO parser (core)** — BUILT 2026-07-30: `adapters/india/notes.py` —
   note enumeration with (page,line) anchors + dedupe; `NoteDisposition` {clean|flag|unknown};
   `coverage()` (phantom dispositions raise — fake coverage impossible); CARO 2020 clause splitter +
   adverse-language TRIAGE (clean formulations like "no fraud … noticed" do not fire; triage routes to
   REVIEW, never auto-veto — Law 1 boundary). 100% covered. *Remaining: the note-taxonomy classifier and
   the Schedule III mandatory-row extractor.*
   ✅ **Note taxonomy + Schedule III** — BUILT 2026-07-30: `NOTE_TAXONOMY` (25 categories, specific-wins
   ordering), `Note.category`, `categorise_notes()`; `SCHEDULE_III_ROWS` + `scan_schedule_iii()` /
   `schedule_iii_gaps()` — all 11 mandatory rows reported found-or-missing with (page,line) anchors, so
   absence feeds `disclosure_gap`. 100% covered.
4. ✅ **Model detector + playbook config** — BUILT 2026-07-30: `core/compute/models.py`
   (`StatementShape` → `detect_models()` → `build_playbook()`) + `config/forensic_playbooks.yaml`.
   7 models; conglomerates get the **union** of playbooks; **suppression always wins** (Beneish can never
   fire on the lending arm of a manufacturer-plus-NBFC); `UNIVERSAL` is the floor so an unclassified
   company is still screened; `gross_margin=None` ("not disclosed") is never read as zero. 100% covered.
5. ✅ **Model-specific checks** — BUILT 2026-07-30: `contract_asset_divergence` (EPC unbilled-vs-billed
   revenue), `guarantees_to_net_worth` (off-BS SPV exposure), `capitalised_cost_share` (R&D/dev cost
   capitalisation), `adjusted_ebitda_bridge_gap` (add-backs as a share of revenue), `promoter_loan_share`
   (**SEVERE** — Schedule III siphoning channel, applies universally). Wired into `forensic_screen`,
   selected per model in `forensic_playbooks.yaml`, thresholds in `thresholds.yaml` → `model_forensic`.
   A test guards that **every check named in a playbook is a real signal** — a typo'd playbook entry
   would otherwise claim a check ran while nothing was evaluated. 100% covered.
6. **Golden-set calibration per model** (Phase 6) — thresholds stop being provisional.

**Chain proven end-to-end** (`tests/test_pipeline_e2e.py`, offline): BSE archive fixture → dated `Filing`
rows → bronze backfill (immutable, resumable, refetch-free on re-run) → extraction (incl. OCR fallback on
an image-only filing) → provenance-locked figures → notes-walk (100% coverage gate) + Schedule III + CARO
→ model detection → playbook → forensic screen. Two companies run through it: a clean manufacturer
(**PASS**, no flags) and a manipulated trader (**HARD_FAIL** on receivables +110% vs revenue +5%, revenue
inflation, and disclosure gaps) — so the chain discriminates, not merely executes.
This test **found a real production bug**: Indian AR line items carry note cross-reference prefixes
("Note 9: Trade Receivables 118.0"), which parsed the note number as a figure and truncated the label to
"Note". Fixed in `tables.py` (`_LEADING_NOTE` masking) with a regression test.

**Data spine (ADR-0018, owner decision):** BSE archive adapter BUILT — `adapters/india/exchange.py`
(`BseFilingsSource`), verified live: announcements with exchange dissemination timestamps + annual-report
PDFs **2012–2026 dated & downloadable** (BSE lists to 1997 but pre-2012 rows are undated/linkless).
Real API responses frozen as test fixtures.
