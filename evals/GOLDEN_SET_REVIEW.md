# Golden set — review for sign-off

**8 case(s); 0 signed, 8 awaiting you.** Generated from the case files by `firm eval --review`, so it cannot drift from what the harness reads.

## What you are being asked to confirm

For each case, two things a machine cannot check:

1. **The label is real.** An external, dated, cited event — an auditor resignation, a SEBI order, an NCLT admission — and not something this firm inferred. For a `clean` case, that the *absence* of such an event is genuinely true as of the date.
2. **The verified facts are right.** Each figure was read correctly off the filing page it cites. These separate an extraction failure from a judgment failure, so a wrong one here misattributes every error built on top of it.

## What you are NOT being asked to confirm

**Whether the firm's verdict was correct.** If a case is signed because the screen returned what you expected, the set measures this system against its own output, and every threshold calibrated on it inherits that circularity — the exact failure GOLDEN_SET.md §0 names first. The screen result appears last on each case, as context.

## Before calibrating anything

`firm rates` reports six fiscal years with no dated risk-free rate (FY18, FY19, FY21, FY22, FY23, FY26), so every cash-yield floor currently rests on an undated 6.5% fallback. Calibrating before those land would fit a parameter to the firm's own dating error (ADR-0078/0082, GOLDEN_SET.md §1). **Sign-off first, calibration after the rates.**

---

### ALKYLAMINE-FY19 — ALKYLAMINE, as-of 2019-06-30

- **Label:** `clean` · class `easy`
- **Label event:** none recorded — for a `clean` case the label IS the absence of one, and that absence is what you are confirming.

- **Facts verified by hand: 1** (methods: cross_filing_overlap)

| metric | period | value | read from |
|---|---|---|---|
| `pnl:Sales` | FY18 | 62,482.67 INR_lakh | FY19 AR p.57 l.7 comparative column; stated as current year by the FY18 AR |

- **The claim this case makes:** A FY2018 filing owes no Key Audit Matters section and none of the 2021 Schedule III rows. Anything the firm reports absent here is the firm's own anachronism, not the company's opacity.

- _Context only, not what you are signing — the firm returned: `PASS`_

- **Sign off:** set `human_signed_off: true` in `evals/golden_set/ALKYLAMINE-FY19.yaml`

---

### ALKYLAMINE-FY21 — ALKYLAMINE, as-of 2021-06-30

- **Label:** `clean` · class `hard_capex`
- **Label event:** none recorded — for a `clean` case the label IS the absence of one, and that absence is what you are confirming.

- **Facts verified by hand: 2** (methods: cross_filing_overlap)

| metric | period | value | read from |
|---|---|---|---|
| `balance_sheet:CWIP` | FY20 | 4,488.06 INR_lakh | FY21 AR p.57 l.9 comparative column (4,488.06 lakh) |
| `pnl:Sales` | FY20 | 99,287.76 INR_lakh | FY21 AR p.58 l.6 comparative column (99,287.76 lakh) |

- **The claim this case makes:** The FY2020 filing owes no benami-property, crypto-currency, CWIP-ageing or ratios disclosure — the amendment that created them applies to years commencing on or after 1 April 2021. Before ADR-0059 this case flagged disclosure_gap on five rules that did not exist, which is the single defect that would have poisoned every pre-2022 case in the golden set.

- _Context only, not what you are signing — the firm returned: `PASS`_

- **Sign off:** set `human_signed_off: true` in `evals/golden_set/ALKYLAMINE-FY21.yaml`

---

### ALKYLAMINE-FY23 — ALKYLAMINE, as-of 2023-06-30

- **Label:** `clean` · class `hard_cyclical`
- **Label event:** none recorded — for a `clean` case the label IS the absence of one, and that absence is what you are confirming.

- **Facts verified by hand: 2** (methods: cross_filing_overlap, filing_page)

| metric | period | value | read from |
|---|---|---|---|
| `pnl:Sales` | FY23 | 168,233.60 INR_lakh | FY23 AR p.87 l.6 (1,68,233.60 lakh) |
| `balance_sheet:CWIP` | FY23 | 35,201.04 INR_lakh | FY23 AR p.86 l.10 (35,201.04 lakh) |

- **The claim this case makes:** A cyclical downturn in a chemicals business is not a forensic finding. A cash yield 0.05pp below a provisional band, on a company mid-capex holding working balances, cannot support "is the cash real?" at SEVERE — the strongest accusation the deterministic screen can make. ageing_cwip at MEDIUM is defensible on its own and REVIEW is an acceptable outcome; HARD_FAIL is not.

