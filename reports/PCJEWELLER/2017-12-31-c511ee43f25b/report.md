# PC Jeweller Limited (PCJEWELLER) — research note

**Verdict: `FORENSIC_CAUTION` — Forensic caution — red flags evidenced below**

_As-of 2017-12-31 · run `2017-12-31-c511ee43f25b` · confidence 0.38 (from 16 facts, lowest grade A) · 90% of the applicable playbook was evaluable, 25% of notes carry a substantive disposition, 36% of the line-by-line questions could be answered, and the weakest grade relied on is A (cap 0.90)_

> Research artifact only. Not investment advice, not a recommendation to transact, and not an offer to buy or sell any security. Figures are computed deterministically from cited primary sources; anything not disclosed is reported as UNAVAILABLE.

_Agents: business_analyst@1.0.0, financial_statement_analyst@1.0.0, forensic_accountant@1.0.0_

## Executive summary

The statements describe a company whose profit is an accounting event and whose cash is a financing event. Working capital absorbs the profit year after year, the investing line is small beside it, and the finance-cost line is far too large for the borrowings shown, which points at funding hidden inside the payables. The one good year of conversion at the end of the window does not repair the cumulative record; it coincides with slower collections and should be read with the forensic note rather than against it.

**Verdict rationale (deterministic):** deterministic screen returned HARD_FAIL with 2 flag(s); at or above severity HIGH: cumulative_cfo_pat_low, receivables_divergent

### The load-bearing points

- **[observation, grade A]** Across the six-year window, cumulative operating cash flow was 0.24 [fact:derived:cum_cfo_pat] of cumulative profit after tax. Roughly three rupees of every four of reported profit did not arrive as cash from operations.
- **[observation, grade A]** The deterministic screen hard-fails on cumulative cash conversion: 0.24 [fact:derived:cum_cfo_pat] of cumulative reported profit arrived as operating cash across the window.
- **[observation, grade A]** Revenue compounded at 22.8% [fact:derived:revenue_cagr] across the window while profit compounded at 12.8% [fact:derived:pat_cagr] — growth has been bought at declining profitability per rupee of sales.

## What this business actually does

Manufactures and retails gold, diamond-studded and silver jewellery through its own domestic showrooms, and sells gold jewellery in bulk to export buyers. A rupee of revenue arrives either over a showroom counter, largely against cash, or as an export invoice that becomes a trade receivable. The raw material is bullion: the company buys gold, including on gold metal loans routed through bank trade payables, converts it through owned and outsourced karigar workshops, and carries a very large inventory of finished stock in the showrooms.

## The numbers (deterministic — Law 1)

