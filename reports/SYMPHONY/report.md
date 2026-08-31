# Symphony Limited (SYMPHONY) — research note

**Verdict: `FORENSIC_CAUTION` — Forensic caution — red flags evidenced below**

_As-of 2018-12-31 · run `2018-12-31-e2051e41d639` · confidence 0.29 (from 20 facts, lowest grade A) · 80% of the applicable playbook was evaluable, 12% of notes carry a substantive disposition, 31% of the line-by-line questions could be answered, and the weakest grade relied on is A (cap 0.90)_

> Research artifact only. Not investment advice, not a recommendation to transact, and not an offer to buy or sell any security. Figures are computed deterministically from cited primary sources; anything not disclosed is reported as UNAVAILABLE.

_Agents: business_analyst@1.0.0, financial_statement_analyst@1.0.0, forensic_accountant@1.0.0_

## Executive summary

The statements describe a business whose profit is real by the cumulative cash test at 0.79 [fact:derived:cum_cfo_pat] but whose latest-year optics are muddied by treasury classification at 0.55 [fact:derived:cfo_pat_latest], whose working capital at 48.2 [fact:derived:cash_conversion_cycle] days is short and calm, and whose per-share record at 10.9% [fact:derived:eps_cagr] against 25.1% [fact:derived:pat_cagr] aggregate is dominated by a share-capital event the sources read here do not explain. The window-level cost-ratio deltas are contaminated by a disclosure-basis change and are deliberately not narrated as cost moves.

**Verdict rationale (deterministic):** deterministic screen returned REVIEW with 2 flag(s); at or above severity HIGH: cfo_pat_low

### The load-bearing points

- **[observation, grade A]** The deterministic screen returns REVIEW on two flags: single-year cash conversion at 0.55 [fact:derived:cfo_pat_latest] below the policy floor, and accruals at 0.126 [fact:derived:accrual_ratio_latest] above the policy limit. Every stock-flow divergence check passes: receivables and inventory both grew more slowly, relative to revenue, than the configured limits allow.
- **[observation, grade A]** The cost base is bought, not made: the company purchases 293.14 [fact:SYMPHONY-AR-FY18.pdf:pnl:Purchases of Stock-in-Trade:FY18] crore of finished stock-in-trade against 93.89 [fact:SYMPHONY-AR-FY18.pdf:pnl:Cost of Materials Consumed:FY18] crore of materials consumed — an outsourced-manufacturing model where the company owns the brand, the design and the distribution while contract vendors own the factories.
- **[observation, grade A]** Operations more than fund the investment programme: cumulative operating cash of 546.6 [fact:derived:cfo_cum_window] crore against 349.1 [fact:derived:investing_outflow_cum] crore of investing outflow, a self-funding ratio of 1.57 [fact:derived:self_funding_ratio] — growth here has not needed outside capital.

## What this business actually does

Designs, brands and distributes air coolers; manufacturing is outsourced to contract vendors, so the company's own capital sits in brand, distribution and a large treasury rather than plant.

## The numbers (deterministic — Law 1)

