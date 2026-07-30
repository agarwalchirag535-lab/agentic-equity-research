# Alkyl Amines Chemicals (ALKYLAMINE) — research note
_As-of 2026-07-23 · deterministic numbers from `core/compute`/screener FY26 · narration by Claude Code (Pro plan, no API) · in-universe mid-cap (₹9,279cr)_

## Verdict: **REJECT as a multibagger** — quality business, wrong price, returns at a trough

## Computed facts (Law 1)
| metric | value |
|---|---|
| History | FY15–FY26 (11y), not stale |
| Revenue CAGR 10y / **5y** | 11.2% / **4.3%** |
| PAT CAGR (10y) | 13.4% |
| OPM (FY26 vs FY15) | 18.6% vs 18.3% |
| ROIC / ROCE / ROE | ~10% / 16.6% / 12.3% |
| **Incremental ROIC (last 3 windows)** | **-0.36, -0.13, -0.24** |
| Cumulative CFO/PAT | 1.27 (cash is real) |
| Borrowings FY15→FY26 | ₹135cr → **₹1cr (debt-free)** |
| Market Cap / P/E | ₹9,279cr / **51.5x** |
| **Reverse-DCF implied 10y FCF CAGR** | **~24–28%** |
| Forensic verdict | **PASS** (no flags) |
| Feasibility 4x/6y | NEEDS_EXTERNAL_FUNDING (2.53× NOPAT) |

## The one-line thesis
You are paying a **51x** super-cycle multiple that demands **~25% growth for a decade**, for a debt-free but spread-cyclical amines maker that grew **4.3%** over 5 years and whose **last three years of capex earned negative incremental returns**. Forensically clean, but the compounding case is not supported by the numbers at this price.

## sector_analyst

Genuine national-relevance tailwind: amines/acetonitrile feed India's pharma and agrochem supply chains and displace Chinese imports. But the sector is cyclical on product spreads, and the current numbers show the cycle has cooled from the FY20-22 peak.

## business_analyst

A quality domestic amines franchise sitting on a real India supply-chain need — but economically a commodity-specialty whose profits track product spreads, not a branded moat.

## financial_statement_analyst

The tell is incremental ROIC. Average ROCE (16.6%) still looks fine, but the MARGINAL return on the last three years of capital has been negative — capacity was added into a softening cycle. Revenue growth decelerated to 4.3% (5y). Balance sheet is pristine (debt-free), cash conversion healthy.

## forensic_accountant

Forensically clean. Profit converts to cash (ΣCFO/ΣPAT 1.27), CWIP is stable at ~7% of assets (no perpetual-WIP siphoning), and the company is debt-free. No manipulation signals; no veto.

**Verdict: PASS** (veto=False)

## valuation_modeler

At P/E 51.5x the price demands ~24-28% FCF CAGR for a decade (reverse DCF). The company delivered 4.3% revenue CAGR over 5 years with negative recent incremental ROIC. That gap is the whole story: you are paying a super-cycle multiple for trough fundamentals. Expected value is roughly flat-to-down unless a new up-cycle arrives.

## thesis_synthesizer

Under the firm's one question — can this plausibly 5-10x self-funded in 5-8 years — the answer is NO at ₹1,812. It is a high-quality, honest, debt-free business at a demanding valuation and a returns trough. Reject as a multibagger thesis; revisit if the cycle and incremental ROIC inflect.

## red_team

The bull case rests entirely on a cycle turn that the numbers do not yet show, financed at a multiple that assumes the turn is certain. The asymmetry is unfavourable: limited margin of safety, clear de-rating risk.

**Kill criteria:** Incremental ROIC stays negative through FY27 (capex not paying off).; Revenue growth remains sub-8% for two more years (no cycle recovery).; P/E compresses below 30x (multiple normalises to cyclical reality).; A large debt-funded capex that breaks the debt-free balance sheet.


---

## Primary-source forensic (grade A — FY2025-26 audited annual report, 137 pp, filed 2026-06-09)

Read from the audited document itself (not screener), via `adapters/india/filings.py`:

- **Auditor's opinion: unqualified / clean.** No "Qualified Opinion", "Emphasis of Matter", "Disclaimer" or "Adverse Opinion" in the Independent Auditor's Report.
- **No auditor resignation** during the year — auditor continuity intact.
- **Related-party: arm's-length, ordinary course** — "no materially significant related party transactions ... which may have potential conflict with the interest of the Company."
- **Key Audit Matter: Litigation/contingencies** — a single, routine KAM for a chemicals maker.
- **Contingent liabilities: routine** — "claims against the Company not acknowledged as debt", chiefly government/tax disputes management deems not probable. No off-balance-sheet alarm.

Primary source **confirms** the deterministic screen: forensically clean — the audited notes agree with the numbers.

## Deep-dive: common-size statements (Law 1)

### Common-size P&L (% of sales)
| line | FY24 | FY25 | FY26 |
|---|---|---|---|
| Sales | 100.0 | 100.0 | 100.0 |
| Expenses | 82.5 | 81.4 | 81.4 |
| Operating Profit | 17.5 | 18.5 | 18.6 |
| Other Income | 1.0 | 1.9 | 2.1 |
| Interest | 0.3 | 0.1 | 0.1 |
| Depreciation | 4.1 | 4.5 | 4.7 |
| Profit before tax | 14.0 | 15.8 | 15.8 |
| Net Profit | 10.3 | 11.8 | 11.7 |

### Common-size Balance Sheet (% of total assets)
| line | FY24 | FY25 | FY26 |
|---|---|---|---|
| Borrowings | 0.2 | 0.3 | 0.1 |
| Reserves | 79.4 | 77.8 | 80.3 |
| Fixed Assets | 68.8 | 58.4 | 53.5 |
| CWIP | 2.3 | 2.9 | 6.9 |
| Investments | 0.0 | 0.0 | 2.7 |
| Other Assets | 29.0 | 38.7 | 36.9 |
| Total Assets | 100.0 | 100.0 | 100.0 |