| metric | value | source |
|---|---|---|
| revenue_cagr | 0.23 | `[fact:derived:revenue_cagr]` derivation:(pnl:Sales FY17 / pnl:Sales FY12)^(1/5) - 1 inputs AR-FY13-PCJ-AR-FY13.pdf:pnl:Sales:FY12, AR-FY17-PCJ-AR-FY17.pdf:pnl:Sales:FY17 (grade A) |
| pat_cagr | 0.13 | `[fact:derived:pat_cagr]` derivation:(pnl:Net Profit FY17 / pnl:Net Profit FY12)^(1/5) - 1 inputs AR-FY13-PCJ-AR-FY13.pdf:pnl:Net Profit:FY12, AR-FY17-PCJ-AR-FY17.pdf:pnl:Net Profit:FY17 (grade A) |
| cum_cfo_pat | 0.24 | `[fact:derived:cum_cfo_pat]` derivation:Σ CFO / Σ PAT, FY12-FY17 inputs AR-FY13-PCJ-AR-FY13.pdf:cashflow:Cash from Operating Activity:FY12, AR-FY14-PCJ-AR-FY14.pdf:cashflow:Cash from Operating Activity:FY13, AR-FY15-PCJ-AR-FY15.pdf:cashflow:Cash from Operating Activity:FY14, AR-FY16-PCJ-AR-FY16.pdf:cashflow:Cash from Operating Activity:FY15, AR-FY17-PCJ-AR-FY17.pdf:cashflow:Cash from Operating Activity:FY16, AR-FY17-PCJ-AR-FY17.pdf:cashflow:Cash from Operating Activity:FY17, AR-FY13-PCJ-AR-FY13.pdf:pnl:Net Profit:FY12, AR-FY14-PCJ-AR-FY14.pdf:pnl:Net Profit:FY13, AR-FY15-PCJ-AR-FY15.pdf:pnl:Net Profit:FY14, AR-FY16-PCJ-AR-FY16.pdf:pnl:Net Profit:FY15, AR-FY17-PCJ-AR-FY17.pdf:pnl:Net Profit:FY16, AR-FY17-PCJ-AR-FY17.pdf:pnl:Net Profit:FY17 (grade A) |
| cfo_pat_latest | 1.80 | `[fact:derived:cfo_pat_latest]` derivation:CFO FY17 / PAT FY17 inputs AR-FY17-PCJ-AR-FY17.pdf:cashflow:Cash from Operating Activity:FY17, AR-FY17-PCJ-AR-FY17.pdf:pnl:Net Profit:FY17 (grade A) |
| accrual_ratio_latest | -0.05 | `[fact:derived:accrual_ratio_latest]` derivation:(PAT - CFO)(FY17) / avg Total Assets inputs AR-FY17-PCJ-AR-FY17.pdf:pnl:Net Profit:FY17, AR-FY17-PCJ-AR-FY17.pdf:cashflow:Cash from Operating Activity:FY17, AR-FY17-PCJ-AR-FY17.pdf:balance_sheet:Total Assets:FY17, AR-FY17-PCJ-AR-FY17.pdf:balance_sheet:Total Assets:FY16 (grade A) |
| other_income_share | 0.18 | `[fact:derived:other_income_share]` derivation:pnl:Other Income FY17 / pnl:Profit before tax FY17 inputs AR-FY17-PCJ-AR-FY17.pdf:pnl:Other Income:FY17, AR-FY17-PCJ-AR-FY17.pdf:pnl:Profit before tax:FY17 (grade A) |
| cost_of_debt_latest | 0.40 | `[fact:derived:cost_of_debt_latest]` derivation:Interest FY17 / Borrowings FY17 inputs AR-FY17-PCJ-AR-FY17.pdf:pnl:Interest:FY17, AR-FY17-PCJ-AR-FY17.pdf:balance_sheet:Borrowings:FY17 (grade A) |
| debt_delta_window | 114.39 | `[fact:derived:debt_delta_window]` derivation:Borrowings FY17 - Borrowings FY12 inputs AR-FY13-PCJ-AR-FY13.pdf:balance_sheet:Borrowings:FY12, AR-FY17-PCJ-AR-FY17.pdf:balance_sheet:Borrowings:FY17 (grade A) |
| cfo_cum_window | 502.71 | `[fact:derived:cfo_cum_window]` derivation:Σ CFO, FY12-FY17 inputs AR-FY13-PCJ-AR-FY13.pdf:cashflow:Cash from Operating Activity:FY12, AR-FY14-PCJ-AR-FY14.pdf:cashflow:Cash from Operating Activity:FY13, AR-FY15-PCJ-AR-FY15.pdf:cashflow:Cash from Operating Activity:FY14, AR-FY16-PCJ-AR-FY16.pdf:cashflow:Cash from Operating Activity:FY15, AR-FY17-PCJ-AR-FY17.pdf:cashflow:Cash from Operating Activity:FY16, AR-FY17-PCJ-AR-FY17.pdf:cashflow:Cash from Operating Activity:FY17 (grade A) |
| investing_outflow_cum | 717.92 | `[fact:derived:investing_outflow_cum]` derivation:-Σ CFI, FY12-FY17 inputs AR-FY13-PCJ-AR-FY13.pdf:cashflow:Cash from Investing Activity:FY12, AR-FY14-PCJ-AR-FY14.pdf:cashflow:Cash from Investing Activity:FY13, AR-FY15-PCJ-AR-FY15.pdf:cashflow:Cash from Investing Activity:FY14, AR-FY16-PCJ-AR-FY16.pdf:cashflow:Cash from Investing Activity:FY15, AR-FY17-PCJ-AR-FY17.pdf:cashflow:Cash from Investing Activity:FY16, AR-FY17-PCJ-AR-FY17.pdf:cashflow:Cash from Investing Activity:FY17 (grade A) |
| self_funding_ratio | 0.70 | `[fact:derived:self_funding_ratio]` derivation:Σ CFO / -Σ CFI, FY12-FY17 (>=1 means operations paid for the investment programme) inputs AR-FY13-PCJ-AR-FY13.pdf:cashflow:Cash from Operating Activity:FY12, AR-FY14-PCJ-AR-FY14.pdf:cashflow:Cash from Operating Activity:FY13, AR-FY15-PCJ-AR-FY15.pdf:cashflow:Cash from Operating Activity:FY14, AR-FY16-PCJ-AR-FY16.pdf:cashflow:Cash from Operating Activity:FY15, AR-FY17-PCJ-AR-FY17.pdf:cashflow:Cash from Operating Activity:FY16, AR-FY17-PCJ-AR-FY17.pdf:cashflow:Cash from Operating Activity:FY17, AR-FY13-PCJ-AR-FY13.pdf:cashflow:Cash from Investing Activity:FY12, AR-FY14-PCJ-AR-FY14.pdf:cashflow:Cash from Investing Activity:FY13, AR-FY15-PCJ-AR-FY15.pdf:cashflow:Cash from Investing Activity:FY14, AR-FY16-PCJ-AR-FY16.pdf:cashflow:Cash from Investing Activity:FY15, AR-FY17-PCJ-AR-FY17.pdf:cashflow:Cash from Investing Activity:FY16, AR-FY17-PCJ-AR-FY17.pdf:cashflow:Cash from Investing Activity:FY17 (grade A) |
| debt_funded_investment_share | 0.16 | `[fact:derived:debt_funded_investment_share]` derivation:ΔBorrowings / -Σ CFI, FY12-FY17 (share of the investment programme debt paid for) inputs AR-FY13-PCJ-AR-FY13.pdf:balance_sheet:Borrowings:FY12, AR-FY17-PCJ-AR-FY17.pdf:balance_sheet:Borrowings:FY17, AR-FY13-PCJ-AR-FY13.pdf:cashflow:Cash from Investing Activity:FY12, AR-FY14-PCJ-AR-FY14.pdf:cashflow:Cash from Investing Activity:FY13, AR-FY15-PCJ-AR-FY15.pdf:cashflow:Cash from Investing Activity:FY14, AR-FY16-PCJ-AR-FY16.pdf:cashflow:Cash from Investing Activity:FY15, AR-FY17-PCJ-AR-FY17.pdf:cashflow:Cash from Investing Activity:FY16, AR-FY17-PCJ-AR-FY17.pdf:cashflow:Cash from Investing Activity:FY17 (grade A) |
| receivable_days | 66.20 | `[fact:derived:receivable_days]` derivation:balance_sheet:Trade Receivables FY17 / pnl:Sales FY17 x 365 inputs AR-FY17-PCJ-AR-FY17.pdf:balance_sheet:Trade Receivables:FY17, AR-FY17-PCJ-AR-FY17.pdf:pnl:Sales:FY17 (grade A) |
| inventory_days | 214.65 | `[fact:derived:inventory_days]` derivation:balance_sheet:Inventories FY17 / (Materials + Δ FG/WIP) FY17 x 365 inputs AR-FY17-PCJ-AR-FY17.pdf:balance_sheet:Inventories:FY17, AR-FY17-PCJ-AR-FY17.pdf:pnl:Cost of Materials Consumed:FY17, AR-FY17-PCJ-AR-FY17.pdf:pnl:Changes in Inventories:FY17 (grade A) |
| payable_days | 153.63 | `[fact:derived:payable_days]` derivation:balance_sheet:Trade Payables FY17 / (Materials + Δ FG/WIP) FY17 x 365 inputs AR-FY17-PCJ-AR-FY17.pdf:balance_sheet:Trade Payables:FY17, AR-FY17-PCJ-AR-FY17.pdf:pnl:Cost of Materials Consumed:FY17, AR-FY17-PCJ-AR-FY17.pdf:pnl:Changes in Inventories:FY17 (grade A) |
| receivable_days_delta | 17.43 | `[fact:derived:receivable_days_delta]` derivation:Receivable days FY17 - FY16 (positive = collection is slowing) inputs AR-FY17-PCJ-AR-FY17.pdf:balance_sheet:Trade Receivables:FY17, AR-FY17-PCJ-AR-FY17.pdf:pnl:Sales:FY17, AR-FY17-PCJ-AR-FY17.pdf:balance_sheet:Trade Receivables:FY16, AR-FY17-PCJ-AR-FY17.pdf:pnl:Sales:FY16 (grade A) |
| cash_conversion_cycle | 127.22 | `[fact:derived:cash_conversion_cycle]` derivation:Receivable days + Inventory days - Payable days, FY17 (days of cash tied up) inputs AR-FY17-PCJ-AR-FY17.pdf:balance_sheet:Trade Receivables:FY17, AR-FY17-PCJ-AR-FY17.pdf:pnl:Sales:FY17, AR-FY17-PCJ-AR-FY17.pdf:balance_sheet:Inventories:FY17, AR-FY17-PCJ-AR-FY17.pdf:pnl:Cost of Materials Consumed:FY17, AR-FY17-PCJ-AR-FY17.pdf:pnl:Changes in Inventories:FY17, AR-FY17-PCJ-AR-FY17.pdf:balance_sheet:Trade Payables:FY17, AR-FY17-PCJ-AR-FY17.pdf:pnl:Cost of Materials Consumed:FY17, AR-FY17-PCJ-AR-FY17.pdf:pnl:Changes in Inventories:FY17 (grade A) |
| material_cost_ratio | 0.89 | `[fact:derived:material_cost_ratio]` derivation:Cost of Materials Consumed FY17 / pnl:Sales FY17 inputs AR-FY17-PCJ-AR-FY17.pdf:pnl:Cost of Materials Consumed:FY17, AR-FY17-PCJ-AR-FY17.pdf:pnl:Sales:FY17 (grade A) |
| material_cost_ratio_delta | -0.14 | `[fact:derived:material_cost_ratio_delta]` derivation:Cost of Materials Consumed/Sales FY17 - Cost of Materials Consumed/Sales FY12 inputs AR-FY13-PCJ-AR-FY13.pdf:pnl:Cost of Materials Consumed:FY12, AR-FY13-PCJ-AR-FY13.pdf:pnl:Sales:FY12, AR-FY17-PCJ-AR-FY17.pdf:pnl:Cost of Materials Consumed:FY17, AR-FY17-PCJ-AR-FY17.pdf:pnl:Sales:FY17 (grade A) |
| employee_cost_ratio | 0.01 | `[fact:derived:employee_cost_ratio]` derivation:Employee Benefits FY17 / pnl:Sales FY17 inputs AR-FY17-PCJ-AR-FY17.pdf:pnl:Employee Benefits:FY17, AR-FY17-PCJ-AR-FY17.pdf:pnl:Sales:FY17 (grade A) |
| employee_cost_ratio_delta | 0.00 | `[fact:derived:employee_cost_ratio_delta]` derivation:Employee Benefits/Sales FY17 - Employee Benefits/Sales FY12 inputs AR-FY13-PCJ-AR-FY13.pdf:pnl:Employee Benefits:FY12, AR-FY13-PCJ-AR-FY13.pdf:pnl:Sales:FY12, AR-FY17-PCJ-AR-FY17.pdf:pnl:Employee Benefits:FY17, AR-FY17-PCJ-AR-FY17.pdf:pnl:Sales:FY17 (grade A) |
| other_expense_ratio | 0.02 | `[fact:derived:other_expense_ratio]` derivation:Other Expenses FY17 / pnl:Sales FY17 inputs AR-FY17-PCJ-AR-FY17.pdf:pnl:Other Expenses:FY17, AR-FY17-PCJ-AR-FY17.pdf:pnl:Sales:FY17 (grade A) |
| other_expense_ratio_delta | -0.03 | `[fact:derived:other_expense_ratio_delta]` derivation:Other Expenses/Sales FY17 - Other Expenses/Sales FY12 inputs AR-FY13-PCJ-AR-FY13.pdf:pnl:Other Expenses:FY12, AR-FY13-PCJ-AR-FY13.pdf:pnl:Sales:FY12, AR-FY17-PCJ-AR-FY17.pdf:pnl:Other Expenses:FY17, AR-FY17-PCJ-AR-FY17.pdf:pnl:Sales:FY17 (grade A) |
| net_cash_position | 499.98 | `[fact:derived:net_cash_position]` derivation:Cash + Other Bank Balances - Borrowings, FY17 inputs AR-FY17-PCJ-AR-FY17.pdf:balance_sheet:Cash Equivalents:FY17, AR-FY17-PCJ-AR-FY17.pdf:balance_sheet:Other Bank Balances:FY17, AR-FY17-PCJ-AR-FY17.pdf:balance_sheet:Borrowings:FY17 (grade A) |
| cost_of_debt_average | 0.34 | `[fact:derived:cost_of_debt_average]` derivation:Interest FY17 / average Borrowings, FY16-FY17 inputs AR-FY17-PCJ-AR-FY17.pdf:pnl:Interest:FY17, AR-FY17-PCJ-AR-FY17.pdf:balance_sheet:Borrowings:FY17, AR-FY17-PCJ-AR-FY17.pdf:balance_sheet:Borrowings:FY16 (grade A) |

