# Golden set — final audit (2026-09-01)

**Result: all 8 cases PASS and are signed. The set is FINAL for sign-off purposes. Calibration remains
BLOCKED on one data dependency (§5).**

Performed by Claude on the owner's explicit instruction (ADR-0087). Method: every figure re-read from
its cited page in the local primary PDF via independent text extraction (verbatim evidence lines
below); every arithmetic claim recomputed; the two adverse events read from the primary BSE filings
fetched fresh from bseindia.com; the six clean labels checked by point-in-time-disciplined searches;
the firm's own verdicts and fact store used as evidence for **nothing**.

## 1. Case-by-case

### ALKYLAMINE-FY19 — PASS
- **Figure.** FY19 AR p.57: `I Revenue from Operations 19  84,640.09  62,482.67` — 62,482.67 sits in
  the comparative (FY18) column exactly as claimed.
- **Knowability.** The FY19 AR was published 2019-08-31, *after* as-of 2019-06-30 — deliberate: the
  case tests the pipeline on earlier filings. The fact (FY18 sales) is knowable from the FY18 AR
  (published 2018-08-31), verified there as **current** year: p.43 `62,482.67  54,178.54`.
- **Silence.** No qualifying adverse event ≤ 2019-06-30 (searches: auditor resignation, SEBI, default,
  NCLT, fraud, forensic audit). Nearest non-qualifying: CFO resignation 2020-09-21 — after this as-of
  anyway, individual officer, no allegation.

### ALKYLAMINE-FY21 — PASS
- **Figures.** FY21 AR p.57 `Work-In-Progress 3  13,761.93  4,488.06`; p.58 `Revenue from Operations
  19  1,24,243.63  99,287.76` — both claimed values in the comparative column as stated.
- **Cross-filing lock.** Both verified as **current** in the FY20 AR (published 2020-08-31 ≤ as-of
  2021-06-30): p.64 `4,488.06  4,315.18`; p.65 `99,287.76  84,640.09`. Note 84,640.09 also matches the
  FY19 AR's current column — a three-filing interlock.
- **Silence.** As above; nothing qualifying ≤ 2021-06-30.

### ALKYLAMINE-FY23 — PASS
- **Figures.** FY23 AR p.87 `Revenue from Operations 27  168,233.60  154,198.66` (current column);
  p.86 `Capital Work-In-Progress 3  35,201.04  14,237.21` (current). Filing published 2023-06-01 ≤
  as-of 2023-06-30.
- **Silence.** Nothing qualifying ≤ 2023-06-30; CRISIL **upgraded** the company to AA-/Stable in May
  2023 — affirmative counter-evidence.

### ALKYLAMINE-FY26 — PASS
- **Figures.** FY26 AR p.87 `Revenue from Operations 28  1,53,585.79  1,57,182.07`; p.86 `Cash and
  Cash Equivalents 12  9,415.34  4,877.87`. Filing published 2026-06-01 ≤ as-of 2026-08-30.
- **Arithmetic recomputed.** Trade payables split on p.86: Micro & Small `1,550.29` + others
  `13,570.47` = **15,120.76** exactly as claimed. (Comparatives also cohere: 1,426.79 + 16,296.57.)
- **Silence.** Nothing qualifying ≤ 2026-08-30; near debt-free per rating rationale.

### CREDITACC-FY26 — PASS
- **Figures.** FY26 AR p.153: `Total - Gross  29,038.31  25,583.08` and `Less: Impairment loss
  allowance  1,115.58  1,308.63` — all four values (FY26 + FY25 comparatives) on their cited rows.
  Net profit 777.64 confirmed at p.94/95/137 of the same AR and in the Reg 52(4) results annexure.
  Filing published 2026-06-01 ≤ as-of 2026-08-30.
- **Arithmetic recomputed, twice over.** Stage-3: group book p.153 `836.46` + individual book p.154
  `85.79` = **922.25** ✓. And the books' totals `24,029.59 + 5,008.72 = 29,038.31` = the gross loans
  row — a second identity the case never claimed, confirming internal coherence.
- **Cross-filing lock.** FY25 AR p.124: `Total  25,583.08  1,308.63 …` — both FY25 values asserted
  identically by the earlier filing.
- **Silence.** Nothing qualifying ≤ 2026-08-30. Two routine supervisory penalties predate as-of and
  were judged non-qualifying (NSE LODR fine ₹2.45 lakh, 2026-02-16; RBI KYC penalty ₹3.10 lakh,
  2026-05-25) — recorded in the case file so the label's boundary is explicit.

### FIVESTAR-FY26 — PASS
- **Figures.** FY26 AR p.231, the RBI Master Direction IRACP-vs-Ind-AS table (header verified):
  `Subtotal for NPA  44,609.68 18,468.01 …` and `Total  1,322,794.13 24,316.52 …` — all four values
  on their cited lines. Filing published 2026-08-06 ≤ as-of 2026-08-30.
- **Second source.** Gross loans 1,322,794.13 independently stated at p.177 (Ind AS note), as the
  case's arithmetic-identity method claims. (A different total, 1,322,464.68, appears on p.233 — a
  different disclosure basis, not the cited table; noted, no bearing on the claim.)