| metric | value | source |
|---|---|---|
| revenue_cagr | 0.18 | `[fact:derived:revenue_cagr]` derivation:(pnl:Sales FY18 / pnl:Sales FY12)^(1/5.7496) - 1 inputs SYMPHONY-AR-FY13.pdf:pnl:Sales:FY12, SYMPHONY-AR-FY18.pdf:pnl:Sales:FY18 (grade A) |
| pat_cagr | 0.25 | `[fact:derived:pat_cagr]` derivation:(pnl:Net Profit FY18 / pnl:Net Profit FY12)^(1/5.7496) - 1 inputs SYMPHONY-AR-FY13.pdf:pnl:Net Profit:FY12, SYMPHONY-AR-FY18.pdf:pnl:Net Profit:FY18 (grade A) |
| cum_cfo_pat | 0.79 | `[fact:derived:cum_cfo_pat]` derivation:Σ CFO / Σ PAT, FY12-FY18 inputs SYMPHONY-AR-FY13.pdf:cashflow:Cash from Operating Activity:FY12, SYMPHONY-AR-FY14.pdf:cashflow:Cash from Operating Activity:FY13, SYMPHONY-AR-FY15.pdf:cashflow:Cash from Operating Activity:FY14, SYMPHONY-AR-FY16.pdf:cashflow:Cash from Operating Activity:FY15, SYMPHONY-AR-FY18.pdf:cashflow:Cash from Operating Activity:FY17, SYMPHONY-AR-FY18.pdf:cashflow:Cash from Operating Activity:FY18, SYMPHONY-AR-FY13.pdf:pnl:Net Profit:FY12, SYMPHONY-AR-FY14.pdf:pnl:Net Profit:FY13, SYMPHONY-AR-FY15.pdf:pnl:Net Profit:FY14, SYMPHONY-AR-FY16.pdf:pnl:Net Profit:FY15, SYMPHONY-AR-FY18.pdf:pnl:Net Profit:FY17, SYMPHONY-AR-FY18.pdf:pnl:Net Profit:FY18 (grade A) |
| cfo_pat_latest | 0.55 | `[fact:derived:cfo_pat_latest]` derivation:CFO FY18 / PAT FY18 inputs SYMPHONY-AR-FY18.pdf:cashflow:Cash from Operating Activity:FY18, SYMPHONY-AR-FY18.pdf:pnl:Net Profit:FY18 (grade A) |
| accrual_ratio_latest | 0.13 | `[fact:derived:accrual_ratio_latest]` derivation:(PAT - CFO)(FY18) / avg Total Assets inputs SYMPHONY-AR-FY18.pdf:pnl:Net Profit:FY18, SYMPHONY-AR-FY18.pdf:cashflow:Cash from Operating Activity:FY18, SYMPHONY-AR-FY18.pdf:balance_sheet:Total Assets:FY18, SYMPHONY-AR-FY18.pdf:balance_sheet:Total Assets:FY17 (grade A) |
| other_income_share | 0.20 | `[fact:derived:other_income_share]` derivation:pnl:Other Income FY18 / pnl:Profit before tax FY18 inputs SYMPHONY-AR-FY18.pdf:pnl:Other Income:FY18, SYMPHONY-AR-FY18.pdf:pnl:Profit before tax:FY18 (grade A) |
| eps_cagr | 0.11 | `[fact:derived:eps_cagr]` derivation:(pnl:EPS in Rs FY18 / pnl:EPS in Rs FY12)^(1/5.7496) - 1 inputs SYMPHONY-AR-FY13.pdf:pnl:EPS in Rs:FY12, SYMPHONY-AR-FY18.pdf:pnl:EPS in Rs:FY18 (grade A) |
| cfo_cum_window | 546.63 | `[fact:derived:cfo_cum_window]` derivation:Σ CFO, FY12-FY18 inputs SYMPHONY-AR-FY13.pdf:cashflow:Cash from Operating Activity:FY12, SYMPHONY-AR-FY14.pdf:cashflow:Cash from Operating Activity:FY13, SYMPHONY-AR-FY15.pdf:cashflow:Cash from Operating Activity:FY14, SYMPHONY-AR-FY16.pdf:cashflow:Cash from Operating Activity:FY15, SYMPHONY-AR-FY18.pdf:cashflow:Cash from Operating Activity:FY17, SYMPHONY-AR-FY18.pdf:cashflow:Cash from Operating Activity:FY18 (grade A) |
| investing_outflow_cum | 349.15 | `[fact:derived:investing_outflow_cum]` derivation:-Σ CFI, FY12-FY18 inputs SYMPHONY-AR-FY13.pdf:cashflow:Cash from Investing Activity:FY12, SYMPHONY-AR-FY14.pdf:cashflow:Cash from Investing Activity:FY13, SYMPHONY-AR-FY15.pdf:cashflow:Cash from Investing Activity:FY14, SYMPHONY-AR-FY18.pdf:cashflow:Cash from Investing Activity:FY17, SYMPHONY-AR-FY18.pdf:cashflow:Cash from Investing Activity:FY18 (grade A) |
| self_funding_ratio | 1.57 | `[fact:derived:self_funding_ratio]` derivation:Σ CFO / -Σ CFI, FY12-FY18 (>=1 means operations paid for the investment programme) inputs SYMPHONY-AR-FY13.pdf:cashflow:Cash from Operating Activity:FY12, SYMPHONY-AR-FY14.pdf:cashflow:Cash from Operating Activity:FY13, SYMPHONY-AR-FY15.pdf:cashflow:Cash from Operating Activity:FY14, SYMPHONY-AR-FY16.pdf:cashflow:Cash from Operating Activity:FY15, SYMPHONY-AR-FY18.pdf:cashflow:Cash from Operating Activity:FY17, SYMPHONY-AR-FY18.pdf:cashflow:Cash from Operating Activity:FY18, SYMPHONY-AR-FY13.pdf:cashflow:Cash from Investing Activity:FY12, SYMPHONY-AR-FY14.pdf:cashflow:Cash from Investing Activity:FY13, SYMPHONY-AR-FY15.pdf:cashflow:Cash from Investing Activity:FY14, SYMPHONY-AR-FY18.pdf:cashflow:Cash from Investing Activity:FY17, SYMPHONY-AR-FY18.pdf:cashflow:Cash from Investing Activity:FY18 (grade A) |
| receivable_days | 28.12 | `[fact:derived:receivable_days]` derivation:balance_sheet:Trade Receivables FY18 / pnl:Sales FY18 x 365 inputs SYMPHONY-AR-FY18.pdf:balance_sheet:Trade Receivables:FY18, SYMPHONY-AR-FY18.pdf:pnl:Sales:FY18 (grade A) |
| inventory_days | 75.37 | `[fact:derived:inventory_days]` derivation:balance_sheet:Inventories FY18 / (Cost of Materials Consumed + Purchases of Stock-in-Trade + Changes in Inventories) FY18 x 365 inputs SYMPHONY-AR-FY18.pdf:balance_sheet:Inventories:FY18, SYMPHONY-AR-FY18.pdf:pnl:Cost of Materials Consumed:FY18, SYMPHONY-AR-FY18.pdf:pnl:Purchases of Stock-in-Trade:FY18, SYMPHONY-AR-FY18.pdf:pnl:Changes in Inventories:FY18 (grade A) |
| payable_days | 55.27 | `[fact:derived:payable_days]` derivation:balance_sheet:Trade Payables FY18 / (Cost of Materials Consumed + Purchases of Stock-in-Trade + Changes in Inventories) FY18 x 365 inputs SYMPHONY-AR-FY18.pdf:balance_sheet:Trade Payables:FY18, SYMPHONY-AR-FY18.pdf:pnl:Cost of Materials Consumed:FY18, SYMPHONY-AR-FY18.pdf:pnl:Purchases of Stock-in-Trade:FY18, SYMPHONY-AR-FY18.pdf:pnl:Changes in Inventories:FY18 (grade A) |
| receivable_days_delta | 3.16 | `[fact:derived:receivable_days_delta]` derivation:Receivable days FY18 - FY17 (positive = collection is slowing) inputs SYMPHONY-AR-FY18.pdf:balance_sheet:Trade Receivables:FY18, SYMPHONY-AR-FY18.pdf:pnl:Sales:FY18, SYMPHONY-AR-FY18.pdf:balance_sheet:Trade Receivables:FY17, SYMPHONY-AR-FY18.pdf:pnl:Sales:FY17 (grade A) |
| cash_conversion_cycle | 48.23 | `[fact:derived:cash_conversion_cycle]` derivation:Receivable days + Inventory days - Payable days, FY18 (days of cash tied up) inputs SYMPHONY-AR-FY18.pdf:balance_sheet:Trade Receivables:FY18, SYMPHONY-AR-FY18.pdf:pnl:Sales:FY18, SYMPHONY-AR-FY18.pdf:balance_sheet:Inventories:FY18, SYMPHONY-AR-FY18.pdf:pnl:Cost of Materials Consumed:FY18, SYMPHONY-AR-FY18.pdf:pnl:Purchases of Stock-in-Trade:FY18, SYMPHONY-AR-FY18.pdf:pnl:Changes in Inventories:FY18, SYMPHONY-AR-FY18.pdf:balance_sheet:Trade Payables:FY18, SYMPHONY-AR-FY18.pdf:pnl:Cost of Materials Consumed:FY18, SYMPHONY-AR-FY18.pdf:pnl:Purchases of Stock-in-Trade:FY18, SYMPHONY-AR-FY18.pdf:pnl:Changes in Inventories:FY18 (grade A) |
| material_cost_ratio | 0.12 | `[fact:derived:material_cost_ratio]` derivation:Cost of Materials Consumed FY18 / pnl:Sales FY18 inputs SYMPHONY-AR-FY18.pdf:pnl:Cost of Materials Consumed:FY18, SYMPHONY-AR-FY18.pdf:pnl:Sales:FY18 (grade A) |
| material_cost_ratio_delta | -0.22 | `[fact:derived:material_cost_ratio_delta]` derivation:Cost of Materials Consumed/Sales FY18 - Cost of Materials Consumed/Sales FY12 inputs SYMPHONY-AR-FY13.pdf:pnl:Cost of Materials Consumed:FY12, SYMPHONY-AR-FY13.pdf:pnl:Sales:FY12, SYMPHONY-AR-FY18.pdf:pnl:Cost of Materials Consumed:FY18, SYMPHONY-AR-FY18.pdf:pnl:Sales:FY18 (grade A) |
| employee_cost_ratio | 0.09 | `[fact:derived:employee_cost_ratio]` derivation:Employee Benefits FY18 / pnl:Sales FY18 inputs SYMPHONY-AR-FY18.pdf:pnl:Employee Benefits:FY18, SYMPHONY-AR-FY18.pdf:pnl:Sales:FY18 (grade A) |
| employee_cost_ratio_delta | 0.00 | `[fact:derived:employee_cost_ratio_delta]` derivation:Employee Benefits/Sales FY18 - Employee Benefits/Sales FY12 inputs SYMPHONY-AR-FY13.pdf:pnl:Employee Benefits:FY12, SYMPHONY-AR-FY13.pdf:pnl:Sales:FY12, SYMPHONY-AR-FY18.pdf:pnl:Employee Benefits:FY18, SYMPHONY-AR-FY18.pdf:pnl:Sales:FY18 (grade A) |
| other_expense_ratio | 0.11 | `[fact:derived:other_expense_ratio]` derivation:Other Expenses FY18 / pnl:Sales FY18 inputs SYMPHONY-AR-FY18.pdf:pnl:Other Expenses:FY18, SYMPHONY-AR-FY18.pdf:pnl:Sales:FY18 (grade A) |
| other_expense_ratio_delta | -0.14 | `[fact:derived:other_expense_ratio_delta]` derivation:Other Expenses/Sales FY18 - Other Expenses/Sales FY12 inputs SYMPHONY-AR-FY13.pdf:pnl:Other Expenses:FY12, SYMPHONY-AR-FY13.pdf:pnl:Sales:FY12, SYMPHONY-AR-FY18.pdf:pnl:Other Expenses:FY18, SYMPHONY-AR-FY18.pdf:pnl:Sales:FY18 (grade A) |
| cash_yield_latest | 0.13 | `[fact:derived:cash_yield_latest]` derivation:|Interest Income FY18| / average (Cash + Other Bank Balances), FY17-FY18 inputs SYMPHONY-AR-FY18.pdf:cashflow:Interest Income:FY18, SYMPHONY-AR-FY18.pdf:balance_sheet:Cash Equivalents:FY18, SYMPHONY-AR-FY18.pdf:balance_sheet:Other Bank Balances:FY18, SYMPHONY-AR-FY18.pdf:balance_sheet:Cash Equivalents:FY17, SYMPHONY-AR-FY18.pdf:balance_sheet:Other Bank Balances:FY17 (grade A) |