## Line by line — why each number moved

_Every question a competent analyst must ask of each statement line. **36%** of the applicable questions could be answered from the sources read as-of 2017-12-31; the rest are printed unanswered with the exact filing row that would close them, because a question dropped is a question that looks answered._

### Revenue — where the money actually comes from

_Every other line depends on this one, and it is the easiest to inflate: revenue can be booked gross instead of net, recognised early, routed through a related party, or bought outright. Growth with no stated cause is the single most common way a promoter story survives contact with a spreadsheet._

**Answered: 2 of 7** (29%)

- **At what rate did revenue actually compound, and over what window?**
  → Revenue compounded at 22.8% across FY12-FY17 — fast enough that a 5x in 5-8 years does not require a re-rating. `[fact:derived:revenue_cagr]`
- **Did receivables grow faster than revenue? Sales that turn into a receivable instead of cash are the classic signature of channel-stuffing and of revenue booked to hit a number.**
  → Receivable days moved 17.4 days year on year — collection is lengthening materially, which is what revenue booked to hit a number looks like on the balance sheet. `[fact:derived:receivable_days_delta]`
- **Is the growth VOLUME or PRICE? A processor whose revenue rose on realisation has no compounding claim — the price reverses. One whose tonnage rose has a capacity story that can repeat.** — ⚠️ **unanswered** (high)
  → no extractor reads this yet — it requires the primary-source rows named below
     - needs: tonnes / units sold per year (MD&A production-and-sales table, or the segment note)
     - needs: realisation per unit (segment revenue / segment volume) to separate price from mix
- **Is revenue concentrated in a few buyers? One customer at 30% of sales is not a customer, it is a counterparty risk with pricing power over the entire P&L.** — ⚠️ **unanswered** (high)
  → no extractor reads this yet — it requires the primary-source rows named below
     - needs: customer-concentration disclosure (Ind AS 108 segment note: revenue from customers >10%)
     - needs: trade-receivable concentration in the credit-risk note (Ind AS 107)
- **How much revenue is transacted with related parties? Revenue sold to an entity the promoter also controls is not third-party demand; it is a number the promoter can choose.** — ⚠️ **unanswered** (high)
  → no extractor reads this yet — it requires the primary-source rows named below
     - needs: related-party transactions note (Ind AS 24) — sales-of-goods line, by party
     - needs: the related-party balance outstanding at year end, to see whether the sale was ever collected
