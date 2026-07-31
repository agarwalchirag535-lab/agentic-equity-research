"""Point-in-time facts view + **provenance-locked derived metrics** (Phase 2, ADR-0021).

The gap this closes: `core/compute` produces honest numbers and `core/facts` stores honest facts, but a
*derived* number (ΣCFO/ΣPAT, ROIC, other-income share) had nowhere to carry its provenance. Law 2 says
"provenance or it doesn't exist" — so a ratio that appears in a published report must be able to answer
three questions without a human digging: **which formula, which input facts, and what is the weakest
grade it rests on.**

`Derivation` answers all three:

* `formula` — the human-readable derivation ("Σ CFO / Σ PAT, FY15-FY26"), so a third party can replicate;
* `inputs` — the actual `Fact` rows consumed, each with `(doc_id, locator, published_at, grade)`;
* `citation` — a synthesised `Citation` whose grade is the **worst** input grade and whose `published_at`
  is the **latest** input publication date. A ratio is exactly as reliable as its weakest input and
  exactly as recent as its newest one; anything else would flatter the number.

Two rules make this honest rather than decorative:

1. **A metric is derived only when every input it needs exists.** Missing inputs are recorded in
   `DerivedSet.missing` as the metric names that were absent — they become `UNAVAILABLE` in the report
   with a reason (owner directive 2: missing data is a signal, never a blank), never a zero.
2. **Nothing here computes with an LLM or a network call** (Laws 1 and 6). Every formula delegates to
   `core/compute`; this module only wires facts into it and keeps the receipts.

Point-in-time discipline (Law 3) is inherited: every read goes through `FactStore.query_fact(as_of=...)`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Mapping, Sequence

from firm.core.compute import quality, ratios
from firm.core.compute import roic as RO
from firm.core.facts.store import Fact, FactStore
from firm.schemas._base import Citation, Grade

#: Grades ordered best → worst; the derived grade is the worst input grade (`_worst_grade`).
_GRADE_ORDER = (Grade.A, Grade.B, Grade.C, Grade.D)

#: The metric keys this module knows how to read. Kept explicit (rather than "whatever is in the DB")
#: so a renamed upstream metric surfaces as a missing input instead of silently disappearing.
SALES = "pnl:Sales"
PAT = "pnl:Net Profit"
OPERATING_PROFIT = "pnl:Operating Profit"
DEPRECIATION = "pnl:Depreciation"
INTEREST = "pnl:Interest"
TAX_PCT = "pnl:Tax %"
OTHER_INCOME = "pnl:Other Income"
PBT = "pnl:Profit before tax"
CFO = "cashflow:Cash from Operating Activity"
FCF = "cashflow:Free Cash Flow"
BORROWINGS = "balance_sheet:Borrowings"
EQUITY_CAPITAL = "balance_sheet:Equity Capital"
RESERVES = "balance_sheet:Reserves"
CWIP = "balance_sheet:CWIP"
FIXED_ASSETS = "balance_sheet:Fixed Assets"
TOTAL_ASSETS = "balance_sheet:Total Assets"
#: Governance facts from the quarterly SEBI shareholding pattern (ADR-0035). Quarterly rather than annual,
#: so they never enter an annual derivation — they exist so an agent can CITE promoter holding and pledge
#: instead of abstaining, which is what `ownership_flows_analyst` had to do while the parser wrote nowhere.
PROMOTER_HOLDING = "governance:Promoter Holding"
PUBLIC_HOLDING = "governance:Public Holding"
PROMOTER_PLEDGED = "governance:Promoter Pledged"

CASH = "balance_sheet:Cash Equivalents"
RECEIVABLES = "balance_sheet:Trade Receivables"
INVENTORY = "balance_sheet:Inventories"
#: Lines the interrogation layer (ADR-0022) needs to answer *why* a number moved rather than only what it
#: is. All four are already in the screener snapshot and were previously read by nothing.
EPS = "pnl:EPS in Rs"
EXPENSES = "pnl:Expenses"
DIVIDEND_PAYOUT_PCT = "pnl:Dividend Payout %"
CFI = "cashflow:Cash from Investing Activity"

#: Rows that exist only once an AUDITED ANNUAL REPORT has been walked (`core/pipeline/filing.py`). The
#: screener snapshot carries none of them: it collapses the P&L expense breakup into one `Expenses` row
#: and omits payables, the cash-flow detail and the balance-sheet cash split entirely. Every question in
#: `config/line_items.yaml` that was UNANSWERED for want of "the P&L expense breakup" or "trade payables
#: per year" is unanswered for want of exactly these.
TOTAL_INCOME = "pnl:Total Income"
MATERIALS = "pnl:Cost of Materials Consumed"
INVENTORY_CHANGE = "pnl:Changes in Inventories"
EMPLOYEE_COST = "pnl:Employee Benefits"
OTHER_EXPENSES = "pnl:Other Expenses"
TOTAL_EXPENSES = "pnl:Total Expenses"
TOTAL_TAX = "pnl:Total Tax"
OTHER_BANK = "balance_sheet:Other Bank Balances"
PAYABLES = "balance_sheet:Trade Payables"
CFF = "cashflow:Cash from Financing Activity"
CAPEX = "cashflow:Purchase of PPE"
DIVIDEND_PAID = "cashflow:Dividend Paid"
INTEREST_PAID = "cashflow:Interest Paid"
INTEREST_INCOME = "cashflow:Interest Income"

#: The remainder of the balance sheet. No derivation reads these and none is expected to: they exist so
#: that every note to the accounts has a face figure to reconcile against (`filing.reconcile_notes`), which
#: is what turns "the notes were enumerated" into "the notes were read". They are still stored as
#: grade-A facts with locators, so an agent may cite any of them.
ROU_ASSETS = "balance_sheet:Right of Use Assets"
INTANGIBLES = "balance_sheet:Intangible Assets"
NONCURRENT_LOANS = "balance_sheet:Non-Current Loans"
CURRENT_LOANS = "balance_sheet:Current Loans"
OTHER_NONCURRENT_FIN_ASSETS = "balance_sheet:Other Non-Current Financial Assets"
OTHER_CURRENT_FIN_ASSETS = "balance_sheet:Other Current Financial Assets"
OTHER_NONCURRENT_ASSETS = "balance_sheet:Other Non-Current Assets"
OTHER_CURRENT_ASSETS = "balance_sheet:Other Current Assets"
NONCURRENT_PROVISIONS = "balance_sheet:Long Term Provisions"
CURRENT_PROVISIONS = "balance_sheet:Short Term Provisions"
DEFERRED_TAX = "balance_sheet:Deferred Tax Liabilities"
OTHER_FIN_LIABILITIES = "balance_sheet:Other Financial Liabilities"
OTHER_CURRENT_LIABILITIES = "balance_sheet:Other Current Liabilities"

BALANCE_SHEET_REMAINDER: tuple[str, ...] = (
    ROU_ASSETS, INTANGIBLES, NONCURRENT_LOANS, CURRENT_LOANS, OTHER_NONCURRENT_FIN_ASSETS,
    OTHER_CURRENT_FIN_ASSETS, OTHER_NONCURRENT_ASSETS, OTHER_CURRENT_ASSETS, NONCURRENT_PROVISIONS,
    CURRENT_PROVISIONS, DEFERRED_TAX, OTHER_FIN_LIABILITIES, OTHER_CURRENT_LIABILITIES,
)

READ_METRICS: tuple[str, ...] = (
    SALES, PAT, OPERATING_PROFIT, DEPRECIATION, INTEREST, TAX_PCT, OTHER_INCOME, PBT,
    CFO, FCF, BORROWINGS, EQUITY_CAPITAL, RESERVES, CWIP, FIXED_ASSETS, TOTAL_ASSETS,
    CASH, RECEIVABLES, INVENTORY,
    EPS, EXPENSES, DIVIDEND_PAYOUT_PCT, CFI,
    TOTAL_INCOME, MATERIALS, INVENTORY_CHANGE, EMPLOYEE_COST, OTHER_EXPENSES, TOTAL_EXPENSES,
    TOTAL_TAX, OTHER_BANK, PAYABLES, CFF, CAPEX, DIVIDEND_PAID, INTEREST_PAID, INTEREST_INCOME,
    *BALANCE_SHEET_REMAINDER,
)

#: Days in the year used for every turnover ratio. Not a policy threshold — a calendar fact.
DAYS_IN_YEAR = 365.0


#: Metrics filed quarterly rather than annually. Read against quarter labels (`Q2FY25`), never mixed into an
#: annual derivation — a promoter stake is a point-in-time holding, not a flow to compound.
QUARTERLY_METRICS: tuple[str, ...] = (PROMOTER_HOLDING, PUBLIC_HOLDING, PROMOTER_PLEDGED)


def _worst_grade(grades: Sequence[str]) -> Grade:
    """The weakest grade among the inputs — a derived figure cannot be stronger than its worst source."""
    seen = {Grade(g) for g in grades}
    for grade in reversed(_GRADE_ORDER):
        if grade in seen:
            return grade
    raise ValueError("no grades to compare")  # pragma: no cover - guarded by callers


def fiscal_years(as_of: date, start_year: int) -> tuple[str, ...]:
    """Indian fiscal-year labels FY{yy} from ``start_year`` to the last FY closed on/before ``as_of``.

    The Indian FY ends 31 March, so a date in Jan-Mar is still inside the prior fiscal year.
    """
    latest = as_of.year if as_of.month >= 4 else as_of.year - 1
    return tuple(f"FY{y % 100:02d}" for y in range(start_year, latest + 1))


@dataclass(frozen=True)
class CompanyFacts:
    """Every stored fact for one company, read as-of a date (Law 3 enforced at the query layer)."""

    ticker: str
    as_of: date
    periods: tuple[str, ...]                       # ascending, only periods with any data
    series: Mapping[str, Mapping[str, Fact]]       # metric -> period -> Fact

    def fact(self, metric: str, period: str) -> Fact | None:
        return self.series.get(metric, {}).get(period)

    def value(self, metric: str, period: str) -> float | None:
        f = self.fact(metric, period)
        return None if f is None else f.value

    def has(self, metric: str) -> bool:
        return bool(self.series.get(metric))

    def latest_period(self, metric: str) -> str | None:
        available = [p for p in self.periods if self.fact(metric, p) is not None]
        return available[-1] if available else None

    def all_fact_ids(self) -> tuple[str, ...]:
        return tuple(
            f.fact_id for metric in self.series for f in self.series[metric].values()
        )


def load_company_facts(
    store: FactStore,
    ticker: str,
    as_of: date,
    *,
    start_year: int = 2015,
    metrics: Sequence[str] = READ_METRICS,
    quarterly_metrics: Sequence[str] = QUARTERLY_METRICS,
) -> CompanyFacts:
    """Read the known metric set for ``ticker`` as-of ``as_of``. Absent metrics are simply absent.

    Two passes, because two cadences. Annual metrics are read against fiscal years; the SEBI shareholding
    pattern is filed quarterly, so its facts carry quarter labels (`Q2FY25`) that an annual-only scan never
    queries. Before the second pass the governance facts existed in the store, loaded into nothing, and
    `ownership_flows_analyst` abstained for want of anything it could cite (ADR-0035).
    """
    series: dict[str, dict[str, Fact]] = {}
    periods_with_data: list[str] = []
    for period in fiscal_years(as_of, start_year):
        found = False
        for metric in metrics:
            fact = store.query_fact(ticker, metric, period, as_of=as_of)
            if fact is not None:
                series.setdefault(metric, {})[period] = fact
                found = True
        if found:
            periods_with_data.append(period)
        # Quarterly facts hang off the fiscal year they fall in, so a run that knows its years knows its
        # quarters. They are NOT added to `periods_with_data`: `history_years` counts annual periods, and a
        # quarterly filing must not inflate the apparent length of the record.
        for quarter in (f"Q{n}{period}" for n in (1, 2, 3, 4)):
            for metric in quarterly_metrics:
                fact = store.query_fact(ticker, metric, quarter, as_of=as_of)
                if fact is not None:
                    series.setdefault(metric, {})[quarter] = fact
    return CompanyFacts(ticker, as_of, tuple(periods_with_data), series)


@dataclass(frozen=True)
class Derivation:
    """One derived number with the receipts: formula, input facts, and a provenance-locked citation."""

    metric: str
    value: float
    formula: str
    inputs: tuple[Fact, ...]
    extractor_version: str = "core.compute@1.0.0"

    @property
    def fact_ids(self) -> tuple[str, ...]:
        return tuple(f.fact_id for f in self.inputs)

    @property
    def citation(self) -> Citation:
        """A citation for a computed number: the derivation *is* the source, and it names its inputs.

        `grade` is the worst input grade and `published_at` the latest input publication date, so the
        derived figure can never look better-sourced or fresher than the facts underneath it.
        """
        return Citation(
            fact_id=f"derived:{self.metric}",
            doc_id=f"derivation:{self.formula}",
            locator="inputs " + ", ".join(self.fact_ids),
            published_at=max(f.published_at for f in self.inputs),
            extractor_version=self.extractor_version,
            grade=_worst_grade([f.grade for f in self.inputs]),
        )


@dataclass(frozen=True)
class DerivedSet:
    """Derived metrics plus an explicit record of what could not be derived and why.

    `missing[metric]` lists the input metric names that were absent. That list is what turns into an
    `UNAVAILABLE` check record with a reason, instead of a silently missing row.
    """

    ticker: str
    as_of: date
    values: Mapping[str, Derivation]
    missing: Mapping[str, tuple[str, ...]]
    first_period: str | None = None
    last_period: str | None = None

    def get(self, metric: str) -> Derivation | None:
        return self.values.get(metric)

    def value(self, metric: str) -> float | None:
        d = self.values.get(metric)
        return None if d is None else d.value

    @property
    def years(self) -> int:
        if self.first_period is None or self.last_period is None:
            return 0
        return int(self.last_period[2:]) - int(self.first_period[2:])


class _Builder:
    """Accumulates derivations, recording missing inputs instead of guessing at them."""

    def __init__(self, facts: CompanyFacts) -> None:
        self.facts = facts
        self.values: dict[str, Derivation] = {}
        self.missing: dict[str, tuple[str, ...]] = {}

    def need(self, metric: str, *pairs: tuple[str, str]) -> list[Fact] | None:
        """Fetch every (metric, period) input; on any absence record the gap and return None."""
        got: list[Fact] = []
        absent: list[str] = []
        for m, period in pairs:
            fact = self.facts.fact(m, period)
            if fact is None:
                absent.append(f"{m} {period}")
            else:
                got.append(fact)
        if absent:
            self.missing[metric] = tuple(absent)
            return None
        return got

    def add(self, metric: str, value: float | None, formula: str, inputs: Sequence[Fact]) -> None:
        if value is None:
            self.missing.setdefault(metric, ("undefined for these inputs",))
            return
        self.values[metric] = Derivation(metric, float(value), formula, tuple(inputs))


def _as_fraction(fact: Fact) -> float:
    """A percent-named row as a fraction, using the stored `unit` rather than guessing from magnitude.

    Rows like `pnl:Tax %` and `pnl:Dividend Payout %` arrive as `unit="ratio"` already scaled (0.26 for
    26%), while an extractor reading a printed percentage off an annual-report page yields 26.0. Both must
    land on the same scale before any arithmetic touches them.

    The obvious shortcut — `v / 100 if v > 1 else v` — is wrong exactly where it matters: an effective tax
    rate of 120% (prior-period adjustments) or a payout ratio of 150% (paying out of reserves) are real,
    and the shortcut silently turns them into 1.2% and 1.5%. Both are anomalies a forensic report should
    surface, so the one input that must not be mangled is the anomalous one. `unit` removes the guess.
    """
    return fact.value if fact.unit == "ratio" else fact.value / 100.0


def _cagr(first: float, last: float, years: int) -> float | None:
    if years <= 0 or first <= 0 or last <= 0:
        return None
    return (last / first) ** (1.0 / years) - 1.0


def _cum(
    b: _Builder,
    facts: CompanyFacts,
    metric: str,
    source: str,
    periods: Sequence[str],
    formula: str,
    *,
    sign: float = 1.0,
) -> Derivation | None:
    """Sum ``source`` across every period that has it, recording the gap when none does.

    ``sign=-1`` flips a cash-flow line that is negative for an outflow (CFI), so the derived figure reads
    as the *cost* of the programme rather than as a negative number the reader has to re-interpret.
    Returns the `Derivation` so a caller can build a ratio on it without re-summing.
    """
    usable = [p for p in periods if facts.fact(source, p) is not None]
    if not usable:
        b.missing.setdefault(metric, (f"{source} (no period in the window discloses it)",))
        return None
    inputs = [facts.fact(source, p) for p in usable]
    b.add(metric, sign * sum(facts.value(source, p) for p in usable), formula, inputs)
    return b.values.get(metric)


def derive_metrics(facts: CompanyFacts) -> DerivedSet:
    """Compute every derived metric the Phase-2 report and checks need, keeping provenance on each.

    Nothing is estimated: a metric whose inputs are absent lands in `missing`, which the report renders
    as `UNAVAILABLE` with the reason. This is the mechanism behind owner directive 3 (zero hallucination).
    """
    b = _Builder(facts)
    with_core = [p for p in facts.periods if facts.fact(SALES, p) and facts.fact(PAT, p)]
    if not with_core:
        return DerivedSet(facts.ticker, facts.as_of, {}, {"*": ("no Sales/PAT history",)})
    f0, fN = with_core[0], with_core[-1]
    span = int(fN[2:]) - int(f0[2:])

    # ---- growth + margins -----------------------------------------------------------------------
    if (got := b.need("revenue_cagr", (SALES, f0), (SALES, fN))) is not None:
        b.add("revenue_cagr", _cagr(got[0].value, got[1].value, span),
              f"({SALES} {fN} / {SALES} {f0})^(1/{span}) - 1", got)
    if (got := b.need("pat_cagr", (PAT, f0), (PAT, fN))) is not None:
        b.add("pat_cagr", _cagr(got[0].value, got[1].value, span),
              f"({PAT} {fN} / {PAT} {f0})^(1/{span}) - 1", got)
    if (got := b.need("opm_latest", (OPERATING_PROFIT, fN), (SALES, fN))) is not None:
        b.add("opm_latest", got[0].value / got[1].value if got[1].value else None,
              f"{OPERATING_PROFIT} {fN} / {SALES} {fN}", got)

    # ---- returns on capital ---------------------------------------------------------------------
    invested_inputs = b.need("roic_latest", (BORROWINGS, fN), (EQUITY_CAPITAL, fN), (RESERVES, fN),
                             (OPERATING_PROFIT, fN), (DEPRECIATION, fN), (TAX_PCT, fN))
    if invested_inputs is not None:
        borrow, eq, res, op, dep = (f.value for f in invested_inputs[:5])
        invested = borrow + eq + res
        nopat = RO.nopat(op - dep, _as_fraction(invested_inputs[5]))
        b.add("roic_latest", RO.roic(nopat, invested) if invested > 0 else None,
              f"NOPAT({fN}) / (Borrowings + Equity Capital + Reserves)({fN})", invested_inputs)

    # ---- cash reality (ADR-0006) ----------------------------------------------------------------
    cash_periods = [p for p in with_core if facts.fact(CFO, p) and facts.fact(PAT, p)]
    if cash_periods:
        inputs = [facts.fact(CFO, p) for p in cash_periods] + [facts.fact(PAT, p) for p in cash_periods]
        pat_sum = sum(facts.value(PAT, p) for p in cash_periods)
        b.add("cum_cfo_pat",
              quality.cumulative_cfo_pat_ratio(
                  [facts.value(CFO, p) for p in cash_periods],
                  [facts.value(PAT, p) for p in cash_periods]) if pat_sum else None,
              f"Σ CFO / Σ PAT, {cash_periods[0]}-{cash_periods[-1]}", inputs)
    else:
        b.missing["cum_cfo_pat"] = (f"{CFO} (no period with both CFO and PAT)",)

    if (got := b.need("cfo_pat_latest", (CFO, fN), (PAT, fN))) is not None:
        b.add("cfo_pat_latest",
              quality.cfo_pat_ratio(got[0].value, got[1].value) if got[1].value else None,
              f"CFO {fN} / PAT {fN}", got)

    if (got := b.need("accrual_ratio_latest", (PAT, fN), (CFO, fN),
                      (TOTAL_ASSETS, fN),
                      (TOTAL_ASSETS, with_core[-2] if len(with_core) >= 2 else fN))) is not None:
        avg_assets = (got[2].value + got[3].value) / 2.0
        b.add("accrual_ratio_latest",
              quality.accrual_ratio(got[0].value, got[1].value, avg_assets) if avg_assets > 0 else None,
              f"(PAT - CFO)({fN}) / avg Total Assets", got)

    # ---- other income / interest ----------------------------------------------------------------
    # Raw ratios only: the threshold comparison lives in `checks.py` so a single check owns a single
    # policy number. `other_income_share` here is the value; `quality.other_income_share` does the flag.
    if (got := b.need("other_income_share", (OTHER_INCOME, fN), (PBT, fN))) is not None:
        b.add("other_income_share",
              got[0].value / got[1].value if got[1].value > 0 else None,
              f"{OTHER_INCOME} {fN} / {PBT} {fN}", got)
    if (got := b.need("interest_coverage_latest", (OPERATING_PROFIT, fN), (DEPRECIATION, fN),
                      (INTEREST, fN))) is not None:
        b.add("interest_coverage_latest",
              ratios.interest_coverage(got[0].value - got[1].value, got[2].value)
              if got[2].value > 0 else None,
              f"EBIT {fN} / Interest {fN}", got)
    if (got := b.need("cost_of_debt_latest", (INTEREST, fN), (BORROWINGS, fN))) is not None:
        b.add("cost_of_debt_latest", got[0].value / got[1].value if got[1].value > 0 else None,
              f"Interest {fN} / Borrowings {fN}", got)

    # ---- CWIP ageing ----------------------------------------------------------------------------
    if (got := b.need("cwip_share_latest", (CWIP, fN), (TOTAL_ASSETS, fN))) is not None:
        b.add("cwip_share_latest", got[0].value / got[1].value if got[1].value > 0 else None,
              f"CWIP {fN} / Total Assets {fN}", got)

    # ---- the ratios the financial_statement_analyst is allowed to quote -------------------------
    # These exist so the agent's numeric schema fields can be ARITHMETICALLY VERIFIED against the
    # compute layer (Law 1). A field with no derivation here must come back null from the agent.
    if (got := b.need("cfo_to_ebitda_latest", (CFO, fN), (OPERATING_PROFIT, fN))) is not None:
        b.add("cfo_to_ebitda_latest",
              ratios.cfo_to_ebitda(got[0].value, got[1].value) if got[1].value else None,
              f"CFO {fN} / Operating Profit {fN}", got)

    fcf_periods = [p for p in with_core if facts.fact(FCF, p) and facts.fact(PAT, p)]
    if fcf_periods:
        inputs = [facts.fact(FCF, p) for p in fcf_periods] + [facts.fact(PAT, p) for p in fcf_periods]
        pat_sum = sum(facts.value(PAT, p) for p in fcf_periods)
        b.add("fcf_to_pat_cum",
              (sum(facts.value(FCF, p) for p in fcf_periods) / pat_sum) if pat_sum else None,
              f"Σ FCF / Σ PAT, {fcf_periods[0]}-{fcf_periods[-1]}", inputs)
    else:
        b.missing["fcf_to_pat_cum"] = (f"{FCF} (no period with both FCF and PAT)",)

    # ---- WHY a line moved, not just what it is (ADR-0022) ---------------------------------------
    # Everything below answers a *causal* question with arithmetic instead of adjectives. Each one exists
    # because a report that says "revenue grew 11%" and stops is a screener with prose attached: the
    # analyst question is always "grew on what — volume, price, an acquisition, or an accounting choice?"
    # These are the ones a screener snapshot can answer honestly; the rest are asked and left explicitly
    # unanswered by `interrogate.py`, which names the annual-report row that would close each gap.
    #
    # No thresholds here, deliberately: this module produces raw values and `config/line_items.yaml` owns
    # every band that turns a value into a judgment (SPEC §3 — no policy numbers in Python).

    # Per-share reality. Aggregate profit growth flatters a company that bought its growth with equity:
    # PAT can compound at 13% while EPS compounds at 9%, and the 4-point wedge is the shareholder's.
    # The firm's question is a 5-10x *per share*, so the wedge is load-bearing, not a footnote.
    if (got := b.need("eps_cagr", (EPS, f0), (EPS, fN))) is not None:
        b.add("eps_cagr", _cagr(got[0].value, got[1].value, span),
              f"({EPS} {fN} / {EPS} {f0})^(1/{span}) - 1", got)
    pat_c, eps_c = b.values.get("pat_cagr"), b.values.get("eps_cagr")
    if pat_c is not None and eps_c is not None:
        b.add("dilution_drag", pat_c.value - eps_c.value,
              f"PAT CAGR - EPS CAGR, {f0}-{fN} (positive = per-share growth lagged aggregate growth)",
              tuple(pat_c.inputs) + tuple(eps_c.inputs))
    elif eps_c is None:
        b.missing.setdefault("dilution_drag", (f"{EPS} at {f0} and {fN}",))

    # Cost growth against revenue growth: the deterministic half of "why did the margin move?". The other
    # half (which cost line moved — material, power, employee) needs the P&L expense breakup from the AR;
    # the screener collapses it to a single `Expenses` row, so that question is asked and left unanswered.
    if (got := b.need("expense_cagr", (EXPENSES, f0), (EXPENSES, fN))) is not None:
        b.add("expense_cagr", _cagr(got[0].value, got[1].value, span),
              f"({EXPENSES} {fN} / {EXPENSES} {f0})^(1/{span}) - 1", got)
    if (got := b.need("opm_delta_window", (OPERATING_PROFIT, f0), (SALES, f0),
                      (OPERATING_PROFIT, fN), (SALES, fN))) is not None:
        op0, s0, opN, sN = (f.value for f in got)
        b.add("opm_delta_window", (opN / sN) - (op0 / s0) if s0 and sN else None,
              f"OPM {fN} - OPM {f0} (margin trajectory across the window)", got)

    # Effective tax rate, raw. A rate persistently far from statutory is either a real incentive the notes
    # must name, or profit booked where it is not taxed — the interrogation config decides which band.
    if (got := b.need("effective_tax_rate_latest", (TAX_PCT, fN))) is not None:
        b.add("effective_tax_rate_latest", _as_fraction(got[0]), f"{TAX_PCT} {fN}", got)

    # ---- "why is the debt increasing?" ----------------------------------------------------------
    # Rising debt is not a finding; unexplained rising debt is. The cash-flow identity attributes the
    # change deterministically: over the window the company spent `investing_outflow_cum` on its
    # investment programme, generated `cfo_cum_window` from operations, and moved borrowings by
    # `debt_delta_window`. Those three fix whether new debt funded capacity (defensible), or funded
    # distributions and working capital (the pattern that precedes a balance-sheet accident).
    if (got := b.need("debt_delta_window", (BORROWINGS, f0), (BORROWINGS, fN))) is not None:
        b.add("debt_delta_window", got[1].value - got[0].value,
              f"Borrowings {fN} - Borrowings {f0}", got)

    cfo_sum = _cum(b, facts, "cfo_cum_window", CFO, with_core, f"Σ CFO, {f0}-{fN}")
    # CFI is negative for an outflow, so the *cost* of the investment programme is -Σ CFI. A positive
    # result means net investor; negative means the company was a net seller of assets over the window.
    cfi_sum = _cum(b, facts, "investing_outflow_cum", CFI, with_core, f"-Σ CFI, {f0}-{fN}", sign=-1.0)

    debt_delta = b.values.get("debt_delta_window")
    if cfi_sum is not None and cfi_sum.value > 0:
        if cfo_sum is not None:
            b.add("self_funding_ratio", cfo_sum.value / cfi_sum.value,
                  f"Σ CFO / -Σ CFI, {f0}-{fN} (>=1 means operations paid for the investment programme)",
                  tuple(cfo_sum.inputs) + tuple(cfi_sum.inputs))
        if debt_delta is not None:
            b.add("debt_funded_investment_share", debt_delta.value / cfi_sum.value,
                  f"ΔBorrowings / -Σ CFI, {f0}-{fN} (share of the investment programme debt paid for)",
                  tuple(debt_delta.inputs) + tuple(cfi_sum.inputs))
    else:
        for metric in ("self_funding_ratio", "debt_funded_investment_share"):
            b.missing.setdefault(metric, (
                f"{CFI} over {f0}-{fN} summing to a net outflow (the window shows no net investment)",))

    # Distributions competing with the capex programme: a company borrowing while paying out is making a
    # capital-allocation choice that has to be named rather than averaged away.
    div_periods = [p for p in with_core if facts.fact(DIVIDEND_PAYOUT_PCT, p) and facts.fact(PAT, p)]
    if div_periods:
        inputs = ([facts.fact(DIVIDEND_PAYOUT_PCT, p) for p in div_periods]
                  + [facts.fact(PAT, p) for p in div_periods])
        paid = sum(
            facts.value(PAT, p) * _as_fraction(facts.fact(DIVIDEND_PAYOUT_PCT, p)) for p in div_periods
        )
        b.add("dividend_cum_window", paid,
              f"Σ (Dividend Payout % × PAT), {div_periods[0]}-{div_periods[-1]}", inputs)
        if cfo_sum is not None and cfo_sum.value > 0:
            b.add("payout_share_of_cfo", paid / cfo_sum.value,
                  f"Σ dividends / Σ CFO, {f0}-{fN}", inputs + list(cfo_sum.inputs))
    else:
        b.missing.setdefault("dividend_cum_window", (f"{DIVIDEND_PAYOUT_PCT} (no period with PAT)",))

    # ---- working capital: the bridge between reported profit and cash (ADR-0037) ----------------
    # These three were named in `config/line_items.yaml` from the day it was written and had no
    # derivation behind them, because receivables, inventory and payables are not in a screener snapshot.
    # They are on the audited balance sheet, and the whole working-capital section of the report was
    # UNANSWERED for want of a filing walk rather than for want of disclosure.
    _working_capital_days(b, facts, with_core)

    # ---- WHICH cost line moved -------------------------------------------------------------------
    # "Margins fell" is not an analysis. An Ind AS P&L prints the expense breakup — materials, employee
    # benefits, other — and the ratio of each to revenue, differenced across the window, says which one
    # actually moved and by how much. The screener collapses all three into one `Expenses` row, which is
    # why this question could only ever be asked, never answered, before the filings were read.
    for metric, source, label in (("material_cost_ratio", MATERIALS, "Cost of Materials Consumed"),
                                  ("employee_cost_ratio", EMPLOYEE_COST, "Employee Benefits"),
                                  ("other_expense_ratio", OTHER_EXPENSES, "Other Expenses")):
        if (got := b.need(metric, (source, fN), (SALES, fN))) is not None:
            b.add(metric, got[0].value / got[1].value if got[1].value else None,
                  f"{label} {fN} / {SALES} {fN}", got)
        # The window is the one this LINE covers, not the one the headline CAGRs cover. Sales and profit
        # reach back to FY15 through the screener; the expense breakup starts wherever the oldest annual
        # report walked does. Anchoring the delta to the headline window would report the breakup as
        # unavailable for the whole decade because one year at the far end is missing.
        span = [p for p in with_core
                if facts.fact(source, p) is not None and facts.fact(SALES, p) is not None]
        if len(span) >= 2:
            got = [facts.fact(m, p) for p in (span[0], span[-1]) for m in (source, SALES)]
            c0, s0, cN, sN = (f.value for f in got)
            b.add(f"{metric}_delta", (cN / sN) - (c0 / s0) if s0 and sN else None,
                  f"{label}/Sales {span[-1]} - {label}/Sales {span[0]}", got)
        else:
            b.missing.setdefault(f"{metric}_delta", (f"{source} in two or more years",))

    # ---- capex against the maintenance floor -----------------------------------------------------
    # Depreciation is the accountant's estimate of what it costs to stand still, so capex measured
    # against it separates a company replacing its assets from one building new capacity. Without the
    # split, a negative incremental return cannot be told apart from ordinary replacement — which is the
    # difference between value destruction and keeping the lights on.
    # BOTH SUMS RUN OVER THE SAME YEARS. The capex line comes from the cash-flow statement and so exists
    # only for the years an annual report was walked; depreciation is also in the screener and reaches
    # further back. Summing each over "whatever years it has" would divide eleven years of depreciation
    # into ten of capex and call the answer a ratio.
    both = [p for p in with_core if facts.fact(CAPEX, p) and facts.fact(DEPRECIATION, p)]
    capex_sum = _cum(b, facts, "capex_cum_window", CAPEX, with_core, f"Σ |capex|, {f0}-{fN}", sign=-1.0)
    if both:
        window = f"{both[0]}-{both[-1]}"
        inputs = ([facts.fact(CAPEX, p) for p in both] + [facts.fact(DEPRECIATION, p) for p in both])
        capex_total = abs(sum(facts.value(CAPEX, p) for p in both))
        depreciation_total = sum(facts.value(DEPRECIATION, p) for p in both)
        b.add("capex_to_depreciation",
              capex_total / depreciation_total if depreciation_total > 0 else None,
              f"Σ |capex| / Σ Depreciation, {window} (1.0x = replacement only; above = expansion)",
              inputs)
    else:
        b.missing.setdefault("capex_to_depreciation", (
            f"{CAPEX} and {DEPRECIATION} in the same year (the cash-flow capex line comes from the "
            f"filing, not the screener)",))

    # ---- is the cash real? -----------------------------------------------------------------------
    # The sharpest test in the forensic library, and it needs two rows a screener does not carry. Cash
    # that exists earns interest at a rate you can compute; cash that does not exist earns nothing. The
    # denominator is the average balance, because interest accrues across the year.
    prior = with_core[-2] if len(with_core) >= 2 else fN
    if (got := b.need("cash_yield_latest", (INTEREST_INCOME, fN), (CASH, fN), (OTHER_BANK, fN),
                      (CASH, prior), (OTHER_BANK, prior))) is not None:
        income = abs(got[0].value)
        average = (got[1].value + got[2].value + got[3].value + got[4].value) / 2.0
        b.add("cash_yield_latest", income / average if average > 0 else None,
              f"|Interest Income {fN}| / average (Cash + Other Bank Balances), {prior}-{fN}", got)
    if (got := b.need("net_cash_position", (CASH, fN), (OTHER_BANK, fN), (BORROWINGS, fN))) is not None:
        b.add("net_cash_position", got[0].value + got[1].value - got[2].value,
              f"Cash + Other Bank Balances - Borrowings, {fN}", got)

    # Cost of debt on the AVERAGE balance rather than the closing one. `cost_of_debt_latest` divides a
    # full year of interest by a year-end snapshot, so a company that repaid before 31 March produces a
    # rate of several hundred percent — the reason `config/line_items.yaml` declares that ratio
    # implausible outside 2-30% and refuses to narrate it.
    if (got := b.need("cost_of_debt_average", (INTEREST, fN), (BORROWINGS, fN),
                      (BORROWINGS, prior))) is not None:
        average_debt = (got[1].value + got[2].value) / 2.0
        b.add("cost_of_debt_average", got[0].value / average_debt if average_debt > 0 else None,
              f"Interest {fN} / average Borrowings, {prior}-{fN}", got)

    incremental = _incremental_roic(facts, with_core)
    if incremental is None:
        b.missing["incremental_roic_3y"] = ((
            "a 4+ year run of Operating Profit, Depreciation, Tax %, Borrowings, Equity Capital and "
            "Reserves is required for a rolling 3-year incremental ROIC"
        ),)
    else:
        value, inputs, window = incremental
        b.add("incremental_roic_3y", value, f"ΔNOPAT / ΔInvested capital, {window}", inputs)

    return DerivedSet(facts.ticker, facts.as_of, b.values, b.missing, f0, fN)


def _working_capital_days(b: _Builder, facts: CompanyFacts, periods: Sequence[str]) -> None:
    """Receivable / inventory / payable days and the cash-conversion cycle, plus the year-on-year move.

    Cost of goods sold, not revenue, is the denominator for inventory and payables: both are carried at
    cost, and dividing them by revenue silently embeds the gross margin in what is supposed to be a
    turnover measure. Ind AS prints COGS as two rows — materials consumed plus the change in finished
    goods and work-in-progress — so it is composed here rather than assumed.

    The DELTA is the finding, not the level. A processor's absolute receivable days say little without a
    peer; receivables that lengthened while revenue fell is the classic signature of sales booked to hit
    a number, and it is arithmetic rather than judgment.
    """
    latest = periods[-1]
    prior = periods[-2] if len(periods) >= 2 else None

    def cogs(period: str) -> tuple[float, tuple[Fact, ...]] | None:
        materials, change = facts.fact(MATERIALS, period), facts.fact(INVENTORY_CHANGE, period)
        if materials is None:
            return None
        # The change in FG/WIP is a real expense line but a small one; a filing that omits it (or whose
        # row could not be read) still supports a defensible cost base from materials alone.
        total = materials.value + (change.value if change is not None else 0.0)
        inputs = (materials,) if change is None else (materials, change)
        return (total, inputs) if total > 0 else None

    def days(metric: str, balance_metric: str, period: str, use_cogs: bool) -> Derivation | None:
        balance = facts.fact(balance_metric, period)
        if balance is None:
            b.missing.setdefault(metric, (f"{balance_metric} {period}",))
            return None
        if use_cogs:
            base = cogs(period)
            if base is None:
                b.missing.setdefault(metric, (f"{MATERIALS} {period} (cost base for a turnover ratio)",))
                return None
            denominator, extra = base
            formula = f"{balance_metric} {period} / (Materials + Δ FG/WIP) {period} x 365"
        else:
            sales = facts.fact(SALES, period)
            if sales is None or sales.value <= 0:
                b.missing.setdefault(metric, (f"{SALES} {period}",))
                return None
            denominator, extra, formula = sales.value, (sales,), (
                f"{balance_metric} {period} / {SALES} {period} x 365")
        b.add(metric, balance.value / denominator * DAYS_IN_YEAR, formula, (balance,) + extra)
        return b.values.get(metric)

    receivable = days("receivable_days", RECEIVABLES, latest, use_cogs=False)
    inventory = days("inventory_days", INVENTORY, latest, use_cogs=True)
    payable = days("payable_days", PAYABLES, latest, use_cogs=True)

    # Computed into a throwaway builder so the prior year's LEVEL never reaches the report as if it were
    # the current one; only the difference is published.
    before = (_days_at(_Builder(facts), facts, RECEIVABLES, prior, use_cogs=False)
              if receivable is not None and prior is not None else None)
    if receivable is not None and before is not None:
        b.add("receivable_days_delta", receivable.value - before.value,
              f"Receivable days {latest} - {prior} (positive = collection is slowing)",
              tuple(receivable.inputs) + tuple(before.inputs))
    else:
        b.missing.setdefault("receivable_days_delta", (
            f"{RECEIVABLES} and {SALES} in two consecutive years",))

    if receivable is not None and inventory is not None and payable is not None:
        b.add("cash_conversion_cycle",
              receivable.value + inventory.value - payable.value,
              f"Receivable days + Inventory days - Payable days, {latest} (days of cash tied up)",
              tuple(receivable.inputs) + tuple(inventory.inputs) + tuple(payable.inputs))
    else:
        b.missing.setdefault("cash_conversion_cycle", tuple(
            m for m, d in ((RECEIVABLES, receivable), (INVENTORY, inventory), (PAYABLES, payable))
            if d is None))


def _days_at(
    b: _Builder, facts: CompanyFacts, balance_metric: str, period: str, *, use_cogs: bool
) -> Derivation | None:
    """One year's turnover-days figure, for differencing. Same arithmetic, no report entry."""
    balance = facts.fact(balance_metric, period)
    sales = facts.fact(SALES, period)
    if balance is None or sales is None or sales.value <= 0 or use_cogs:
        return None
    b.add("_days", balance.value / sales.value * DAYS_IN_YEAR, "", (balance, sales))
    return b.values.get("_days")