## Line by line — why each number moved

_Every question a competent analyst must ask of each statement line. **31%** of the applicable questions could be answered from the sources read as-of 2018-12-31; the rest are printed unanswered with the exact filing row that would close them, because a question dropped is a question that looks answered._

### Revenue — where the money actually comes from

_Every other line depends on this one, and it is the easiest to inflate: revenue can be booked gross instead of net, recognised early, routed through a related party, or bought outright. Growth with no stated cause is the single most common way a promoter story survives contact with a spreadsheet._

**Answered: 2 of 7** (29%)

- **At what rate did revenue actually compound, and over what window?**
  → Revenue compounded at 17.7% across FY12-FY18 — fast enough that a 5x in 5-8 years does not require a re-rating. `[fact:derived:revenue_cagr]`
- **Did receivables grow faster than revenue? Sales that turn into a receivable instead of cash are the classic signature of channel-stuffing and of revenue booked to hit a number.**
  → Receivable days moved +3.2 days year on year — essentially unchanged — sales are converting to cash at the same rate they did last year. `[fact:derived:receivable_days_delta]`
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
  → The material cost ratio moved -22.3pp across FY12-FY18 against -13.9pp for other expenses.
 — the material ratio FELL materially, so any margin compression came from somewhere other than feedstock. `[fact:derived:material_cost_ratio_delta]`
