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
CASH = "balance_sheet:Cash Equivalents"
RECEIVABLES = "balance_sheet:Trade Receivables"
INVENTORY = "balance_sheet:Inventories"

READ_METRICS: tuple[str, ...] = (
    SALES, PAT, OPERATING_PROFIT, DEPRECIATION, INTEREST, TAX_PCT, OTHER_INCOME, PBT,
    CFO, FCF, BORROWINGS, EQUITY_CAPITAL, RESERVES, CWIP, FIXED_ASSETS, TOTAL_ASSETS,
    CASH, RECEIVABLES, INVENTORY,
)


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
) -> CompanyFacts:
    """Read the known metric set for ``ticker`` as-of ``as_of``. Absent metrics are simply absent."""
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


def _cagr(first: float, last: float, years: int) -> float | None:
    if years <= 0 or first <= 0 or last <= 0:
        return None
    return (last / first) ** (1.0 / years) - 1.0


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
        borrow, eq, res, op, dep, tax = (f.value for f in invested_inputs)
        invested = borrow + eq + res
        nopat = RO.nopat(op - dep, tax / 100.0 if tax > 1 else tax)
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
        tax = facts.value(TAX_PCT, period)
        return RO.nopat(op - dep, tax / 100.0 if tax > 1 else tax)

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