def _incremental_roic(
    facts: CompanyFacts, periods: Sequence[str]
) -> tuple[float, tuple[Fact, ...], str] | None:
    """Latest rolling 3-year ΔNOPAT/ΔInvested, with the facts it consumed. None when the run is short.

    Incremental ROIC is the number the `financial_statement_analyst` is explicitly told to report even
    when average ROIC looks fine, so it is derived here rather than left to prose.
    """
    needed = (OPERATING_PROFIT, DEPRECIATION, TAX_PCT, BORROWINGS, EQUITY_CAPITAL, RESERVES)
    usable = [p for p in periods if all(facts.fact(m, p) is not None for m in needed)]
    if len(usable) < 4:
        return None
    window = usable[-4:]
    inputs = tuple(facts.fact(m, p) for p in window for m in needed)

    def nopat_of(period: str) -> float:
        op = facts.value(OPERATING_PROFIT, period)
        dep = facts.value(DEPRECIATION, period)
        return RO.nopat(op - dep, _as_fraction(facts.fact(TAX_PCT, period)))

    def invested_of(period: str) -> float:
        return (facts.value(BORROWINGS, period) + facts.value(EQUITY_CAPITAL, period)
                + facts.value(RESERVES, period))

    d_nopat = nopat_of(window[-1]) - nopat_of(window[0])
    d_invested = invested_of(window[-1]) - invested_of(window[0])
    if d_invested == 0:
        return None
    return d_nopat / d_invested, inputs, f"{window[0]}-{window[-1]}"


def cwip_persistence_years(facts: CompanyFacts, share_threshold: float) -> tuple[float, tuple[Fact, ...]]:
    """Consecutive recent years CWIP stayed above ``share_threshold`` of total assets.

    A deterministic stand-in for "how long has this block been sitting there?" — the real question the
    ageing-CWIP check asks (ADR-0006). Counting backwards from the latest period ends at the first year
    the block was *not* large, which is when it must have been commissioned or written off. Returns
    (years, input facts) so the caller can cite it; 0 years when CWIP is not large today.
    """
    used: list[Fact] = []
    years = 0
    for period in reversed(facts.periods):
        cwip, assets = facts.fact(CWIP, period), facts.fact(TOTAL_ASSETS, period)
        if cwip is None or assets is None or assets.value <= 0:
            break
        used += [cwip, assets]
        if cwip.value / assets.value <= share_threshold:
            break
        years += 1
    return float(years), tuple(used)