- **What does the workforce cost as a share of revenue, and is that share rising? A processor whose employee ratio climbs while tonnage is flat is losing operating leverage.**
  → Employee benefits are 9.1% of revenue, having moved 0.1% across FY12-FY18 — a normal manufacturing cost base, where scale rather than headcount drives the margin. `[fact:derived:employee_cost_ratio]`
- **Did the operating margin expand or compress across the window?** — ⚠️ **unanswered** (high)
  → the sources read do not disclose: pnl:Operating Profit FY12, pnl:Operating Profit FY18
- **Did costs compound faster than revenue? That is margin compression, stated causally.** — ⚠️ **unanswered** (medium)
  → the sources read do not disclose: pnl:Expenses FY12, pnl:Expenses FY18
- **If the margin expanded, was it price, mix, or scale? Only scale is durable at a commodity.** — ⚠️ **unanswered** (medium)
  → no extractor reads this yet — it requires the primary-source rows named below
     - needs: segment-wise revenue and result (Ind AS 108) to separate mix from price
     - needs: capacity and utilisation, to attribute the balance to operating leverage

### Other income — whether the profit is from the business

_Other income is where a weak operating year gets rescued. It is also where a promoter parks treasury gains, forex swings and one-off asset sales without ever labelling them non-recurring._

**Answered: 1 of 2** (50%)

- **How much of pre-tax profit is other income rather than the business?**
  → Other income is 20.4% of pre-tax profit — material enough to be understood, not large enough to be the story. `[fact:derived:other_income_share]`
- **WHAT is the other income — interest on real cash, a forex gain, a government incentive, or a one-off asset sale? Each has a completely different persistence.** — ⚠️ **unanswered** (high)
  → no extractor reads this yet — it requires the primary-source rows named below
     - needs: other-income breakup note (interest / dividend / forex / profit on sale of assets / other)
     - needs: prior-year comparative for the same note, to see which components recur

### Debt — not whether it rose, but what it bought

_Owner directive: rising debt is not a finding. Debt that funded capacity which then earned above its cost is good capital allocation; debt that funded dividends, working-capital leakage or interest on earlier debt is the beginning of a balance-sheet accident. The cash-flow identity distinguishes them deterministically, so there is no excuse for reporting the level and stopping._

**Answered: 1 of 8** (12%)

- **Did operations pay for the investment programme, or did someone else? A self-funded compounder is the entire premise of this firm; a company whose growth needs external capital every cycle is a different instrument with a different risk.**
  → Operating cash covered 1.57x of the investment programme across FY12-FY18 — self-funded: operations paid for growth with cash left over. `[fact:derived:self_funding_ratio]`
- **Did borrowings rise or fall across the window, and by how much?** — ⚠️ **unanswered** (high)
  → the sources read do not disclose: balance_sheet:Borrowings FY12, balance_sheet:Borrowings FY18
- **What share of the investment programme did debt pay for? This is the direct answer to "why is the debt increasing" — it rose to buy assets, or it rose for something else.** — ⚠️ **unanswered** (high)
  → no derivation for 'debt_funded_investment_share' exists in the pipeline yet, so this question was never put to the sources — a gap in the firm's extraction, not in the filing
- **What is the implied cost of debt, and is it consistent with the company's standing?** — ⚠️ **unanswered** (medium)
  → the sources read do not disclose: balance_sheet:Borrowings FY18, balance_sheet:Borrowings FY17
     - needs: borrowings note — the interest rate stated per facility, which is the disclosed rate rather than an implied one
- **Can operating profit service the interest?** — ⚠️ **unanswered** (high)
  → the sources read do not disclose: pnl:Operating Profit FY18
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
  → Net investing outflow across FY12-FY18 was ₹349 crore. `[fact:derived:investing_outflow_cum]`
- **What did the LAST cycle of capital actually earn? Average ROIC is a legacy number; the incremental figure is the one that says whether the next rupee should be deployed here.** — ⚠️ **unanswered** (high)
  → the sources read do not disclose: a 4+ year run of Operating Profit, Depreciation, Tax %, Borrowings, Equity Capital and Reserves is required for a rolling 3-year incremental ROIC
- **Did per-share value compound with the company, or was the growth bought with equity? The firm's question is a 5-10x PER SHARE; aggregate profit growth flatters a serial issuer.** — ⚠️ **unanswered** (high)
  → the sources read do not disclose: equity share capital moved 6.9957 -> 13.9914 (2.00x) across FY12-FY18, so the share base behind EPS is not comparable; whether that is a bonus/split (cosmetic for holders) or an issuance (real dilution) is a corporate-action disclosure the EPS series cannot answer
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
  → Receivable days stand at 28.1 days. `[fact:derived:receivable_days]`
- **Is inventory building faster than sales, and is any of it obsolete?**
  → Inventory days stand at 75.4 days. `[fact:derived:inventory_days]`
- **Is the company funding itself by paying suppliers late? A stretching payable cycle is a liquidity signal that arrives before any ratio breaks.**
  → Payable days stand at 55.3 days — ordinary trade credit for a chemical processor. `[fact:derived:payable_days]`
- **Net of all three, how many days of cash does the operating cycle tie up — and does the company fund its own working capital or does someone else?**
  → The cash conversion cycle ties up 48.2 days — positive but short — growth is broadly self-financing at this level of working capital. `[fact:derived:cash_conversion_cycle]`