- **Recorded coverage gap / note:** CAL-1 CLOSED 2026-08-31 (ADR-0059), and NOT by moving cash_yield_floor_ratio, which is untouched at 0.40 and remains uncalibrated. The case was recorded as failing because the check fired SEVERE at an implied cash yield of 2.55% against a 2.60% floor. The diagnosis, taken from the whole FY19-FY26 series rather than from this one year: the yield is a year of interest divided by the MEAN of two balance-sheet endpoints, and Alkyl Amines' cash and bank balances fell 71% during FY23 (₹62.57cr to ₹18.23cr). The same two endpoints are equally consistent with 1.64% and with 5.64% — the ordinary story where the drawdown happened in April. The check now asserts the claim only where every timing story the endpoints tell agrees with it, so FY23 reports UNAVAILABLE naming the balances that would resolve it, and the screen comes out REVIEW on ageing_cwip and disclosure_gap — which is what this case's rationale said in advance was the defensible answer. THE THRESHOLD IS STILL UNTESTED. This observation never bore on it: 8 of Alkyl's 8 measurable years, and 11 of the set's 12 company-years, have endpoint bands too wide to test any floor. What changed is that the firm now knows that, and says so.

- _Context only, not what you are signing — the firm returned: `REVIEW`_

- **Sign off:** set `human_signed_off: true` in `evals/golden_set/ALKYLAMINE-FY23.yaml`

---

### ALKYLAMINE-FY26 — ALKYLAMINE, as-of 2026-08-30

- **Label:** `clean` · class `easy`
- **Label event:** none recorded — for a `clean` case the label IS the absence of one, and that absence is what you are confirming.

- **Facts verified by hand: 3** (methods: arithmetic_identity, filing_page)

| metric | period | value | read from |
|---|---|---|---|
| `pnl:Sales` | FY26 | 153,585.79 INR_lakh | FY26 AR p.87 l.7, Statement of Profit and Loss, Revenue from Operations |
| `balance_sheet:Trade Payables` | FY26 | 15,120.76 INR_lakh | FY26 AR p.86 l.49-50, Schedule III split across two rows |
| `balance_sheet:Cash Equivalents` | FY26 | 9,415.34 INR_lakh | FY26 AR p.86 l.23 |

- **The claim this case makes:** A profitable, self-funded specialty chemicals manufacturer with no governance event. If this does not come out PASS, the floor is broken and no other case means anything.

- _Context only, not what you are signing — the firm returned: `PASS`_

- **Sign off:** set `human_signed_off: true` in `evals/golden_set/ALKYLAMINE-FY26.yaml`

---

### CREDITACC-FY26 — CREDITACC, as-of 2026-08-30

- **Label:** `clean` · class `hard_recovery`
- **Label event:** none recorded — for a `clean` case the label IS the absence of one, and that absence is what you are confirming.

- **Facts verified by hand: 6** (methods: arithmetic_identity, cross_filing_overlap, independent_filing)

| metric | period | value | read from |
|---|---|---|---|
| `notes:Stage 3 Gross` | FY26 | 922.25 INR_cr | ECL staging tables, group book p.153 (836.46) + individual book p.154 (85.79) |
| `notes:Gross Loans` | FY26 | 29,038.31 INR_cr | note 7 (Loans) p.153 Total-Gross row; also IRACP p.129 l.105 |
| `notes:Impairment Allowance` | FY26 | 1,115.58 INR_cr | note 7 (Loans) p.153 Less-Impairment-loss-allowance row; also IRACP p.129 |
| `notes:Gross Loans` | FY25 | 25,583.08 INR_cr | FY25 AR p.123 l.55; restated in FY26 AR note 22 (Loans) comparative column |
| `notes:Impairment Allowance` | FY25 | 1,308.63 INR_cr | FY25 AR p.123 l.55; FY26 AR note 22 comparative column |
| `pnl:Net Profit` | FY26 | 777.64 INR_cr | Reg 52(4) Annexure I to the Q4 FY26 results, item 9 "Net profit after tax" |

- **The claim this case makes:** Gross NPA fell 4.79% to 3.18% and provision coverage is 65.8%, both confirmed by the company's own Reg 52(4) annexure (Gross Stage III 3.17%, provision coverage 65.40%). A provision-rate cut into an improving book is not suppression. REVIEW rather than PASS is expected and correct: disclosure_gap still fires on undisclosed_income, which the firm has not resolved.

- _Context only, not what you are signing — the firm returned: `REVIEW`_

- **Sign off:** set `human_signed_off: true` in `evals/golden_set/CREDITACC-FY26.yaml`

---

### FIVESTAR-FY26 — FIVESTAR, as-of 2026-08-30

- **Label:** `clean` · class `hard_model_mismatch`
- **Label event:** none recorded — for a `clean` case the label IS the absence of one, and that absence is what you are confirming.

- **Facts verified by hand: 4** (methods: arithmetic_identity, independent_filing)