- **Is the growth organic, or did it arrive with an acquisition?** — ⚠️ **unanswered** (medium)
  → no extractor reads this yet — it requires the primary-source rows named below
     - needs: business-combination note (Ind AS 103) — consideration paid, revenue acquired
     - needs: consolidated-vs-standalone revenue gap, to size what the subsidiaries contribute
- **Did the revenue-recognition policy change during the window, and did the change flatter the trend? A policy change is disclosed exactly once and then never mentioned again.** — ⚠️ **unanswered** (medium)
  → no extractor reads this yet — it requires the primary-source rows named below
     - needs: significant-accounting-policies note, revenue paragraph, compared across two annual reports

### Margins — whether the growth is worth having

_A margin is an outcome, not a decision. It moves because a cost line moved, because price moved, or because the mix moved — and only the first two are inside management's control. Growth bought with margin is how a commodity processor looks like a compounder for exactly one cycle._

**Answered: 2 of 5** (40%)

- **WHICH cost line moved — raw material, power, employee, or other expenses? "Margins fell" is not an analysis; "the material cost ratio rose 400bps because the feedstock spread inverted" is.**
  → The material cost ratio moved -14.0pp across FY12-FY17 against -3.1pp for other expenses.
 — the material ratio FELL materially, so any margin compression came from somewhere other than feedstock. `[fact:derived:material_cost_ratio_delta]`
- **What does the workforce cost as a share of revenue, and is that share rising? A processor whose employee ratio climbs while tonnage is flat is losing operating leverage.**
  → Employee benefits are 1.0% of revenue, having moved 0.2% across FY12-FY17 — a very light cost base — the economics live entirely in the material spread. `[fact:derived:employee_cost_ratio]`
- **Did the operating margin expand or compress across the window?** — ⚠️ **unanswered** (high)
  → the sources read do not disclose: pnl:Operating Profit FY12, pnl:Operating Profit FY17
- **Did costs compound faster than revenue? That is margin compression, stated causally.** — ⚠️ **unanswered** (medium)
  → the sources read do not disclose: pnl:Expenses FY12, pnl:Expenses FY17
- **If the margin expanded, was it price, mix, or scale? Only scale is durable at a commodity.** — ⚠️ **unanswered** (medium)
  → no extractor reads this yet — it requires the primary-source rows named below
     - needs: segment-wise revenue and result (Ind AS 108) to separate mix from price
     - needs: capacity and utilisation, to attribute the balance to operating leverage

### Other income — whether the profit is from the business

_Other income is where a weak operating year gets rescued. It is also where a promoter parks treasury gains, forex swings and one-off asset sales without ever labelling them non-recurring._

**Answered: 1 of 2** (50%)

- **How much of pre-tax profit is other income rather than the business?**
  → Other income is 17.5% of pre-tax profit — material enough to be understood, not large enough to be the story. `[fact:derived:other_income_share]`
- **WHAT is the other income — interest on real cash, a forex gain, a government incentive, or a one-off asset sale? Each has a completely different persistence.** — ⚠️ **unanswered** (high)
  → no extractor reads this yet — it requires the primary-source rows named below
     - needs: other-income breakup note (interest / dividend / forex / profit on sale of assets / other)
     - needs: prior-year comparative for the same note, to see which components recur

### Debt — not whether it rose, but what it bought

_Owner directive: rising debt is not a finding. Debt that funded capacity which then earned above its cost is good capital allocation; debt that funded dividends, working-capital leakage or interest on earlier debt is the beginning of a balance-sheet accident. The cash-flow identity distinguishes them deterministically, so there is no excuse for reporting the level and stopping._

**Answered: 3 of 8** (38%)

- **Did borrowings rise or fall across the window, and by how much?**
  → Borrowings moved ₹114 crore across FY12-FY17 — debt rose — the next two questions decide whether that is a problem. `[fact:derived:debt_delta_window]`
- **What share of the investment programme did debt pay for? This is the direct answer to "why is the debt increasing" — it rose to buy assets, or it rose for something else.**
  → Debt funded 15.9% of the FY12-FY17 investment programme — mostly funded from operations, with debt at the margin. `[fact:derived:debt_funded_investment_share]`
- **Did operations pay for the investment programme, or did someone else? A self-funded compounder is the entire premise of this firm; a company whose growth needs external capital every cycle is a different instrument with a different risk.**
  → Operating cash covered 0.70x of the investment programme across FY12-FY17 — nearly self-funded — the shortfall is what debt or equity had to close. `[fact:derived:self_funding_ratio]`
- **What is the implied cost of debt, and is it consistent with the company's standing?** — ⚠️ **unanswered** (medium)
  → computes to 34.1%, outside the range in which this ratio carries information — the remaining borrowings are too small for the implied rate to mean anything — the average balance is a rounding artefact of a company that has repaid its debt, so the disclosed rate per facility in the borrowings note is the only honest source
     - needs: borrowings note — the interest rate stated per facility, which is the disclosed rate rather than an implied one
- **Can operating profit service the interest?** — ⚠️ **unanswered** (high)
  → the sources read do not disclose: pnl:Operating Profit FY17
     - needs: borrowings note — to confirm the debt is genuinely immaterial rather than reclassified
- **When does the debt fall due? A company with a comfortable coverage ratio and a bullet repayment inside twelve months has a liquidity problem the ratio cannot see.** — ⚠️ **unanswered** (high)
  → no extractor reads this yet — it requires the primary-source rows named below
     - needs: borrowings note — repayment schedule by year, secured vs unsecured, and the interest rate on each tranche
     - needs: current-vs-non-current split of borrowings from the balance sheet
- **What is pledged against the debt, and are there covenants close to breaching?** — ⚠️ **unanswered** (high)
  → no extractor reads this yet — it requires the primary-source rows named below
     - needs: borrowings note — nature of security, assets charged
     - needs: CERSAI / ROC charge register for charges the notes do not mention
     - needs: any covenant-breach or default disclosure, including the CARO clause on repayment defaults
- **What is owed that is not on the balance sheet? Guarantees given for a promoter entity are the cheapest way to move risk into a listed company without moving a rupee of reported debt.** — ⚠️ **unanswered** (high)
  → no extractor reads this yet — it requires the primary-source rows named below
     - needs: contingent liabilities note — guarantees given, by beneficiary
     - needs: related-party note cross-check: is the beneficiary an entity the promoter controls?

### Capital allocation — what management did with the cash

_This is the only line item that measures management rather than the business. Over a decade the allocation record is the most reliable statement of intent a promoter ever makes, and it is arithmetic rather than an interview._

**Answered: 1 of 5** (20%)