### Cash — whether the balance is real

_The sharpest single test in the forensic library: cash that exists earns interest at a rate you can compute, and cash that does not exist earns nothing. A company holding a large balance while paying high interest on debt is either badly run or not holding the balance it reports._

**Answered: 1 of 3** (33%)

- **Does the reported cash balance earn a plausible rate of interest?**
  → The reported cash and bank balances yielded 13.4% on the average balance — above term-deposit rates, so the income is not coming from these balances alone and the composition needs reading. `[fact:derived:cash_yield_latest]`
- **Is the company holding cash while paying materially more to borrow?** — ⚠️ **unanswered** (high)
  → the sources read do not disclose: balance_sheet:Borrowings FY18
     - needs: borrowings note with the interest rate per tranche
- **Is the cash actually available? Margin money, unpaid-dividend accounts and lien-marked deposits are reported inside cash and cannot be spent.** — ⚠️ **unanswered** (medium)
  → no extractor reads this yet — it requires the primary-source rows named below
     - needs: cash-and-bank note — restricted balances, margin money, deposits under lien

### Tax — the cheapest cross-check on reported profit

_Tax is paid to a party with no interest in the share price. A profit that is reported but not taxed has to be explained by a disclosed incentive; if there is no such incentive, the profit is the thing in doubt._

**Answered: 0 of 2** (0%)

- **What is the effective tax rate, and how far is it from the statutory rate?** — ⚠️ **unanswered** (high)
  → the sources read do not disclose: pnl:Tax % FY18
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
25. borrowings note with the interest rate per tranche
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

**Notes the parser could not locate: [40, 41, 42, 43]** — numbered by the company and absent from our enumeration, so the coverage figure above is a share of the notes we found, not of the notes that exist. This is a gap in our reading, not in the company's disclosure.

### Verified-clean checklist

_Every check that ran, passes included — a clean verdict with an invisible process is worth nothing._

| check | outcome | detail | facts |
|---|---|---|---|
| `cumulative_cfo_pat` | ✅ pass | ΣCFO/ΣPAT 0.79 vs floor 0.70 (Σ CFO / Σ PAT, FY12-FY18) (grade A) | `[fact:SYMPHONY-AR-FY13.pdf:cashflow:Cash from Operating Activity:FY12]`, `[fact:SYMPHONY-AR-FY14.pdf:cashflow:Cash from Operating Activity:FY13]`, `[fact:SYMPHONY-AR-FY15.pdf:cashflow:Cash from Operating Activity:FY14]`, `[fact:SYMPHONY-AR-FY16.pdf:cashflow:Cash from Operating Activity:FY15]`, `[fact:SYMPHONY-AR-FY18.pdf:cashflow:Cash from Operating Activity:FY17]`, `[fact:SYMPHONY-AR-FY18.pdf:cashflow:Cash from Operating Activity:FY18]`, `[fact:SYMPHONY-AR-FY13.pdf:pnl:Net Profit:FY12]`, `[fact:SYMPHONY-AR-FY14.pdf:pnl:Net Profit:FY13]`, `[fact:SYMPHONY-AR-FY15.pdf:pnl:Net Profit:FY14]`, `[fact:SYMPHONY-AR-FY16.pdf:pnl:Net Profit:FY15]`, `[fact:SYMPHONY-AR-FY18.pdf:pnl:Net Profit:FY17]`, `[fact:SYMPHONY-AR-FY18.pdf:pnl:Net Profit:FY18]` |
| `cfo_pat` | 🚩 flag | CFO/PAT 0.55 vs floor 0.70 (CFO FY18 / PAT FY18) (grade A) | `[fact:SYMPHONY-AR-FY18.pdf:cashflow:Cash from Operating Activity:FY18]`, `[fact:SYMPHONY-AR-FY18.pdf:pnl:Net Profit:FY18]` |
| `cash_interest_inconsistent` | ✅ pass | implied yield on cash and bank balances 13.41% vs floor 2.60% (|Interest Income FY18| / average (Cash + Other Bank Balances), FY17-FY18) (grade A) | `[fact:SYMPHONY-AR-FY18.pdf:cashflow:Interest Income:FY18]`, `[fact:SYMPHONY-AR-FY18.pdf:balance_sheet:Cash Equivalents:FY18]`, `[fact:SYMPHONY-AR-FY18.pdf:balance_sheet:Other Bank Balances:FY18]`, `[fact:SYMPHONY-AR-FY18.pdf:balance_sheet:Cash Equivalents:FY17]`, `[fact:SYMPHONY-AR-FY18.pdf:balance_sheet:Other Bank Balances:FY17]` |
| `cash_debt_paradox` | ⚠️ unavailable | this check could not be run on the sources read as-of this run: balance_sheet:Borrowings FY18, balance_sheet:Borrowings FY18 | — |
| `disclosure_gap` | ✅ pass | every mandated Schedule III / forensic section located in the filing | — |
| `other_income_heavy` | ✅ pass | other income 20.4% of PBT vs limit 25% (pnl:Other Income FY18 / pnl:Profit before tax FY18) (grade A) | `[fact:SYMPHONY-AR-FY18.pdf:pnl:Other Income:FY18]`, `[fact:SYMPHONY-AR-FY18.pdf:pnl:Profit before tax:FY18]` |
| `promoter_lending` | ⚠️ unavailable | inputs not disclosed in the sources read as-of this run: loans and advances to promoters/KMP (Schedule III row) | — |
| `receivables_divergent` | ✅ pass | receivables +17.6% vs revenue +4.4%, gap +13.2% vs limit 25% (AR) (grade A) | `[fact:SYMPHONY-AR-FY18.pdf:balance_sheet:Trade Receivables:FY18]`, `[fact:SYMPHONY-AR-FY18.pdf:balance_sheet:Trade Receivables:FY17]`, `[fact:SYMPHONY-AR-FY18.pdf:pnl:Sales:FY18]`, `[fact:SYMPHONY-AR-FY18.pdf:pnl:Sales:FY17]` |
| `inventory_divergent` | ✅ pass | inventory +2.9% vs revenue +4.4%, gap -1.5% vs limit 30% (AR) (grade A) | `[fact:SYMPHONY-AR-FY18.pdf:balance_sheet:Inventories:FY18]`, `[fact:SYMPHONY-AR-FY18.pdf:balance_sheet:Inventories:FY17]`, `[fact:SYMPHONY-AR-FY18.pdf:pnl:Sales:FY18]`, `[fact:SYMPHONY-AR-FY18.pdf:pnl:Sales:FY17]` |
| `high_accruals` | 🚩 flag | accruals +0.126 vs limit ±0.10 ((PAT - CFO)(FY18) / avg Total Assets) (grade A) | `[fact:SYMPHONY-AR-FY18.pdf:pnl:Net Profit:FY18]`, `[fact:SYMPHONY-AR-FY18.pdf:cashflow:Cash from Operating Activity:FY18]`, `[fact:SYMPHONY-AR-FY18.pdf:balance_sheet:Total Assets:FY18]`, `[fact:SYMPHONY-AR-FY18.pdf:balance_sheet:Total Assets:FY17]` |

