<!-- agent: financial_statement_analyst@1.0.0 · answer with ONE JSON object matching the schema at the end · save it as financial_statement_analyst.json in this directory -->

# SYSTEM

# House Analytical Standards

Every agent inherits these. They are enforced by validators where possible (SPEC §9) and by review
where not.

1. **Numbers over adjectives.** "Margins improved" is banned. Required form: "EBITDA margin went
   14.2% → 18.6% over FY22–FY25, driven ~60% by operating leverage and ~40% by mix." A `hedge_detector`
   flags vague quantifiers ("strong growth", "healthy margins", "significant opportunity") and forces a
   number.
2. **State the base rate first.** Before claiming a company grows 30% for 7 years, state how many Indian
   companies in this sector have ever done that.
3. **Say "I don't know."** An explicit `unknown` with a note on what data would resolve it beats a
   confident guess. Every output has an `open_questions` array — an empty array is suspicious.
4. **Separate observation / inference / speculation.** Three distinct schema fields. Never blend them in
   prose.
5. **Confidence is numeric** and justified by evidence count and grade, not vibes.
6. **Disconfirming search is mandatory.** Every agent actively looks for evidence against its own
   emerging conclusion and records what it found or failed to find.
7. **A management claim is data about management, not data about the business.** Tag it as grade C and
   attribute it.
8. **Cite the grade.** When a thesis pillar rests on grade C or D evidence, say so in the thesis body,
   not a footnote.

Numbers rule (Law 1): agents never compute or invent a figure. Every number an agent uses was produced
by `core/compute/` and arrives with a `fact_id`. Agents reason about numbers; they do not make them.

---

# Epistemics — how to express uncertainty

- **Confidence is a number in [0,1]**, and it must be defensible from evidence count × grade, not tone.
  Two grade-A facts beat ten grade-D mentions.
- **Three states, never two:** `supported` (evidence for), `refuted` (evidence against), `unknown` (no
  sufficient evidence). "Unknown" is a first-class answer and often the correct one.
- **Distinguish observation / inference / speculation** and never let a downstream agent read a
  speculation as an observation. The schema forces separate fields; honour them.
- **Every load-bearing claim is falsifiable.** If no future filing could prove it wrong, it is not a
  claim, it is a vibe — demote it.
- **Grade every input** (A audited / B exchange / C company-claim / D media). A thesis pillar may not
  rest on grade D alone.
- **Calibrate.** Predictions carry a probability; those probabilities are scored by Brier later
  (SPEC §7). Systematic over/under-confidence is a defect the loop will surface — write probabilities
  you would bet on.

---

# Forbidden — anti-patterns that fail a run

- **Inventing or computing a number.** Any figure not carrying a `fact_id` from `core/compute/` is a
  hard fail (Law 1).
- **Vague quantifiers.** "Strong", "healthy", "significant", "robust", "meaningful" without a number.
- **Unsourced claims.** Every factual assertion needs a citation token → `fact_id` (Law 2).
- **Look-ahead.** Referencing anything with `published_at > as_of`. The query layer prevents this; an
  agent that works around it fails the run (Law 3).
- **Free-prose hand-offs.** Agents read each other's JSON, never each other's prose (Law 4).
- **Reading raw HTML/PDF.** Agents read gold fact tables only (Law 7).
- **Emitting "buy" / a target price as advice.** Output is a thesis with assumptions, probabilities, and
  kill criteria — never a recommendation to transact (SPEC §1).
- **Empty `open_questions` / no disconfirming search.** Treated as a quality failure, not a strength.
- **Treating a management claim as fact.** It is grade-C data about management until an audited filing
  confirms it.
- **Building a thesis pillar on grade-D evidence alone.**

# USER

# financial_statement_analyst

**Mandate.** Full 3-statement work across 10 years, with emphasis on **incremental** returns and cash
conversion — the two things that separate a compounder from an accounting story.

**Inputs.** `financials` (10y), `segments`, `capex_announcements`. All ratios come from
`core/compute/` (Law 1) — this agent interprets, never computes.