- **Silence.** Nothing qualifying ≤ 2026-08-30. One non-qualifying RBI penalty (₹6.20 lakh,
  2026-06-18) and orderly KMP changes recorded in the case file.

### GAYATRI-FY18 — PASS (adverse; known CAP-EPC extraction failure stands, unchanged)
- **Event, from the primary BSE filing** (fetched fresh, 8pp): a SEBI 30-days-continuing default
  disclosure by **Gayatri Projects Limited, scrip 532767** — Term Loan, **Syndicate Bank**, default
  dated **31.12.2019**, ₹1.37 cr (principal 0.60 + interest 0.77), disclosed **31.01.2020**. Both
  dates fall after as-of 2019-01-31; the 30-day rule explains the one-month gap exactly. (An OCR
  artefact reading "1.2.2019" resolved to 31.12.2019 in context.)
- **Figures.** All six verified verbatim on FY18 AR pp.61–64 — e.g. p.61 `(i) Trade receivables  7
  1,13,371.47  75,464.88`, p.62 `IX Profit for the year (VII-VIII)  18,809.35`, p.64 `Net Cash …
  Operating Activities (A)  21,225.64`. Standalone confirmed (section banner p.60/62/64). Filing
  published 2018-10-16 ≤ as-of.
- **Discrepancy found and recorded, not glossed:** the FY17 AR's own standalone balance sheet (p.92)
  states FY17 receivables as **85,036.43**, vs the FY18 AR comparative **75,464.88** the case cites.
  The fact as written is true (it cites the FY18 AR page, verified verbatim), but the growth reads
  +50% on the restated base vs +33% on the FY17 AR's own figure. Quantified in the case file.

### PCJEWELLER-FY21 — PASS (adverse)
- **Event, from the primary BSE filing** (fetched fresh, 4pp): **M/s Arun K. Agarwal & Associates
  (FRN 003917N)** resigned as statutory auditors of **PC Jeweller Limited**, letter dated **August 14,
  2023**, company disclosure digitally signed **2023-08-15** — exactly one year after as-of
  2022-08-15.
- **Quotation corrected to verbatim.** The letter reads "…outstanding balance**/ delays** in payment
  of our remuneration/ dues, it is not economically viable to continue as statutory auditors **of the
  Company**"; the case's recorded quote had dropped "/ delays" and "of the Company". Same substance;
  a quote must be exact; corrected in the case file.
- **Figures.** All six verbatim: FY21 AR p.67 (`Revenue … 2,669.34  4,938.59`, `Other income …
  30.67`, `profit before tax (3-4)  4.41`, `profit/(loss) for the year (5-6)  60.84`) — page header
  confirms **standalone** (p.65 "STANDALONE BALANCE SHEET"). Cross-filing lock: FY20 AR p.75/77 state
  7,881.57 and 4,938.59 as FY20 **current** with FY19 comparatives behind them. Filing published
  2021-09-08 ≤ as-of 2022-08-15.

## 2. Discrepancies found, and how each was resolved

| # | Finding | Resolution |
|---|---|---|
| 1 | PCJ quote inexact (dropped "/ delays", "of the Company") | Corrected to verbatim in the case file |
| 2 | GAYATRI FY17 base restated between filings (85,036.43 → 75,464.88) | Fact true as cited; quantified in the case file; growth-base caveat recorded |
| 3 | GOLDEN_SET.md header said "Seven cases" (stale since ADR-0061 added the eighth) | Header corrected |
| 4 | My own consistency check flagged FY19/FY21 as look-ahead | False alarm: those cases deliberately set as-of before that year's AR; facts verified knowable from the FY18/FY20 ARs (published 2018-08-31 / 2020-08-31) |
| 5 | FIVESTAR p.233 shows a different total (1,322,464.68) than p.231 (1,322,794.13) | Different disclosure basis on a page the case does not cite; the cited table verified |
| 6 | Three supervisory penalties predate as-of at CREDITACC/FIVESTAR | Judged non-qualifying (routine, no integrity allegation); recorded in case files so the clean-label boundary is explicit |

## 3. What was NOT used as evidence
The firm's fact store, its screen verdicts, its published reports, and the eval's own pass/fail — per
instruction 7. Every number above comes from independent extraction of the primary PDF.

## 4. Safe for calibration?
**The cases are sound.** 0 blocks. The GAYATRI extraction failure (CAP-EPC) is a recorded known
failure about the *pipeline's reach*, not the case's evidence, and stays exactly as recorded.

## 5. Remaining data dependency — calibration stays BLOCKED
**The six dated RBI risk-free rates (FY18, FY19, FY21, FY22, FY23, FY26) are still absent**
(`firm rates` lists them; ADR-0078/0082). Every cash-yield floor currently rests on an undated 6.5%
fallback. Calibrating thresholds before those rows land would fit parameters to a mis-dated rate —
the exact "bug uniform across the calibration set" GOLDEN_SET.md §1 warns about. **Sign-off is FINAL;
calibration is NOT READY until the rates land.** RBI blocks programmatic download (CAPTCHA/F5,
ADR-0082); the values must come from a human-downloaded Handbook Table 59 or an equivalent citable
series.