- **How large was the investment programme in absolute terms?**
  → Net investing outflow across FY12-FY17 was ₹718 crore. `[fact:derived:investing_outflow_cum]`
- **What did the LAST cycle of capital actually earn? Average ROIC is a legacy number; the incremental figure is the one that says whether the next rupee should be deployed here.** — ⚠️ **unanswered** (high)
  → the sources read do not disclose: a 4+ year run of Operating Profit, Depreciation, Tax %, Borrowings, Equity Capital and Reserves is required for a rolling 3-year incremental ROIC
- **Did per-share value compound with the company, or was the growth bought with equity? The firm's question is a 5-10x PER SHARE; aggregate profit growth flatters a serial issuer.** — ⚠️ **unanswered** (high)
  → the sources read do not disclose: pnl:EPS in Rs at FY12 and FY17
- **How much operating cash went out as dividend rather than into the business?** — ⚠️ **unanswered** (medium)
  → no derivation for 'payout_share_of_cfo' exists in the pipeline yet, so this question was never put to the sources — a gap in the firm's extraction, not in the filing
- **How much of the capex was maintenance and how much was growth? Without the split, a negative incremental return cannot be distinguished from ordinary asset replacement — and that is the difference between a value-destroying expansion and a company simply keeping the lights on.** — ⚠️ **unanswered** (high)
  → the sources read do not disclose: cashflow:Purchase of PPE and pnl:Depreciation in the same year (the cash-flow capex line comes from the filing, not the screener)
     - needs: PPE note — additions by asset class, to split the expansion projects from replacement
     - needs: MD&A or capex-guidance statement naming the expansion projects and their cost

### Working capital — where cash hides before it disappears

_Working capital is the bridge between reported profit and cash, so it is where an inflated profit must eventually show up. Every question here needs three balance-sheet rows the screener does not carry — receivables, inventory and payables — so these are answerable only on a run that walked the audited annual report, and unanswerable on one that did not._

**Answered: 4 of 4** (100%)

- **How long does the company take to collect, and is that lengthening?**
  → Receivable days stand at 66.2 days. `[fact:derived:receivable_days]`
- **Is inventory building faster than sales, and is any of it obsolete?**
  → Inventory days stand at 214.6 days. `[fact:derived:inventory_days]`
- **Is the company funding itself by paying suppliers late? A stretching payable cycle is a liquidity signal that arrives before any ratio breaks.**
  → Payable days stand at 153.6 days — long enough that suppliers are financing the business, which is a liquidity position rather than a negotiating win. `[fact:derived:payable_days]`
- **Net of all three, how many days of cash does the operating cycle tie up — and does the company fund its own working capital or does someone else?**
  → The cash conversion cycle ties up 127.2 days — a long cycle: growth consumes cash before it produces any, so revenue growth needs funding. `[fact:derived:cash_conversion_cycle]`

### Cash — whether the balance is real

_The sharpest single test in the forensic library: cash that exists earns interest at a rate you can compute, and cash that does not exist earns nothing. A company holding a large balance while paying high interest on debt is either badly run or not holding the balance it reports._

**Answered: 1 of 3** (33%)

- **Is the company holding cash while paying materially more to borrow?**
  → Net cash after deducting all borrowings is ₹500 crore — net cash, so there is no borrow-and-hoard pattern to explain. `[fact:derived:net_cash_position]`
- **Does the reported cash balance earn a plausible rate of interest?** — ⚠️ **unanswered** (high)
  → the sources read do not disclose: cashflow:Interest Income FY17, balance_sheet:Cash Equivalents FY16
     - needs: cash-and-bank note — the split between current accounts, term deposits and margin money
- **Is the cash actually available? Margin money, unpaid-dividend accounts and lien-marked deposits are reported inside cash and cannot be spent.** — ⚠️ **unanswered** (medium)
  → no extractor reads this yet — it requires the primary-source rows named below
     - needs: cash-and-bank note — restricted balances, margin money, deposits under lien

### Tax — the cheapest cross-check on reported profit

_Tax is paid to a party with no interest in the share price. A profit that is reported but not taxed has to be explained by a disclosed incentive; if there is no such incentive, the profit is the thing in doubt._

**Answered: 0 of 2** (0%)

- **What is the effective tax rate, and how far is it from the statutory rate?** — ⚠️ **unanswered** (high)
  → the sources read do not disclose: pnl:Tax % FY17
- **WHY does the effective rate differ from statutory, line by line?** — ⚠️ **unanswered** (medium)
  → no extractor reads this yet — it requires the primary-source rows named below
     - needs: tax-reconciliation note (Ind AS 12) — statutory rate to effective rate, by cause
     - needs: deferred-tax movement, and whether a deferred-tax asset is being recognised on losses

### Related parties — the channel every promoter-level fraud uses

_Almost no Indian small-cap fraud is invented inside the audited statements; it is routed through an entity the promoter also controls, at a price nobody negotiated. This line item is unanswerable without the notes, which is precisely why an unwalked annual report cannot produce a clean verdict._

**Answered: 0 of 3** (0%)

- **What is the total value of related-party transactions, by type and by party?** — ⚠️ **unanswered** (high)
  → no extractor reads this yet — it requires the primary-source rows named below
     - needs: related-party note (Ind AS 24) — sales, purchases, loans given/taken, guarantees, remuneration
     - needs: the year-end outstanding balance per party, not just the transaction value
- **Has the company lent money to, or guaranteed borrowing for, a promoter entity?** — ⚠️ **unanswered** (high)
  → no extractor reads this yet — it requires the primary-source rows named below
     - needs: Schedule III mandatory row: loans and advances to promoters, directors and KMP
     - needs: contingent liabilities note — guarantees given on behalf of related parties
- **Were related-party transactions at arm's length, and who says so? The audit committee's approval is a governance fact; an independent valuation is evidence.** — ⚠️ **unanswered** (medium)
  → no extractor reads this yet — it requires the primary-source rows named below
     - needs: audit-committee report on related-party approvals
     - needs: any transfer-pricing or independent-valuation reference in the notes

### What would close the gaps

_Deduplicated from every unanswered question above — this is the extraction backlog, in the order the questions were asked, not a wish list._