| metric | period | value | read from |
|---|---|---|---|
| `notes:Stage 3 Gross` | FY26 | 44,609.68 INR_lakh | p.231 l.19 "Subtotal for NPA" (RBI Ind AS 109 / IRACP table) |
| `notes:Gross Loans` | FY26 | 1,322,794.13 INR_lakh | p.231 l.20 "Total" |
| `notes:Impairment Allowance` | FY26 | 24,316.52 INR_lakh | p.231 l.20 |
| `notes:Stage 3 Allowance` | FY26 | 18,468.01 INR_lakh | p.231 l.19 |

- **The claim this case makes:** Gross Stage 3 rose 1.79% to 3.37% — the company states both figures itself — so gnpa_drift is a real finding and must fire. provision_coverage_low must NOT: 41.4% coverage on a book 99.98% secured on tangible assets is collateral doing the work, and no lender discloses the value of security held against stage-3 loans, so the number that would matter cannot be computed at all.

- **Recorded coverage gap / note:** PORT-1b extraction half CLOSED 2026-08-31 (ADR-0060): FY25/FY26 verified readings authored through the propose-verify gate (148 figures, 0 violations first pass). The verified_facts below were re-keyed from the third line's metric vocabulary (balance_sheet:Gross NPA / Gross Advances / Loan Loss Allowance / NPA Provisions) to the trunk's (notes:Stage 3 Gross / Gross Loans / Impairment Allowance / Stage 3 Allowance) — values, units, locators and methods are the human's originals, untouched; only the ids moved, because an id names a store slot, not a fact.

- _Context only, not what you are signing — the firm returned: `REVIEW`_

- **Sign off:** set `human_signed_off: true` in `evals/golden_set/FIVESTAR-FY26.yaml`

---

### GAYATRI-FY18 — GAYATRI, as-of 2019-01-31

- **Label:** `adverse`
- **Label event:** `loan_default` on **2020-01-31**
  - Source: https://www.bseindia.com/xml-data/corpfiling/AttachHis/6d008b82-ee1a-40c3-8e95-f09c92e153a0.pdf
  - The company's own Regulation-30 disclosure of loan defaults continuing beyond 30 days: default date 31.12.2019 on working-capital term loans AND funded-interest term loans (an FITL is itself capitalised unpaid interest from an earlier restructuring) owed to a consortium of 12 banks led by Bank of Baroda, against Rs 1,845.05cr of bank borrowings and Rs 3,299.04cr total indebtedness. The letter states the amounts were first disclosed in the quarterly default disclosure of 2020-01-07. NOTE ON THE DATE: SEBI's default-disclosure regime (CIR/CFD/CMD1/44/2019) took effect 2020-01-01, so 2020-01-31 is the earliest a default COULD reach this register — it bounds the confession, not the distress. The enumeration was walked back to 2018-01-01 and found nothing earlier (the regime explains why), and the as_of precedes every default-regime disclosure that exists.

- **Facts verified by hand: 6** (methods: filing_page)

| metric | period | value | read from |
|---|---|---|---|
| `balance_sheet:Trade Receivables` | FY18 | 113,371.47 INR_lakh | p.61 "(i) Trade receivables" (standalone balance sheet, Note 7) |
| `balance_sheet:Trade Receivables` | FY17 | 75,464.88 INR_lakh | FY18 AR p.61 comparative column (standalone balance sheet) |
| `pnl:Sales` | FY18 | 291,231.24 INR_lakh | p.62 "(I) Revenue from operations" (standalone statement of profit and loss) |
| `pnl:Net Profit` | FY18 | 18,809.35 INR_lakh | p.62 "IX Profit for the year (VII-VIII)" |
| `cashflow:Cash from Operating Activity` | FY18 | 21,225.64 INR_lakh | p.64 "Net Cash (used in)/ generated from Operating Activities (A)" |
| `balance_sheet:Total Assets` | FY18 | 498,610.03 INR_lakh | p.61 "Total Assets" (standalone balance sheet) |

- **The claim this case makes:** Twelve months before a confessed default to a 12-bank consortium — with the FY18 auditor already naming unrecovered advances for works that never commenced, receivable days at 142, interest cover of 1.76x and an FITL on the books from an earlier restructuring — the deterministic screen must not clear the company. REVIEW is the floor of honesty; PASS is a miss. No individual check is pre-registered in must_flag because, honestly, none of the wired checks measures the EPC geometry that carries the signal — which is the capability this case exists to force.