REVIEW, and honestly so: two single-year flags with a plausible classification explanation on one side, and on the other a six-year cumulative conversion of 0.79 [fact:derived:cum_cfo_pat], passing divergence checks, quiet working capital, and a cross-filing control that surfaced re-presentations rather than misreads. No veto: the deterministic screen's verdict stands, and nothing in the narrative evidence argues it should be worse.

### Restatement log — what later filings changed

_Every figure a later filing revised, from the same deterministic overlap classifier that quarantines misreads. A restatement is a fact to explain, not an accusation — an accounting-standard transition legitimately rewrites a year — but a company revising its history is something a reader sees here in one place, or never._

| metric | period | earlier filing said | later filing says | revised by |
|---|---|---|---|---|
| `balance_sheet:Cash Equivalents` | FY14 | 5.55 | 4.27 | `SYMPHONY-AR-FY15.pdf` |
| `balance_sheet:Cash Equivalents` | FY15 | 5.36 | 5.31 | `SYMPHONY-AR-FY16.pdf` |
| `balance_sheet:Cash Equivalents` | FY17 | 43.23 | 43.40 | `SYMPHONY-AR-FY18.pdf` |
| `balance_sheet:Current Borrowings` | FY17 | 19.29 | 19.35 | `SYMPHONY-AR-FY18.pdf` |
| `balance_sheet:Fixed Assets` | FY15 | 90.17 | 68.02 | `SYMPHONY-AR-FY16.pdf` |
| `balance_sheet:Fixed Assets` | FY17 | 71.41 | 69.84 | `SYMPHONY-AR-FY18.pdf` |
| `balance_sheet:Reserves` | FY15 | 321.37 | 299.22 | `SYMPHONY-AR-FY16.pdf` |
| `balance_sheet:Reserves` | FY17 | 445.00 | 451.06 | `SYMPHONY-AR-FY18.pdf` |
| `balance_sheet:Total Assets` | FY15 | 444.87 | 422.72 | `SYMPHONY-AR-FY16.pdf` |
| `balance_sheet:Total Assets` | FY17 | 598.79 | 605.20 | `SYMPHONY-AR-FY18.pdf` |
| `balance_sheet:Trade Payables` | FY15 | 40.05 | 39.88 | `SYMPHONY-AR-FY16.pdf` |
| `balance_sheet:Trade Payables` | FY16 | 49.08 | 49.58 | `SYMPHONY-AR-FY17.pdf` |
| `balance_sheet:Trade Payables` | FY17 | 60.95 | 54.78 | `SYMPHONY-AR-FY18.pdf` |
| `balance_sheet:Trade Payables (Other)` | FY16 | 49.08 | 49.58 | `SYMPHONY-AR-FY17.pdf` |
| `cashflow:Cash from Financing Activity` | FY13 | -29.89 | -29.59 | `SYMPHONY-AR-FY14.pdf` |
| `cashflow:Cash from Financing Activity` | FY15 | -65.63 | -65.74 | `SYMPHONY-AR-FY16.pdf` |
| `cashflow:Cash from Financing Activity` | FY17 | -4.71 | -4.65 | `SYMPHONY-AR-FY18.pdf` |
| `cashflow:Cash from Investing Activity` | FY13 | -33.59 | -33.61 | `SYMPHONY-AR-FY14.pdf` |
| `cashflow:Cash from Investing Activity` | FY14 | -59.55 | -60.13 | `SYMPHONY-AR-FY15.pdf` |
| `cashflow:Cash from Investing Activity` | FY17 | -65.17 | -65.10 | `SYMPHONY-AR-FY18.pdf` |
| `cashflow:Cash from Operating Activity` | FY13 | 67.07 | 66.78 | `SYMPHONY-AR-FY14.pdf` |
| `cashflow:Cash from Operating Activity` | FY15 | 118.30 | 103.59 | `SYMPHONY-AR-FY16.pdf` |
| `cashflow:Cash from Operating Activity` | FY17 | 94.89 | 94.65 | `SYMPHONY-AR-FY18.pdf` |
| `pnl:Changes in Inventories` | FY15 | -11.15 | -13.09 | `SYMPHONY-AR-FY16.pdf` |
| `pnl:Cost of Materials Consumed` | FY15 | 52.88 | 54.95 | `SYMPHONY-AR-FY16.pdf` |
| `pnl:Cost of Materials Consumed` | FY17 | 91.27 | 91.72 | `SYMPHONY-AR-FY18.pdf` |
| `pnl:Depreciation` | FY17 | 7.05 | 6.88 | `SYMPHONY-AR-FY18.pdf` |
| `pnl:EPS in Rs` | FY17 | 23.67 | 23.77 | `SYMPHONY-AR-FY18.pdf` |
| `pnl:Employee Benefits` | FY13 | 32.64 | 34.98 | `SYMPHONY-AR-FY14.pdf` |
| `pnl:Employee Benefits` | FY15 | 44.90 | 46.20 | `SYMPHONY-AR-FY16.pdf` |
| `pnl:Employee Benefits` | FY17 | 68.71 | 68.27 | `SYMPHONY-AR-FY18.pdf` |
| `pnl:Net Profit` | FY17 | 165.60 | 166.28 | `SYMPHONY-AR-FY18.pdf` |
| `pnl:Other Expenses` | FY13 | 98.95 | 96.92 | `SYMPHONY-AR-FY14.pdf` |
| `pnl:Other Expenses` | FY14 | 136.89 | 138.67 | `SYMPHONY-AR-FY15.pdf` |
| `pnl:Other Expenses` | FY17 | 92.85 | 91.84 | `SYMPHONY-AR-FY18.pdf` |
| `pnl:Other Income` | FY13 | 16.97 | 16.71 | `SYMPHONY-AR-FY14.pdf` |
| `pnl:Other Income` | FY14 | 13.79 | 15.58 | `SYMPHONY-AR-FY15.pdf` |
| `pnl:Other Income` | FY15 | 31.99 | 33.69 | `SYMPHONY-AR-FY16.pdf` |
| `pnl:Other Income` | FY17 | 43.21 | 43.27 | `SYMPHONY-AR-FY18.pdf` |
| `pnl:Profit before tax` | FY15 | 159.56 | 161.27 | `SYMPHONY-AR-FY16.pdf` |
| `pnl:Profit before tax` | FY17 | 233.71 | 234.95 | `SYMPHONY-AR-FY18.pdf` |
| `pnl:Purchases of Stock-in-Trade` | FY15 | 196.97 | 197.66 | `SYMPHONY-AR-FY16.pdf` |
| `pnl:Sales` | FY13 | 377.76 | 378.02 | `SYMPHONY-AR-FY14.pdf` |
| `pnl:Sales` | FY15 | 578.89 | 525.87 | `SYMPHONY-AR-FY16.pdf` |
| `pnl:Sales` | FY17 | 768.03 | 764.75 | `SYMPHONY-AR-FY18.pdf` |
| `pnl:Total Expenses` | FY14 | 410.47 | 412.25 | `SYMPHONY-AR-FY15.pdf` |
| `pnl:Total Expenses` | FY15 | 451.32 | 398.30 | `SYMPHONY-AR-FY16.pdf` |
| `pnl:Total Expenses` | FY17 | 577.52 | 573.08 | `SYMPHONY-AR-FY18.pdf` |
| `pnl:Total Tax` | FY17 | 68.12 | 68.66 | `SYMPHONY-AR-FY18.pdf` |