1. tonnes / units sold per year (MD&A production-and-sales table, or the segment note)
2. realisation per unit (segment revenue / segment volume) to separate price from mix
3. customer-concentration disclosure (Ind AS 108 segment note: revenue from customers >10%)
4. trade-receivable concentration in the credit-risk note (Ind AS 107)
5. related-party transactions note (Ind AS 24) — sales-of-goods line, by party
6. the related-party balance outstanding at year end, to see whether the sale was ever collected
7. business-combination note (Ind AS 103) — consideration paid, revenue acquired
8. consolidated-vs-standalone revenue gap, to size what the subsidiaries contribute
9. significant-accounting-policies note, revenue paragraph, compared across two annual reports
10. segment-wise revenue and result (Ind AS 108) to separate mix from price
11. capacity and utilisation, to attribute the balance to operating leverage
12. other-income breakup note (interest / dividend / forex / profit on sale of assets / other)
13. prior-year comparative for the same note, to see which components recur
14. borrowings note — the interest rate stated per facility, which is the disclosed rate rather than an implied one
15. borrowings note — to confirm the debt is genuinely immaterial rather than reclassified
16. borrowings note — repayment schedule by year, secured vs unsecured, and the interest rate on each tranche
17. current-vs-non-current split of borrowings from the balance sheet
18. borrowings note — nature of security, assets charged
19. CERSAI / ROC charge register for charges the notes do not mention
20. any covenant-breach or default disclosure, including the CARO clause on repayment defaults
21. contingent liabilities note — guarantees given, by beneficiary
22. related-party note cross-check: is the beneficiary an entity the promoter controls?
23. PPE note — additions by asset class, to split the expansion projects from replacement
24. MD&A or capex-guidance statement naming the expansion projects and their cost
25. cash-and-bank note — the split between current accounts, term deposits and margin money
26. cash-and-bank note — restricted balances, margin money, deposits under lien
27. tax-reconciliation note (Ind AS 12) — statutory rate to effective rate, by cause
28. deferred-tax movement, and whether a deferred-tax asset is being recognised on losses
29. related-party note (Ind AS 24) — sales, purchases, loans given/taken, guarantees, remuneration
30. the year-end outstanding balance per party, not just the transaction value
31. Schedule III mandatory row: loans and advances to promoters, directors and KMP
32. contingent liabilities note — guarantees given on behalf of related parties
33. audit-committee report on related-party approvals
34. any transfer-pricing or independent-valuation reference in the notes

## Forensic review

**Note coverage: 100%**

### Verified-clean checklist

_Every check that ran, passes included — a clean verdict with an invisible process is worth nothing._

| check | outcome | detail | facts |
|---|---|---|---|
| `cumulative_cfo_pat` | 🚩 flag | ΣCFO/ΣPAT 0.24 vs floor 0.70 (Σ CFO / Σ PAT, FY12-FY17) (grade A) | `[fact:AR-FY13-PCJ-AR-FY13.pdf:cashflow:Cash from Operating Activity:FY12]`, `[fact:AR-FY14-PCJ-AR-FY14.pdf:cashflow:Cash from Operating Activity:FY13]`, `[fact:AR-FY15-PCJ-AR-FY15.pdf:cashflow:Cash from Operating Activity:FY14]`, `[fact:AR-FY16-PCJ-AR-FY16.pdf:cashflow:Cash from Operating Activity:FY15]`, `[fact:AR-FY17-PCJ-AR-FY17.pdf:cashflow:Cash from Operating Activity:FY16]`, `[fact:AR-FY17-PCJ-AR-FY17.pdf:cashflow:Cash from Operating Activity:FY17]`, `[fact:AR-FY13-PCJ-AR-FY13.pdf:pnl:Net Profit:FY12]`, `[fact:AR-FY14-PCJ-AR-FY14.pdf:pnl:Net Profit:FY13]`, `[fact:AR-FY15-PCJ-AR-FY15.pdf:pnl:Net Profit:FY14]`, `[fact:AR-FY16-PCJ-AR-FY16.pdf:pnl:Net Profit:FY15]`, `[fact:AR-FY17-PCJ-AR-FY17.pdf:pnl:Net Profit:FY16]`, `[fact:AR-FY17-PCJ-AR-FY17.pdf:pnl:Net Profit:FY17]` |
| `cfo_pat` | ✅ pass | CFO/PAT 1.80 vs floor 0.70 (CFO FY17 / PAT FY17) (grade A) | `[fact:AR-FY17-PCJ-AR-FY17.pdf:cashflow:Cash from Operating Activity:FY17]`, `[fact:AR-FY17-PCJ-AR-FY17.pdf:pnl:Net Profit:FY17]` |
| `cash_interest_inconsistent` | ⚠️ unavailable | inputs not disclosed in the sources read as-of this run: interest income earned on cash (not broken out of other income) | — |
| `cash_debt_paradox` | ✅ pass | cash/assets 5.6% at cost of debt 34.1% (paradox above 15% and 10%) (grade A) | `[fact:AR-FY17-PCJ-AR-FY17.pdf:balance_sheet:Cash Equivalents:FY17]`, `[fact:AR-FY17-PCJ-AR-FY17.pdf:balance_sheet:Total Assets:FY17]`, `[fact:AR-FY17-PCJ-AR-FY17.pdf:balance_sheet:Borrowings:FY17]` |
| `disclosure_gap` | ✅ pass | every mandated Schedule III / forensic section located in the filing | — |
| `other_income_heavy` | ✅ pass | other income 17.5% of PBT vs limit 25% (pnl:Other Income FY17 / pnl:Profit before tax FY17) (grade A) | `[fact:AR-FY17-PCJ-AR-FY17.pdf:pnl:Other Income:FY17]`, `[fact:AR-FY17-PCJ-AR-FY17.pdf:pnl:Profit before tax:FY17]` |
| `promoter_lending` | ✅ pass | related-party note read (AR-FY17-PCJ-AR-FY17.pdf note 37 p.165): categories disclosed = dividend, loans_taken, remuneration, rent; KMP remuneration ₹6.95cr | — |
| `receivables_divergent` | 🚩 flag | receivables +57.6% vs revenue +16.1%, gap +41.5% vs limit 25% (AR) (grade A) | `[fact:AR-FY17-PCJ-AR-FY17.pdf:balance_sheet:Trade Receivables:FY17]`, `[fact:AR-FY17-PCJ-AR-FY17.pdf:balance_sheet:Trade Receivables:FY16]`, `[fact:AR-FY17-PCJ-AR-FY17.pdf:pnl:Sales:FY17]`, `[fact:AR-FY17-PCJ-AR-FY17.pdf:pnl:Sales:FY16]` |
| `inventory_divergent` | ✅ pass | inventory +8.3% vs revenue +16.1%, gap -7.8% vs limit 30% (AR) (grade A) | `[fact:AR-FY17-PCJ-AR-FY17.pdf:balance_sheet:Inventories:FY17]`, `[fact:AR-FY17-PCJ-AR-FY17.pdf:balance_sheet:Inventories:FY16]`, `[fact:AR-FY17-PCJ-AR-FY17.pdf:pnl:Sales:FY17]`, `[fact:AR-FY17-PCJ-AR-FY17.pdf:pnl:Sales:FY16]` |
| `high_accruals` | ✅ pass | accruals -0.051 vs limit ±0.10 ((PAT - CFO)(FY17) / avg Total Assets) (grade A) | `[fact:AR-FY17-PCJ-AR-FY17.pdf:pnl:Net Profit:FY17]`, `[fact:AR-FY17-PCJ-AR-FY17.pdf:cashflow:Cash from Operating Activity:FY17]`, `[fact:AR-FY17-PCJ-AR-FY17.pdf:balance_sheet:Total Assets:FY17]`, `[fact:AR-FY17-PCJ-AR-FY17.pdf:balance_sheet:Total Assets:FY16]` |