- **Recorded as a known failure:** CAP-EPC (ADR-0061) — two halves, both measured by the first cold run (2026-08-31). EXTRACTION: the walker registered the FY17 AR's statements and the FY18 AR's consolidated P&L, but the FY18 AR's balance sheet and cash-flow statement not at all — 5 of 6 verified facts unreproduced — so the screen judged FY18 on a store carrying no FY18 balance sheet; verified readings (ADR-0046 path) are the known fix. JUDGMENT: the screen landed REVIEW (in band) off inventory_divergent and other_income_heavy computed from the FY17-era rows — the right verdict for reasons that carry little of the real signal, because every check that measures the EPC geometry the FY18 filing confesses (advances for works never commenced, claims receivable, contract dues) is declared UNIMPLEMENTED (ADR-0051). Recorded as the register-selected forcing function for both.

- _Context only, not what you are signing — the firm returned: `REVIEW`_
  - _extraction gap:_ balance_sheet:Trade Receivables FY18: verified 113,371.47 (filing_page, p.61 "(i) Trade receivables" (standalone balance sheet, Note 7)), pipeline read absent
  - _extraction gap:_ balance_sheet:Trade Receivables FY17: verified 75,464.88 (filing_page, FY18 AR p.61 comparative column (standalone balance sheet)), pipeline read 850.36
  - _extraction gap:_ pnl:Net Profit FY18: verified 18,809.35 (filing_page, p.62 "IX Profit for the year (VII-VIII)"), pipeline read absent
  - _extraction gap:_ cashflow:Cash from Operating Activity FY18: verified 21,225.64 (filing_page, p.64 "Net Cash (used in)/ generated from Operating Activities (A)"), pipeline read absent
  - _extraction gap:_ balance_sheet:Total Assets FY18: verified 498,610.03 (filing_page, p.61 "Total Assets" (standalone balance sheet)), pipeline read absent

- **Sign off:** set `human_signed_off: true` in `evals/golden_set/GAYATRI-FY18.yaml`

---

### PCJEWELLER-FY21 — PCJEWELLER, as-of 2022-08-15

- **Label:** `adverse`
- **Label event:** `auditor_resignation` on **2023-08-15**
  - Source: https://www.bseindia.com/xml-data/corpfiling/AttachHis/4494ef61-5631-4618-8c14-aa5c83df593b.pdf
  - M/s Arun K. Agarwal & Associates resigned as statutory auditors mid-term (appointed to hold office until the 20th AGM in 2025), stating in their letter of 14 August 2023 that "considering the cost, time and efforts involved in execution of the assignment and outstanding balance in payment of our remuneration/ dues, it is not economically viable to continue as statutory auditors".

- **Facts verified by hand: 6** (methods: cross_filing_overlap, filing_page)

| metric | period | value | read from |
|---|---|---|---|
| `pnl:Sales` | FY21 | 2,669.34 INR_cr | FY21 AR p.67 l.7, Standalone Statement of Profit and Loss, "Revenue from operations" |
| `pnl:Other Income` | FY21 | 30.67 INR_cr | FY21 AR p.67 l.8 |
| `pnl:Profit before tax` | FY21 | 4.41 INR_cr | FY21 AR p.67 l.20, "profit before tax (3-4)" |
| `pnl:Net Profit` | FY21 | 60.84 INR_cr | FY21 AR p.67 l.25, "profit/(loss) for the year (5-6)" |
| `balance_sheet:Total Assets` | FY20 | 7,881.57 INR_cr | FY20 AR balance sheet; restated as the FY21 AR's comparative column |
| `pnl:Sales` | FY20 | 4,938.59 INR_cr | FY20 AR Statement of Profit and Loss; FY21 AR comparative column |

- **The claim this case makes:** THE CLAIM THIS CASE MAKES IS THAT THE FIRM MUST NOT CLEAR THIS COMPANY. From filings available in August 2022: revenue falling 43% a year, pre-tax profit of ₹4.41cr against other income of ₹30.67cr (695% of PBT — the operating business is loss-making), and interest cover of 0.93x, meaning operating profit does not cover the interest bill. A year later the statutory auditor resigned over unpaid dues. PASS is not an acceptable answer; REVIEW with `other_income_heavy` firing is.

- **Recorded coverage gap / note:** RECORDED COVERAGE GAP, not a defect: no business model matches. PC Jeweller is an inventory-heavy jeweller — 74% of assets in inventory, 0.4% in property/plant, asset turnover 0.34x — which fits neither MANUFACTURER (needs PPE >= 20% of assets), TRADER (needs turnover >= 2.0x and gross margin <= 6%), nor REALESTATE. Only the universal playbook runs, and the firm SAYS so rather than guessing a model. Four universal checks are UNAVAILABLE because the cash-flow statement rows this filing prints are not all read. A retail/jewellery playbook would be the honest fix; this case is where its absence becomes measurable.

- _Context only, not what you are signing — the firm returned: `HARD_FAIL`_

- **Sign off:** set `human_signed_off: true` in `evals/golden_set/PCJEWELLER-FY21.yaml`

---