**Method.**
1. Revenue bridge (volume / price / mix / acquisition). Margin walk.
2. Extended DuPont (`compute.dupont`). ROIC vs WACC and, more importantly, **incremental ROIC**
   = ΔNOPAT/ΔInvested over rolling 3-year windows (`compute.roic`).
3. Working-capital cycle and its trend. Capex intensity: maintenance vs growth capex separated
   (estimate it, show the method).
4. Cash conversion: CFO/EBITDA and FCF/PAT across a full cycle. Debt schedule, covenants, refi walls.

**Output.** `FinancialStatementOutput` — `incremental_roic`, `cfo_to_ebitda`, `fcf_to_pat`,
`working_capital_days`.

**Definition of Done.** Every quoted ratio passes the arithmetic validator; incremental ROIC is
reported even when the average ROIC looks fine.

**Known failure modes.** Reporting average ROIC while incremental ROIC is collapsing; ignoring the
refinancing wall.

**Forbidden.** Producing any number the compute layer didn't (Law 1); smoothing over a CFO/PAT gap.

## Computed facts (from core/compute — treat every number as authoritative; DO NOT alter or invent numbers, Law 1)
```json
{
  "ticker": "SYMPHONY",
  "as_of": "2018-12-31",
  "history": "FY12-FY18 (6y)",
  "business_models_detected": [
    "none matched \u2014 universal checks only"
  ],
  "computed_metrics": {
    "revenue_cagr": {
      "value": 0.17653586449706826,
      "formula": "(pnl:Sales FY18 / pnl:Sales FY12)^(1/5.7496) - 1",
      "fact_ids": [
        "SYMPHONY-AR-FY13.pdf:pnl:Sales:FY12",
        "SYMPHONY-AR-FY18.pdf:pnl:Sales:FY18"
      ],
      "cite_as": "[fact:derived:revenue_cagr]",
      "grade": "A"
    },
    "pat_cagr": {
      "value": 0.25112966369606293,
      "formula": "(pnl:Net Profit FY18 / pnl:Net Profit FY12)^(1/5.7496) - 1",
      "fact_ids": [
        "SYMPHONY-AR-FY13.pdf:pnl:Net Profit:FY12",
        "SYMPHONY-AR-FY18.pdf:pnl:Net Profit:FY18"
      ],
      "cite_as": "[fact:derived:pat_cagr]",
      "grade": "A"
    },
    "cum_cfo_pat": {
      "value": 0.7880239564119585,
      "formula": "\u03a3 CFO / \u03a3 PAT, FY12-FY18",
      "fact_ids": [
        "SYMPHONY-AR-FY13.pdf:cashflow:Cash from Operating Activity:FY12",
        "SYMPHONY-AR-FY14.pdf:cashflow:Cash from Operating Activity:FY13",
        "SYMPHONY-AR-FY15.pdf:cashflow:Cash from Operating Activity:FY14",
        "SYMPHONY-AR-FY16.pdf:cashflow:Cash from Operating Activity:FY15",
        "SYMPHONY-AR-FY18.pdf:cashflow:Cash from Operating Activity:FY17",
        "SYMPHONY-AR-FY18.pdf:cashflow:Cash from Operating Activity:FY18",
        "SYMPHONY-AR-FY13.pdf:pnl:Net Profit:FY12",
        "SYMPHONY-AR-FY14.pdf:pnl:Net Profit:FY13",
        "SYMPHONY-AR-FY15.pdf:pnl:Net Profit:FY14",
        "SYMPHONY-AR-FY16.pdf:pnl:Net Profit:FY15",
        "SYMPHONY-AR-FY18.pdf:pnl:Net Profit:FY17",
        "SYMPHONY-AR-FY18.pdf:pnl:Net Profit:FY18"
      ],
      "cite_as": "[fact:derived:cum_cfo_pat]",
      "grade": "A"
    },
    "cfo_pat_latest": {
      "value": 0.5549774057629976,
      "formula": "CFO FY18 / PAT FY18",
      "fact_ids": [
        "SYMPHONY-AR-FY18.pdf:cashflow:Cash from Operating Activity:FY18",
        "SYMPHONY-AR-FY18.pdf:pnl:Net Profit:FY18"
      ],
      "cite_as": "[fact:derived:cfo_pat_latest]",
      "grade": "A"
    },
    "accrual_ratio_latest": {
      "value": 0.12585034538138454,
      "formula": "(PAT - CFO)(FY18) / avg Total Assets",
      "fact_ids": [
        "SYMPHONY-AR-FY18.pdf:pnl:Net Profit:FY18",
        "SYMPHONY-AR-FY18.pdf:cashflow:Cash from Operating Activity:FY18",
        "SYMPHONY-AR-FY18.pdf:balance_sheet:Total Assets:FY18",
        "SYMPHONY-AR-FY18.pdf:balance_sheet:Total Assets:FY17"
      ],
      "cite_as": "[fact:derived:accrual_ratio_latest]",
      "grade": "A"
    },
    "other_income_share": {
      "value": 0.20444487411250362,
      "formula": "pnl:Other Income FY18 / pnl:Profit before tax FY18",
      "fact_ids": [
        "SYMPHONY-AR-FY18.pdf:pnl:Other Income:FY18",
        "SYMPHONY-AR-FY18.pdf:pnl:Profit before tax:FY18"
      ],
      "cite_as": "[fact:derived:other_income_share]",
      "grade": "A"
    },
    "eps_cagr": {
      "value": 0.10901698375903468,
      "formula": "(pnl:EPS in Rs FY18 / pnl:EPS in Rs FY12)^(1/5.7496) - 1",
      "fact_ids": [
        "SYMPHONY-AR-FY13.pdf:pnl:EPS in Rs:FY12",
        "SYMPHONY-AR-FY18.pdf:pnl:EPS in Rs:FY18"
      ],
      "cite_as": "[fact:derived:eps_cagr]",
      "grade": "A"
    },
    "cfo_cum_window": {
      "value": 546.6337,
      "formula": "\u03a3 CFO, FY12-FY18",
      "fact_ids": [
        "SYMPHONY-AR-FY13.pdf:cashflow:Cash from Operating Activity:FY12",
        "SYMPHONY-AR-FY14.pdf:cashflow:Cash from Operating Activity:FY13",
        "SYMPHONY-AR-FY15.pdf:cashflow:Cash from Operating Activity:FY14",
        "SYMPHONY-AR-FY16.pdf:cashflow:Cash from Operating Activity:FY15",
        "SYMPHONY-AR-FY18.pdf:cashflow:Cash from Operating Activity:FY17",
        "SYMPHONY-AR-FY18.pdf:cashflow:Cash from Operating Activity:FY18"
      ],
      "cite_as": "[fact:derived:cfo_cum_window]",
      "grade": "A"
    },
    "investing_outflow_cum": {
      "value": 349.1472,
      "formula": "-\u03a3 CFI, FY12-FY18",
      "fact_ids": [
        "SYMPHONY-AR-FY13.pdf:cashflow:Cash from Investing Activity:FY12",
        "SYMPHONY-AR-FY14.pdf:cashflow:Cash from Investing Activity:FY13",
        "SYMPHONY-AR-FY15.pdf:cashflow:Cash from Investing Activity:FY14",
        "SYMPHONY-AR-FY18.pdf:cashflow:Cash from Investing Activity:FY17",
        "SYMPHONY-AR-FY18.pdf:cashflow:Cash from Investing Activity:FY18"
      ],
      "cite_as": "[fact:derived:investing_outflow_cum]",
      "grade": "A"
    },
    "self_funding_ratio": {
      "value": 1.5656253293739717,
      "formula": "\u03a3 CFO / -\u03a3 CFI, FY12-FY18 (>=1 means operations paid for the investment programme)",
      "fact_ids": [
        "SYMPHONY-AR-FY13.pdf:cashflow:Cash from Operating Activity:FY12",
        "SYMPHONY-AR-FY14.pdf:cashflow:Cash from Operating Activity:FY13",
        "SYMPHONY-AR-FY15.pdf:cashflow:Cash from Operating Activity:FY14",
        "SYMPHONY-AR-FY16.pdf:cashflow:Cash from Operating Activity:FY15",
        "SYMPHONY-AR-FY18.pdf:cashflow:Cash from Operating Activity:FY17",
        "SYMPHONY-AR-FY18.pdf:cashflow:Cash from Operating Activity:FY18",
        "SYMPHONY-AR-FY13.pdf:cashflow:Cash from Investing Activity:FY12",
        "SYMPHONY-AR-FY14.pdf:cashflow:Cash from Investing Activity:FY13",
        "SYMPHONY-AR-FY15.pdf:cashflow:Cash from Investing Activity:FY14",
        "SYMPHONY-AR-FY18.pdf:cashflow:Cash from Investing Activity:FY17",
        "SYMPHONY-AR-FY18.pdf:cashflow:Cash from Investing Activity:FY18"
      ],
      "cite_as": "[fact:derived:self_funding_ratio]",
      "grade": "A"
    },
    "receivable_days": {
      "value": 28.12393165337621,
      "formula": "balance_sheet:Trade Receivables FY18 / pnl:Sales FY18 x 365",
      "fact_ids": [
        "SYMPHONY-AR-FY18.pdf:balance_sheet:Trade Receivables:FY18",
        "SYMPHONY-AR-FY18.pdf:pnl:Sales:FY18"
      ],
      "cite_as": "[fact:derived:receivable_days]",
      "grade": "A"
    },
    "inventory_days": {
      "value": 75.3717356252545,
      "formula": "balance_sheet:Inventories FY18 / (Cost of Materials Consumed + Purchases of Stock-in-Trade + Changes in Inventories) FY18 x 365",
      "fact_ids": [
        "SYMPHONY-AR-FY18.pdf:balance_sheet:Inventories:FY18",
        "SYMPHONY-AR-FY18.pdf:pnl:Cost of Materials Consumed:FY18",
        "SYMPHONY-AR-FY18.pdf:pnl:Purchases of Stock-in-Trade:FY18",
        "SYMPHONY-AR-FY18.pdf:pnl:Changes in Inventories:FY18"
      ],
      "cite_as": "[fact:derived:inventory_days]",
      "grade": "A"
    },
    "payable_days": {
      "value": 55.26951812509944,
      "formula": "balance_sheet:Trade Payables FY18 / (Cost of Materials Consumed + Purchases of Stock-in-Trade + Changes in Inventories) FY18 x 365",
      "fact_ids": [
        "SYMPHONY-AR-FY18.pdf:balance_sheet:Trade Payables:FY18",
        "SYMPHONY-AR-FY18.pdf:pnl:Cost of Materials Consumed:FY18",
        "SYMPHONY-AR-FY18.pdf:pnl:Purchases of Stock-in-Trade:FY18",
        "SYMPHONY-AR-FY18.pdf:pnl:Changes in Inventories:FY18"
      ],
      "cite_as": "[fact:derived:payable_days]",
      "grade": "A"
    },
    "receivable_days_delta": {
      "value": 3.1580132680162443,
      "formula": "Receivable days FY18 - FY17 (positive = collection is slowing)",
      "fact_ids": [
        "SYMPHONY-AR-FY18.pdf:balance_sheet:Trade Receivables:FY18",
        "SYMPHONY-AR-FY18.pdf:pnl:Sales:FY18",
        "SYMPHONY-AR-FY18.pdf:balance_sheet:Trade Receivables:FY17",
        "SYMPHONY-AR-FY18.pdf:pnl:Sales:FY17"
      ],
      "cite_as": "[fact:derived:receivable_days_delta]",
      "grade": "A"
    },
    "cash_conversion_cycle": {
      "value": 48.22614915353128,
      "formula": "Receivable days + Inventory days - Payable days, FY18 (days of cash tied up)",
      "fact_ids": [
        "SYMPHONY-AR-FY18.pdf:balance_sheet:Trade Receivables:FY18",
        "SYMPHONY-AR-FY18.pdf:pnl:Sales:FY18",
        "SYMPHONY-AR-FY18.pdf:balance_sheet:Inventories:FY18",
        "SYMPHONY-AR-FY18.pdf:pnl:Cost of Materials Consumed:FY18",
        "SYMPHONY-AR-FY18.pdf:pnl:Purchases of Stock-in-Trade:FY18",
        "SYMPHONY-AR-FY18.pdf:pnl:Changes in Inventories:FY18",
        "SYMPHONY-AR-FY18.pdf:balance_sheet:Trade Payables:FY18",
        "SYMPHONY-AR-FY18.pdf:pnl:Cost of Materials Consumed:FY18",
        "SYMPHONY-AR-FY18.pdf:pnl:Purchases of Stock-in-Trade:FY18",
        "SYMPHONY-AR-FY18.pdf:pnl:Changes in Inventories:FY18"
      ],
      "cite_as": "[fact:derived:cash_conversion_cycle]",
      "grade": "A"
    },
    "material_cost_ratio": {
      "value": 0.11761762695982295,
      "formula": "Cost of Materials Consumed FY18 / pnl:Sales FY18",
      "fact_ids": [
        "SYMPHONY-AR-FY18.pdf:pnl:Cost of Materials Consumed:FY18",
        "SYMPHONY-AR-FY18.pdf:pnl:Sales:FY18"
      ],
      "cite_as": "[fact:derived:material_cost_ratio]",
      "grade": "A"
    },
    "material_cost_ratio_delta": {
      "value": -0.22255398995763145,
      "formula": "Cost of Materials Consumed/Sales FY18 - Cost of Materials Consumed/Sales FY12",
      "fact_ids": [
        "SYMPHONY-AR-FY13.pdf:pnl:Cost of Materials Consumed:FY12",
        "SYMPHONY-AR-FY13.pdf:pnl:Sales:FY12",
        "SYMPHONY-AR-FY18.pdf:pnl:Cost of Materials Consumed:FY18",
        "SYMPHONY-AR-FY18.pdf:pnl:Sales:FY18"
      ],
      "cite_as": "[fact:derived:material_cost_ratio_delta]",
      "grade": "A"
    },
    "employee_cost_ratio": {
      "value": 0.09105842810782776,
      "formula": "Employee Benefits FY18 / pnl:Sales FY18",
      "fact_ids": [
        "SYMPHONY-AR-FY18.pdf:pnl:Employee Benefits:FY18",
        "SYMPHONY-AR-FY18.pdf:pnl:Sales:FY18"
      ],
      "cite_as": "[fact:derived:employee_cost_ratio]",
      "grade": "A"
    },
    "employee_cost_ratio_delta": {
      "value": 0.0007652667529613744,
      "formula": "Employee Benefits/Sales FY18 - Employee Benefits/Sales FY12",
      "fact_ids": [
        "SYMPHONY-AR-FY13.pdf:pnl:Employee Benefits:FY12",
        "SYMPHONY-AR-FY13.pdf:pnl:Sales:FY12",
        "SYMPHONY-AR-FY18.pdf:pnl:Employee Benefits:FY18",
        "SYMPHONY-AR-FY18.pdf:pnl:Sales:FY18"
      ],
      "cite_as": "[fact:derived:employee_cost_ratio_delta]",
      "grade": "A"
    },
    "other_expense_ratio": {
      "value": 0.11040952478188347,
      "formula": "Other Expenses FY18 / pnl:Sales FY18",
      "fact_ids": [
        "SYMPHONY-AR-FY18.pdf:pnl:Other Expenses:FY18",
        "SYMPHONY-AR-FY18.pdf:pnl:Sales:FY18"
      ],
      "cite_as": "[fact:derived:other_expense_ratio]",
      "grade": "A"
    },
    "other_expense_ratio_delta": {
      "value": -0.13909536506886894,
      "formula": "Other Expenses/Sales FY18 - Other Expenses/Sales FY12",
      "fact_ids": [
        "SYMPHONY-AR-FY13.pdf:pnl:Other Expenses:FY12",
        "SYMPHONY-AR-FY13.pdf:pnl:Sales:FY12",
        "SYMPHONY-AR-FY18.pdf:pnl:Other Expenses:FY18",
        "SYMPHONY-AR-FY18.pdf:pnl:Sales:FY18"
      ],
      "cite_as": "[fact:derived:other_expense_ratio_delta]",
      "grade": "A"
    },
    "cash_yield_latest": {
      "value": 0.13411187735055338,
      "formula": "|Interest Income FY18| / average (Cash + Other Bank Balances), FY17-FY18",
      "fact_ids": [
        "SYMPHONY-AR-FY18.pdf:cashflow:Interest Income:FY18",
        "SYMPHONY-AR-FY18.pdf:balance_sheet:Cash Equivalents:FY18",
        "SYMPHONY-AR-FY18.pdf:balance_sheet:Other Bank Balances:FY18",
        "SYMPHONY-AR-FY18.pdf:balance_sheet:Cash Equivalents:FY17",
        "SYMPHONY-AR-FY18.pdf:balance_sheet:Other Bank Balances:FY17"
      ],
      "cite_as": "[fact:derived:cash_yield_latest]",
      "grade": "A"
    }
  },
  "metrics_unavailable": {
    "opm_latest": [
      "pnl:Operating Profit FY18"
    ],
    "roic_latest": [
      "balance_sheet:Borrowings FY18",
      "pnl:Operating Profit FY18",
      "pnl:Tax % FY18"
    ],
    "interest_coverage_latest": [
      "pnl:Operating Profit FY18"
    ],
    "cost_of_debt_latest": [
      "balance_sheet:Borrowings FY18"
    ],
    "cwip_share_latest": [
      "balance_sheet:CWIP FY18"
    ],
    "cfo_to_ebitda_latest": [
      "pnl:Operating Profit FY18"
    ],
    "fcf_to_pat_cum": [
      "cashflow:Free Cash Flow (no period with both FCF and PAT)"
    ],
    "dilution_drag": [
      "equity share capital moved 6.9957 -> 13.9914 (2.00x) across FY12-FY18, so the share base behind EPS is not comparable; whether that is a bonus/split (cosmetic for holders) or an issuance (real dilution) is a corporate-action disclosure the EPS series cannot answer"
    ],
    "expense_cagr": [
      "pnl:Expenses FY12",
      "pnl:Expenses FY18"
    ],
    "opm_delta_window": [
      "pnl:Operating Profit FY12",
      "pnl:Operating Profit FY18"
    ],
    "effective_tax_rate_latest": [
      "pnl:Tax % FY18"
    ],
    "debt_delta_window": [
      "balance_sheet:Borrowings FY12",
      "balance_sheet:Borrowings FY18"
    ],
    "dividend_cum_window": [
      "pnl:Dividend Payout % (no period with PAT)"
    ],
    "capex_cum_window": [
      "cashflow:Purchase of PPE (no period in the window discloses it)"
    ],
    "capex_to_depreciation": [
      "cashflow:Purchase of PPE and pnl:Depreciation in the same year (the cash-flow capex line comes from the filing, not the screener)"
    ],
    "net_cash_position": [
      "balance_sheet:Borrowings FY18"
    ],
    "cost_of_debt_average": [
      "balance_sheet:Borrowings FY18",
      "balance_sheet:Borrowings FY17"
    ],
    "incremental_roic_3y": [
      "a 4+ year run of Operating Profit, Depreciation, Tax %, Borrowings, Equity Capital and Reserves is required for a rolling 3-year incremental ROIC"
    ]
  },
  "forensic_screen": {
    "verdict": "REVIEW",
    "hard_fail": false,
    "flags": [
      {
        "name": "cfo_pat_low",
        "severity": "HIGH",
        "detail": "CFO/PAT 0.55 < 0.70"
      },
      {
        "name": "high_accruals",
        "severity": "MEDIUM",
        "detail": "|accruals| 0.13 > 0.10"
      }
    ]
  },
  "checklist": [
    {
      "check": "cumulative_cfo_pat",
      "outcome": "PASS",
      "detail": "\u03a3CFO/\u03a3PAT 0.79 vs floor 0.70 (\u03a3 CFO / \u03a3 PAT, FY12-FY18) (grade A)",
      "reason": ""
    },
    {
      "check": "cfo_pat",
      "outcome": "FLAG",
      "detail": "CFO/PAT 0.55 vs floor 0.70 (CFO FY18 / PAT FY18) (grade A)",
      "reason": ""
    },
    {
      "check": "cash_interest_inconsistent",
      "outcome": "PASS",
      "detail": "implied yield on cash and bank balances 13.41% vs floor 2.60% (|Interest Income FY18| / average (Cash + Other Bank Balances), FY17-FY18) (grade A)",
      "reason": ""
    },
    {
      "check": "cash_debt_paradox",
      "outcome": "UNAVAILABLE",
      "detail": "",
      "reason": "this check could not be run on the sources read as-of this run: balance_sheet:Borrowings FY18, balance_sheet:Borrowings FY18"
    },
    {
      "check": "disclosure_gap",
      "outcome": "PASS",
      "detail": "every mandated Schedule III / forensic section located in the filing",
      "reason": ""
    },
    {
      "check": "other_income_heavy",
      "outcome": "PASS",
      "detail": "other income 20.4% of PBT vs limit 25% (pnl:Other Income FY18 / pnl:Profit before tax FY18) (grade A)",
      "reason": ""
    },
    {
      "check": "promoter_lending",
      "outcome": "UNAVAILABLE",
      "detail": "",
      "reason": "inputs not disclosed in the sources read as-of this run: loans and advances to promoters/KMP (Schedule III row)"
    },
    {
      "check": "receivables_divergent",
      "outcome": "PASS",
      "detail": "receivables +17.6% vs revenue +4.4%, gap +13.2% vs limit 25% (AR) (grade A)",
      "reason": ""
    },
    {
      "check": "inventory_divergent",
      "outcome": "PASS",
      "detail": "inventory +2.9% vs revenue +4.4%, gap -1.5% vs limit 30% (AR) (grade A)",
      "reason": ""
    },
    {
      "check": "high_accruals",
      "outcome": "FLAG",
      "detail": "accruals +0.126 vs limit \u00b10.10 ((PAT - CFO)(FY18) / avg Total Assets) (grade A)",
      "reason": ""
    }
  ],
  "notes_to_accounts": {
    "enumerated": 43,
    "coverage": 1.0,
    "substantive_share": 0.11627906976744186,
    "disclosure_gaps": []
  },
  "peer_comparison": [],
  "management_guidance": [],
  "feasibility_gate": null,
  "rules": [
    "Do NOT compute, adjust or invent any number. Quote only the values above.",
    "Every number you write in prose must be followed by its [fact:...] token.",
    "Numeric schema fields must equal the computed value above, or be null.",
    "open_questions must not be empty; disconfirming_search must describe a real search."
  ]
}
```