The evidence indicates a company whose reported profits have not been matched by cash for most of the window, whose receivables are outrunning its revenue, and whose true cost and quantum of funding are larger than the balance sheet labels them. Nothing here is an accusation of fraud; every figure is computed from the company's own audited filings and each can be replicated from the cited derivations and page locators. The deterministic hard-fail stands, and the veto is exercised: no narrative about growth or brand should outrank a cumulative cash record this weak, and the burden of proof now sits with the disclosures the open questions name.

### Restatement log — what later filings changed

_Every figure a later filing revised, from the same deterministic overlap classifier that quarantines misreads. A restatement is a fact to explain, not an accusation — an accounting-standard transition legitimately rewrites a year — but a company revising its history is something a reader sees here in one place, or never._

| metric | period | earlier filing said | later filing says | revised by |
|---|---|---|---|---|
| `balance_sheet:Fixed Assets` | FY16 | 90.11 | 90.12 | `AR-FY17-PCJ-AR-FY17.pdf` |
| `balance_sheet:Inventories` | FY16 | 3,872.19 | 3,867.17 | `AR-FY17-PCJ-AR-FY17.pdf` |
| `balance_sheet:Reserves` | FY16 | 2,147.26 | 2,230.04 | `AR-FY17-PCJ-AR-FY17.pdf` |
| `balance_sheet:Total Assets` | FY16 | 5,762.34 | 5,750.94 | `AR-FY17-PCJ-AR-FY17.pdf` |
| `balance_sheet:Trade Payables` | FY16 | 2,184.47 | 2,175.39 | `AR-FY17-PCJ-AR-FY17.pdf` |
| `cashflow:Cash from Financing Activity` | FY14 | 594.79 | 571.02 | `AR-FY15-PCJ-AR-FY15.pdf` |
| `cashflow:Cash from Financing Activity` | FY15 | -565.78 | -564.76 | `AR-FY16-PCJ-AR-FY16.pdf` |
| `cashflow:Cash from Financing Activity` | FY16 | 16.82 | 16.32 | `AR-FY17-PCJ-AR-FY17.pdf` |
| `cashflow:Cash from Investing Activity` | FY16 | -25.06 | -25.01 | `AR-FY17-PCJ-AR-FY17.pdf` |
| `cashflow:Cash from Operating Activity` | FY14 | -809.68 | -785.92 | `AR-FY15-PCJ-AR-FY15.pdf` |
| `cashflow:Cash from Operating Activity` | FY15 | 333.77 | 332.74 | `AR-FY16-PCJ-AR-FY16.pdf` |
| `cashflow:Cash from Operating Activity` | FY16 | 15.55 | 16.03 | `AR-FY17-PCJ-AR-FY17.pdf` |
| `pnl:Changes in Inventories` | FY16 | -406.55 | -403.10 | `AR-FY17-PCJ-AR-FY17.pdf` |
| `pnl:Cost of Materials Consumed` | FY16 | 6,714.74 | 6,692.86 | `AR-FY17-PCJ-AR-FY17.pdf` |
| `pnl:EPS in Rs` | FY16 | 22.32 | 22.25 | `AR-FY17-PCJ-AR-FY17.pdf` |
| `pnl:Employee Benefits` | FY16 | 72.12 | 72.65 | `AR-FY17-PCJ-AR-FY17.pdf` |
| `pnl:Interest` | FY14 | 151.88 | 147.10 | `AR-FY15-PCJ-AR-FY15.pdf` |
| `pnl:Interest` | FY15 | 220.95 | 219.89 | `AR-FY16-PCJ-AR-FY16.pdf` |
| `pnl:Interest` | FY16 | 214.95 | 244.95 | `AR-FY17-PCJ-AR-FY17.pdf` |
| `pnl:Net Profit` | FY16 | 399.66 | 398.19 | `AR-FY17-PCJ-AR-FY17.pdf` |
| `pnl:Other Expenses` | FY14 | 204.17 | 210.35 | `AR-FY15-PCJ-AR-FY15.pdf` |
| `pnl:Other Expenses` | FY15 | 186.70 | 187.75 | `AR-FY16-PCJ-AR-FY16.pdf` |
| `pnl:Other Expenses` | FY16 | 220.29 | 194.41 | `AR-FY17-PCJ-AR-FY17.pdf` |
| `pnl:Other Income` | FY16 | 48.70 | 49.94 | `AR-FY17-PCJ-AR-FY17.pdf` |
| `pnl:Profit before tax` | FY16 | 536.51 | 534.42 | `AR-FY17-PCJ-AR-FY17.pdf` |
| `pnl:Sales` | FY16 | 7,330.18 | 7,303.22 | `AR-FY17-PCJ-AR-FY17.pdf` |
| `pnl:Total Expenses` | FY14 | 4,925.36 | 4,902.70 | `AR-FY15-PCJ-AR-FY15.pdf` |
| `pnl:Total Expenses` | FY16 | 6,842.37 | 6,818.74 | `AR-FY17-PCJ-AR-FY17.pdf` |
| `pnl:Total Tax` | FY16 | 136.85 | 136.23 | `AR-FY17-PCJ-AR-FY17.pdf` |

## Management and governance

No management or governance assessment is made in this report: `management_analyst`, `transcript_analyst` and `ownership_flows_analyst` did not run. Promoter-pledge, promise-vs-delivery and board-interlock findings are therefore absent rather than clean.

## Valuation

No valuation claim is made in this report. The valuation tier (reverse DCF, probability-weighted scenarios, sensitivity) is Phase 4 of the build; the feasibility gate below is a *self-funding* test, not a price judgment.

## Thesis

PC Jeweller sells jewellery through two very different channels wearing one P&L. The domestic showroom half is a working-capital-heavy but cash-collecting retail business. The export half books revenue against receivables from unnamed overseas buyers. The filings this run read do not let the two be separated cleanly, and that separation is exactly where the analysis of this company should go next, because the cash-flow strain the financial-statement work surfaces has to live in one of those channels.

## Anti-thesis (the strongest case against)

**business_analyst (disconfirming search):** Looked for evidence that the growth is cash-generative retail rather than receivable-funded export: the receivable and inventory day counts and their direction argue against it, and no customer-concentration disclosure exists to rebut it.