## Management and governance

No management or governance assessment is made in this report: `management_analyst`, `transcript_analyst` and `ownership_flows_analyst` did not run. Promoter-pledge, promise-vs-delivery and board-interlock findings are therefore absent rather than clean.

## Valuation

No valuation claim is made in this report. The valuation tier (reverse DCF, probability-weighted scenarios, sensitivity) is Phase 4 of the build; the feasibility gate below is a *self-funding* test, not a price judgment.

## Thesis

Symphony designs and sells air coolers under its own brand and has vendors build them: the money flow is brand price-premium in, vendor invoices and dealer margins out, with the residual compounding at 25.1% [fact:derived:pat_cagr] while revenue compounded 17.7% [fact:derived:revenue_cagr]. The balance sheet's job here is to hold the treasury, not the factories. The honest caveats are that a fifth of pre-tax profit is treasury income at 20.4% [fact:derived:other_income_share] of PBT, and that the questions a brand thesis turns on — volume versus price, channel concentration, export share — are asked and unanswered in this run's sources.

## Anti-thesis (the strongest case against)

**business_analyst (disconfirming search):** Looked for signs the growth was bought rather than earned: receivable and inventory growth both trail revenue growth (the stock-flow checks pass), the programme is self-funded at 1.57 [fact:derived:self_funding_ratio], and no borrowing base appears. What I could NOT disconfirm is concentration risk — customer, channel or vendor concentration is simply not disclosed in the rows read here, so its absence from this narrative is a gap, not evidence of diversification.

**financial_statement_analyst (disconfirming search):** Tried to break the 'cash is fine' reading: the sharpest attack is the latest year at 0.55 [fact:derived:cfo_pat_latest] with accruals at 0.126 [fact:derived:accrual_ratio_latest]. Against it stand the cumulative 0.79 [fact:derived:cum_cfo_pat], receivables moving 3.2 [fact:derived:receivable_days_delta] days, and inventory growth trailing revenue growth in the stock-flow checks — the fraud shapes that make a conversion gap sinister are absent. What survives is a real, unresolved classification question, named above.

**forensic_accountant (disconfirming search):** Hunted for the fraud shape directly: profit rising with cash flat (absent — cumulative 0.79 [fact:derived:cum_cfo_pat]), receivables outrunning sales (absent — the divergence check passes with revenue growing faster), inventory building against demand (absent), a stub period inflating a growth rate (excluded by construction). The two fired flags have a benign arithmetic explanation that the unread interest-received row could confirm or destroy; until it is read, REVIEW is the correct posture and PASS would be overclaiming.