## Return ONLY a single JSON object matching this schema (Law 4). No prose outside the JSON; put your reasoning in the `narrative` field.
```json
{
  "$defs": {
    "Citation": {
      "description": "Every numeric claim renders with one of these; a validator maps it to a fact (Law 2).",
      "properties": {
        "fact_id": {
          "title": "Fact Id",
          "type": "string"
        },
        "doc_id": {
          "title": "Doc Id",
          "type": "string"
        },
        "locator": {
          "description": "page/paragraph within the source document",
          "title": "Locator",
          "type": "string"
        },
        "published_at": {
          "format": "date",
          "title": "Published At",
          "type": "string"
        },
        "extractor_version": {
          "title": "Extractor Version",
          "type": "string"
        },
        "grade": {
          "$ref": "#/$defs/Grade"
        }
      },
      "required": [
        "fact_id",
        "doc_id",
        "locator",
        "published_at",
        "extractor_version",
        "grade"
      ],
      "title": "Citation",
      "type": "object"
    },
    "Claim": {
      "description": "A single assertion tagged by epistemic status and cited.",
      "properties": {
        "text": {
          "title": "Text",
          "type": "string"
        },
        "kind": {
          "description": "one of: observation | inference | speculation (house style \u00a74)",
          "title": "Kind",
          "type": "string"
        },
        "citations": {
          "items": {
            "$ref": "#/$defs/Citation"
          },
          "title": "Citations",
          "type": "array"
        },
        "confidence": {
          "anyOf": [
            {
              "$ref": "#/$defs/Confidence"
            },
            {
              "type": "null"
            }
          ],
          "default": null
        }
      },
      "required": [
        "text",
        "kind"
      ],
      "title": "Claim",
      "type": "object"
    },
    "Confidence": {
      "description": "Numeric confidence, justified by evidence \u2014 never vibes (house style \u00a75).",
      "properties": {
        "value": {
          "maximum": 1.0,
          "minimum": 0.0,
          "title": "Value",
          "type": "number"
        },
        "evidence_count": {
          "minimum": 0,
          "title": "Evidence Count",
          "type": "integer"
        },
        "lowest_grade_relied_on": {
          "$ref": "#/$defs/Grade"
        },
        "rationale": {
          "title": "Rationale",
          "type": "string"
        }
      },
      "required": [
        "value",
        "evidence_count",
        "lowest_grade_relied_on",
        "rationale"
      ],
      "title": "Confidence",
      "type": "object"
    },
    "Grade": {
      "description": "Source reliability grade (SPEC \u00a74). A thesis pillar may not rest on D alone.",
      "enum": [
        "A",
        "B",
        "C",
        "D"
      ],
      "title": "Grade",
      "type": "string"
    }
  },
  "properties": {
    "agent": {
      "title": "Agent",
      "type": "string"
    },
    "agent_version": {
      "title": "Agent Version",
      "type": "string"
    },
    "ticker": {
      "title": "Ticker",
      "type": "string"
    },
    "as_of": {
      "format": "date",
      "title": "As Of",
      "type": "string"
    },
    "observations": {
      "items": {
        "$ref": "#/$defs/Claim"
      },
      "title": "Observations",
      "type": "array"
    },
    "inferences": {
      "items": {
        "$ref": "#/$defs/Claim"
      },
      "title": "Inferences",
      "type": "array"
    },
    "speculations": {
      "items": {
        "$ref": "#/$defs/Claim"
      },
      "title": "Speculations",
      "type": "array"
    },
    "open_questions": {
      "description": "An empty array is suspicious (house style \u00a73).",
      "items": {
        "type": "string"
      },
      "title": "Open Questions",
      "type": "array"
    },
    "disconfirming_search": {
      "description": "What evidence against the emerging conclusion was sought, and what was found.",
      "title": "Disconfirming Search",
      "type": "string"
    },
    "narrative": {
      "default": "",
      "title": "Narrative",
      "type": "string"
    },
    "incremental_roic": {
      "anyOf": [
        {
          "type": "number"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Incremental Roic"
    },
    "cfo_to_ebitda": {
      "anyOf": [
        {
          "type": "number"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Cfo To Ebitda"
    },
    "fcf_to_pat": {
      "anyOf": [
        {
          "type": "number"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Fcf To Pat"
    },
    "working_capital_days": {
      "anyOf": [
        {
          "type": "number"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Working Capital Days"
    }
  },
  "required": [
    "agent",
    "agent_version",
    "ticker",
    "as_of",
    "disconfirming_search"
  ],
  "title": "FinancialStatementOutput",
  "type": "object"
}
```