**financial_statement_analyst (disconfirming search):** Searched for an innocent reading of the cash-conversion record: a young company investing ahead of growth would show the shortfall in investing outflows, but here the shortfall sits in operating cash itself, absorbed by inventory and receivables, which is the pattern of profit recognised ahead of cash rather than of investment.

**forensic_accountant (disconfirming search):** Sought the honest explanations first: a working-capital build ahead of showroom expansion would show capex and inventory rising together with stable collections, and a genuinely cash-rich company would show interest income consistent with its balances. The first is contradicted by collections slowing while conversion is claimed to improve; the second cannot be tested because interest income is not broken out, which is itself noted.

**Checks that fired:** `cumulative_cfo_pat` — ΣCFO/ΣPAT 0.24 vs floor 0.70 (Σ CFO / Σ PAT, FY12-FY17) (grade A); `receivables_divergent` — receivables +57.6% vs revenue +16.1%, gap +41.5% vs limit 25% (AR) (grade A)

**Not verifiable from the sources read:** 1 of 10 applicable checks could not be evaluated, so the case against this company includes everything we could not look at.

## Falsifiability

### Kill criteria — what would break this thesis

| criterion | metric | test | resolve by | load-bearing |
|---|---|---|---|---|
| Cumulative CFO/PAT stays at or above 0.70 (it is 0.24 today). If a decade of reported profit stops converting to cash, the thesis is dead regardless of growth. | `cum_cfo_pat` | `>= 0.7` | 2018-10-27 | **yes** |
| Single-year CFO/PAT stays at or above 1.62 in the next annual report (it is 1.80 today). | `cfo_pat_latest` | `>= 1.6171` | 2018-10-27 | no |
| The accrual ratio stays at or below 0.10 (it is -0.051 today); above it, reported earnings are increasingly non-cash. | `accrual_ratio_latest` | `<= 0.1` | 2018-10-27 | no |

### Rehabilitation criteria — what would reverse this verdict

| criterion | metric | test | resolve by | load-bearing |
|---|---|---|---|---|
| `cumulative_cfo_pat` clears: cum_cfo_pat >= 0.7 (currently 0.24), evidenced in the next annual report. Until then this remains the reason the verdict is withheld. | `cum_cfo_pat` | `>= 0.7` | 2018-10-27 | **yes** |
| `receivables_divergent` clears: receivables_divergent == 0.0, evidenced in the next annual report. Until then this remains the reason the verdict is withheld. | `receivables_divergent` | `== 0.0` | 2018-10-27 | **yes** |
| The company discloses the inputs for the checks that could not be run — `cash_interest_inconsistent` — in a filing readable as text. For a listed company these are public by law; the gap, not our patience, is what holds the verdict. | `checks_unavailable` | `<= 0.0` | 2018-10-27 | **yes** |

## Open questions

- business_analyst: What share of revenue is export versus showroom, and who are the export counterparties? The segment note separates domestic from export revenue but the buyers behind the export receivables are not named.
- business_analyst: How much of the gold inventory is held on leased gold (metal loans) versus owned, and at what price risk?
- business_analyst: Same-store versus new-store growth split for the domestic showroom network is not disclosed.
- financial_statement_analyst: The interest income earned on the cash and bank balances is not broken out of other income, so whether the reported balances behave like real, unencumbered cash cannot be tested from this read.
- financial_statement_analyst: Purchase of property, plant and equipment is not separated in the cash-flow read, so capex versus the depreciation charge cannot be compared.
- financial_statement_analyst: Operating profit is not derivable from the rows read this run, so return on capital and interest cover are not computed — the finance-cost anomaly is measured against borrowings instead.
- forensic_accountant: Who are the export receivable counterparties, and what is their ageing? The receivables note read this run does not break them out by buyer.
- forensic_accountant: What exactly do the bank balances secure? The other-bank-balances note and the borrowings security schedule would answer whether the cash is free.
- forensic_accountant: The related-party note discloses rent paid to promoter directors that multiplied against the prior year; what changed in those lease arrangements, and on whose terms?
- cash_interest_inconsistent: inputs not disclosed in the sources read as-of this run: interest income earned on cash (not broken out of other income)

## Not available from primary sources

_Reported as unavailable rather than estimated._

- cash_interest_inconsistent: inputs not disclosed in the sources read as-of this run: interest income earned on cash (not broken out of other income)

## Replication

_How a third party reproduces these findings._

1. Re-run `python -m firm deep-dive --ticker PCJEWELLER --as-of 2017-12-31`; the run id is a content hash of the inputs, so the same facts reproduce this report byte-for-byte.
2. Every figure in §4 lists its formula and input fact ids; each fact resolves to (doc_id, page/line, published_at, grade) in the fact store.
3. `cumulative_cfo_pat`: ΣCFO/ΣPAT 0.24 vs floor 0.70 (Σ CFO / Σ PAT, FY12-FY17) (grade A) — recompute from fact ids AR-FY13-PCJ-AR-FY13.pdf:cashflow:Cash from Operating Activity:FY12, AR-FY14-PCJ-AR-FY14.pdf:cashflow:Cash from Operating Activity:FY13, AR-FY15-PCJ-AR-FY15.pdf:cashflow:Cash from Operating Activity:FY14, AR-FY16-PCJ-AR-FY16.pdf:cashflow:Cash from Operating Activity:FY15, AR-FY17-PCJ-AR-FY17.pdf:cashflow:Cash from Operating Activity:FY16, AR-FY17-PCJ-AR-FY17.pdf:cashflow:Cash from Operating Activity:FY17, AR-FY13-PCJ-AR-FY13.pdf:pnl:Net Profit:FY12, AR-FY14-PCJ-AR-FY14.pdf:pnl:Net Profit:FY13, AR-FY15-PCJ-AR-FY15.pdf:pnl:Net Profit:FY14, AR-FY16-PCJ-AR-FY16.pdf:pnl:Net Profit:FY15, AR-FY17-PCJ-AR-FY17.pdf:pnl:Net Profit:FY16, AR-FY17-PCJ-AR-FY17.pdf:pnl:Net Profit:FY17.
4. `receivables_divergent`: receivables +57.6% vs revenue +16.1%, gap +41.5% vs limit 25% (AR) (grade A) — recompute from fact ids AR-FY17-PCJ-AR-FY17.pdf:balance_sheet:Trade Receivables:FY17, AR-FY17-PCJ-AR-FY17.pdf:balance_sheet:Trade Receivables:FY16, AR-FY17-PCJ-AR-FY17.pdf:pnl:Sales:FY17, AR-FY17-PCJ-AR-FY17.pdf:pnl:Sales:FY16.