**Checks that fired:** `cfo_pat` — CFO/PAT 0.55 vs floor 0.70 (CFO FY18 / PAT FY18) (grade A); `high_accruals` — accruals +0.126 vs limit ±0.10 ((PAT - CFO)(FY18) / avg Total Assets) (grade A)

**Not verifiable from the sources read:** 2 of 10 applicable checks could not be evaluated, so the case against this company includes everything we could not look at.

## Falsifiability

### Kill criteria — what would break this thesis

| criterion | metric | test | resolve by | load-bearing |
|---|---|---|---|---|
| Cumulative CFO/PAT stays at or above 0.71 (it is 0.79 today). If a decade of reported profit stops converting to cash, the thesis is dead regardless of growth. | `cum_cfo_pat` | `>= 0.7092` | 2019-10-27 | **yes** |
| Single-year CFO/PAT stays at or above 0.70 in the next annual report (it is 0.55 today). | `cfo_pat_latest` | `>= 0.7` | 2019-10-27 | no |
| The accrual ratio stays at or below 0.10 (it is +0.126 today); above it, reported earnings are increasingly non-cash. | `accrual_ratio_latest` | `<= 0.1` | 2019-10-27 | no |

### Rehabilitation criteria — what would reverse this verdict

| criterion | metric | test | resolve by | load-bearing |
|---|---|---|---|---|
| `cfo_pat` clears: cfo_pat_latest >= 0.7 (currently 0.55), evidenced in the next annual report. Until then this remains the reason the verdict is withheld. | `cfo_pat_latest` | `>= 0.7` | 2019-10-27 | **yes** |
| `high_accruals` clears: accrual_ratio_latest <= 0.1 (currently 0.13), evidenced in the next annual report. Until then this remains the reason the verdict is withheld. | `accrual_ratio_latest` | `<= 0.1` | 2019-10-27 | **yes** |
| The company discloses the inputs for the checks that could not be run — `cash_debt_paradox`, `promoter_lending` — in a filing readable as text. For a listed company these are public by law; the gap, not our patience, is what holds the verdict. | `checks_unavailable` | `<= 0.0` | 2019-10-27 | **yes** |

## Open questions

- business_analyst: What share of revenue is domestic versus export, and does the brand carry the same price premium outside India? The segment note would answer this; it is not read in this run.
- business_analyst: Who are the contract manufacturers, and is any of them related to the promoter group? The related-party note discloses remuneration channels only in the sources read here.
- business_analyst: Volume versus realisation: how many coolers were sold? The production/sales quantity table is not in the read fact set, so price-versus-volume growth cannot be split.
- business_analyst: Share capital doubled during the window — a bonus issue or an issuance? The corporate-action disclosure would settle whether per-share compounding tracked aggregate compounding.
- financial_statement_analyst: What does the cash flow's own interest-received line show? That single row would settle how much of the conversion shortfall is investing-classified treasury income.
- financial_statement_analyst: Was the share-capital doubling a bonus issue? The corporate-action disclosure or the reserves note would answer in one line.
- financial_statement_analyst: Return on capital cannot be computed from this fact set — the operating-profit and tax rows are not in the reading vocabulary — so capital efficiency rests on the cash-flow evidence alone here.
- forensic_accountant: The cash-reality test (interest earned versus cash held) could not be run — the interest-income row is not in the reading vocabulary. It is the sharpest remaining test and it is the firm's gap, not the company's.
- forensic_accountant: The related-party note beyond remuneration is unread in this run; promoter lending cannot be cleared, only not-flagged.
- forensic_accountant: Contingent liabilities and the guarantees note are enumerated but not substantively dispositioned in this run.
- cash_debt_paradox: this check could not be run on the sources read as-of this run: balance_sheet:Borrowings FY18, balance_sheet:Borrowings FY18
- promoter_lending: inputs not disclosed in the sources read as-of this run: loans and advances to promoters/KMP (Schedule III row)

## Not available from primary sources

_Reported as unavailable rather than estimated._

- cash_debt_paradox: this check could not be run on the sources read as-of this run: balance_sheet:Borrowings FY18, balance_sheet:Borrowings FY18
- promoter_lending: inputs not disclosed in the sources read as-of this run: loans and advances to promoters/KMP (Schedule III row)

## Replication

_How a third party reproduces these findings._

1. Re-run `python -m firm deep-dive --ticker SYMPHONY --as-of 2018-12-31`; the run id is a content hash of the inputs, so the same facts reproduce this report byte-for-byte.
2. Every figure in §4 lists its formula and input fact ids; each fact resolves to (doc_id, page/line, published_at, grade) in the fact store.
3. `cfo_pat`: CFO/PAT 0.55 vs floor 0.70 (CFO FY18 / PAT FY18) (grade A) — recompute from fact ids SYMPHONY-AR-FY18.pdf:cashflow:Cash from Operating Activity:FY18, SYMPHONY-AR-FY18.pdf:pnl:Net Profit:FY18.
4. `high_accruals`: accruals +0.126 vs limit ±0.10 ((PAT - CFO)(FY18) / avg Total Assets) (grade A) — recompute from fact ids SYMPHONY-AR-FY18.pdf:pnl:Net Profit:FY18, SYMPHONY-AR-FY18.pdf:cashflow:Cash from Operating Activity:FY18, SYMPHONY-AR-FY18.pdf:balance_sheet:Total Assets:FY18, SYMPHONY-AR-FY18.pdf:balance_sheet:Total Assets:FY17.
