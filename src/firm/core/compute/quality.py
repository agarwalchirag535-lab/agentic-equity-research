"""Forensic / earnings-quality metrics — deterministic Gate-B kill set (SPEC §5, ADRs 0002/0003/0005/0006).

Law 1: pure Python, no LLM, no network. Every policy threshold is passed in explicitly.

Design decisions baked in here:
- ADR-0002: forensic models branch by ``sector_class``. Beneish/Piotroski/accruals are suppressed for
  FINANCIAL issuers (banks/NBFCs/insurers) and lender-specific checks are used instead.
- ADR-0003: Benford's Law is intentionally NOT implemented as a load-bearing signal.
- ADR-0005: this whole module is deterministic — Gate B never calls an LLM.
- ADR-0006: "cash-reality" checks — the sharpest 'is the cash actually there / does the cash flow
  contradict the P&L' tests — are first-class here.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum, IntEnum


class SectorClass(str, Enum):
    FINANCIAL = "FINANCIAL"
    NON_FINANCIAL = "NON_FINANCIAL"


class Severity(IntEnum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    SEVERE = 4  # any SEVERE flag is an automatic forensic hard-fail


# --------------------------------------------------------------------------------------------------
# Cash-reality checks (ADR-0006) — the project owner's headline concern.
# --------------------------------------------------------------------------------------------------


def accrual_ratio(net_income: float, cfo: float, avg_total_assets: float) -> float:
    """Cash-flow-approach accrual ratio = (Net Income − CFO) / avg total assets.

    High positive value = earnings are largely accrual-based (low quality, mean-reversion risk).
    """
    if avg_total_assets <= 0:
        raise ValueError("avg_total_assets must be positive")
    return (net_income - cfo) / avg_total_assets


def cfo_pat_ratio(cfo: float, pat: float) -> float:
    """Single-year CFO / PAT. Below ~0.7 persistently = earnings not converting to cash."""
    if pat == 0:
        raise ValueError("pat must be non-zero")
    return cfo / pat


def cumulative_cfo_pat_ratio(cfo_series: Sequence[float], pat_series: Sequence[float]) -> float:
    """Σ CFO / Σ PAT over the full history — 'has a decade of profit ever become cash?'."""
    if len(cfo_series) != len(pat_series):
        raise ValueError("series length mismatch")
    if len(cfo_series) == 0:
        raise ValueError("empty series")
    total_pat = sum(pat_series)
    if total_pat == 0:
        raise ValueError("cumulative pat must be non-zero")
    return sum(cfo_series) / total_pat


@dataclass(frozen=True)
class FlowOverStock:
    """A flow divided by a stock that MOVED during the period — a band, not a number (ADR-0059).

    THE DEFECT THIS EXISTS FOR. Every rate in this library of the form "a year of flow over an average
    balance" — implied cash yield, cost of debt, credit cost — is computed from two endpoints and then
    compared to a threshold as though it were measured. It is not measured. Interest accrues against the
    balance held on every day of the year, and an annual balance sheet reports two of those 365 days.

    Alkyl Amines FY23 is the worked example. Cash and bank balances fell from ₹62.57cr to ₹18.23cr and
    the company earned ₹1.03cr of interest. The two-point mean says the yield was 2.55%, which is below
    the 2.60% floor, which is a SEVERE flag, which is a HARD_FAIL on a company with no fraud, no
    restatement and no governance event. But the same two endpoints are equally consistent with the
    drawdown happening in April — average balance ₹18cr, yield 5.6%, entirely ordinary. Nothing in the
    filing distinguishes those two stories, and the check picked one of them without saying so.

    WHAT THE BAND IS, AND WHAT IT IS NOT. `low` and `high` are the rates implied if the balance sat at
    its higher endpoint all year and at its lower endpoint all year. That is not a proof of containment:
    a balance can excursion outside both endpoints mid-year and no annual filing would show it. It is
    the weaker and sufficient claim — **these are ordinary timing stories the same two endpoints tell,
    so a threshold claim that fails on any of them has not been established.** To assert "the yield is
    below the floor" the whole band must be below the floor; to assert "the rate is above the ceiling"
    the whole band must be above it.

    Where the endpoints are close the band collapses and nothing changes: Alkyl FY26 moved 1% and reads
    7.73%–7.82%. Where the endpoints are far apart the band is the honest width of the firm's ignorance:
    FY25 moved +550% and reads 4.03%–26.20%, a "measurement" spanning a factor of six.
    """

    #: The conventional estimate: flow / mean(opening, closing). Kept because it is what a reader of the
    #: statements would compute, and what every report has printed until now.
    point: float
    #: The lower end of the band: the rate against whichever endpoint makes it smaller. For a positive
    #: flow that is the HIGHER balance; for a negative one (accruals run both ways) it is the lower, so
    #: the two are ordered rather than assigned by endpoint.
    low: float
    #: The upper end of the band, by the same ordering.
    high: float
    opening: float
    closing: float

    @property
    def drift(self) -> float:
        """How far the endpoints are apart, as a fraction of the larger — 0.0 when the stock held still.

        This is the width of the band expressed on the inputs rather than the output, and it is what a
        report should print next to any of these rates: `drift` 0.01 means the number means something,
        `drift` 0.85 means it does not.
        """
        return abs(self.closing - self.opening) / max(self.opening, self.closing)

    def below(self, floor: float) -> bool:
        """Is the rate below `floor` under EVERY timing story the endpoints tell?"""
        return self.high < floor

    def above(self, ceiling: float) -> bool:
        """Is the rate above `ceiling` under EVERY timing story the endpoints tell?"""
        return self.low > ceiling

    def outside(self, limit: float) -> bool:
        """Is |rate| above `limit` under EVERY timing story? The two-sided claim (accruals run both ways)."""
        return self.above(limit) or self.below(-limit)

    def indeterminate_below(self, floor: float) -> bool:
        """The conventional estimate is below `floor` but the band is not — the artefact case.

        Distinguished from a plain "not flagged" because the two deserve different words in a report: a
        rate of 7.8% is a finding of nothing, and a rate of "somewhere between 1.6% and 5.6%" against a
        2.6% floor is a question the firm cannot answer with what it read.
        """
        return self.point < floor <= self.high


def flow_over_stock(flow: float, opening: float, closing: float) -> FlowOverStock:
    """A year's flow over a balance observed only at its two endpoints, as the band they support.

    Both endpoints must be positive: a rate against a balance that was zero at either end is not a wide
    measurement, it is a different question (money that arrived, or left, entirely within the year).
    """
    if opening <= 0 or closing <= 0:
        raise ValueError("both endpoints must be positive to bound the average balance")
    ends = (flow / opening, flow / closing)
    return FlowOverStock(
        point=flow / ((opening + closing) / 2.0),
        low=min(ends),
        high=max(ends),
        opening=opening,
        closing=closing,
    )


def cash_interest_consistency(
    interest_income: float, avg_cash: float, risk_free_rate: float, floor_ratio: float
) -> tuple[float, bool]:
    """'Is the cash real?' — implied yield on reported cash vs the risk-free rate.

    If ₹X of cash earns interest implying a yield far below risk-free, the cash may be fictitious,
    encumbered, or parked with related parties. Returns (implied_yield, is_flagged).

    A SINGLE AVERAGE BALANCE IS ALL THIS CAN BE TOLD, so it answers on the point estimate. Where the two
    endpoints are available — which is everywhere the filing was read rather than summarised — the
    caller should bound the claim with `flow_over_stock` instead; see `FlowOverStock` for why the point
    estimate produced this library's only live false positive.
    """
    if avg_cash <= 0:
        raise ValueError("avg_cash must be positive")
    implied_yield = interest_income / avg_cash
    return implied_yield, implied_yield < floor_ratio * risk_free_rate


def cash_debt_paradox(
    cash: float,
    total_assets: float,
    gross_debt: float,
    cost_of_debt: float,
    large_cash_ratio: float,
    high_cost_rate: float,
) -> bool:
    """Large gross cash held WHILE paying high-cost debt — 'why borrow at 12% on ₹500cr of cash?'."""
    if total_assets <= 0:
        raise ValueError("total_assets must be positive")
    return (
        cash / total_assets > large_cash_ratio
        and gross_debt > 0
        and cost_of_debt > high_cost_rate
    )


def ageing_cwip_flag(
    cwip: float,
    total_assets: float,
    years_since_commissioned: float,
    cwip_ratio_threshold: float,
    years_threshold: float,
) -> bool:
    """Capital-WIP that is large and not commissioning into PP&E — capex-siphoning tell."""
    if total_assets <= 0:
        raise ValueError("total_assets must be positive")
    return (
        cwip / total_assets > cwip_ratio_threshold
        and years_since_commissioned >= years_threshold
    )


# --------------------------------------------------------------------------------------------------
# Beneish M-score (8-index) — NON-financials only (ADR-0002).
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class BeneishYear:
    sales: float
    cogs: float
    receivables: float
    current_assets: float
    ppe_net: float
    total_assets: float
    depreciation: float
    sga: float
    income_continuing_ops: float
    cfo: float
    current_liabilities: float
    long_term_debt: float


def beneish_m_score(prior: BeneishYear, current: BeneishYear) -> float:
    """Beneish (1999) 8-variable M-score. M > −1.78 => elevated manipulation probability.

    Raises ValueError if any required denominator is zero (caller must supply clean inputs).
    """
    t, p = current, prior
    try:
        gm_t = (t.sales - t.cogs) / t.sales
        gm_p = (p.sales - p.cogs) / p.sales
        dsri = (t.receivables / t.sales) / (p.receivables / p.sales)
        gmi = gm_p / gm_t
        aqi = (1 - (t.current_assets + t.ppe_net) / t.total_assets) / (
            1 - (p.current_assets + p.ppe_net) / p.total_assets
        )
        sgi = t.sales / p.sales
        depi = (p.depreciation / (p.depreciation + p.ppe_net)) / (
            t.depreciation / (t.depreciation + t.ppe_net)
        )
        sgai = (t.sga / t.sales) / (p.sga / p.sales)
        lvgi = ((t.long_term_debt + t.current_liabilities) / t.total_assets) / (
            (p.long_term_debt + p.current_liabilities) / p.total_assets
        )
        tata = (t.income_continuing_ops - t.cfo) / t.total_assets
    except ZeroDivisionError as exc:
        raise ValueError("beneish_m_score: a required denominator was zero") from exc

    return (
        -4.84
        + 0.920 * dsri
        + 0.528 * gmi
        + 0.404 * aqi
        + 0.892 * sgi
        + 0.115 * depi
        - 0.172 * sgai
        + 4.679 * tata
        - 0.327 * lvgi
    )


# --------------------------------------------------------------------------------------------------
# Lender-specific forensic checks — FINANCIAL issuers (ADR-0002).
# --------------------------------------------------------------------------------------------------


def gnpa_drift_flag(gnpa_ratio_current: float, gnpa_ratio_prior: float, threshold: float) -> bool:
    """Year-on-year rise in the gross-NPA ratio above ``threshold``."""
    return (gnpa_ratio_current - gnpa_ratio_prior) > threshold


def provision_coverage_flag(provisions: float, gnpa_amount: float, min_pcr: float) -> bool:
    """Provision coverage ratio below ``min_pcr``. Zero GNPA => not flagged."""
    if gnpa_amount <= 0:
        return False
    return (provisions / gnpa_amount) < min_pcr


def restructured_book_flag(restructured: float, gross_advances: float, threshold: float) -> bool:
    """Restructured advances above ``threshold`` share of the book."""
    if gross_advances <= 0:
        raise ValueError("gross_advances must be positive")
    return (restructured / gross_advances) > threshold


# --------------------------------------------------------------------------------------------------
# Originate-to-sell / lender earnings-quality checks (FORENSIC_METHODOLOGY §7 P7; proposed ADR).
#
# These apply by BUSINESS MODEL, not by ``sector_class`` label: a company that originates and sells
# loans (or carries a loan/receivable book) gets these checks even if it calls itself a "dealer".
# The Carvana lesson: "It's actually more of a subprime finance business than a car dealership."
# All thresholds are passed in explicitly (Law 1 / no magic numbers).
# --------------------------------------------------------------------------------------------------


def gain_on_sale_reliance(
    gain_on_sale: float, net_income: float, max_ratio: float
) -> tuple[float, bool]:
    """Reported profit's dependence on discretionary gain-on-loan-sale. Carvana: gain-on-sale = 2.2x NI.

    A high ratio means earnings rest on a non-recurring, timing-manipulable sale channel rather than on
    operations. If ``net_income <= 0`` but there is a positive gain on sale, reliance is effectively
    infinite — without the sale the company is loss-making — which is itself the signal, so it flags.
    Returns (ratio, is_flagged).
    """
    if net_income <= 0:
        return (float("inf"), True) if gain_on_sale > 0 else (0.0, False)
    ratio = gain_on_sale / net_income
    return ratio, ratio > max_ratio


def provision_rate(provisions: float, gross_loans: float) -> float:
    """Loan-loss provisions as a share of the gross loan book."""
    if gross_loans <= 0:
        raise ValueError("gross_loans must be positive")
    return provisions / gross_loans


def provision_book_divergence(
    provisions_curr: float,
    provisions_prior: float,
    loans_curr: float,
    loans_prior: float,
    max_gap: float,
) -> tuple[float, float, bool]:
    """Provision growth vs loan-book growth. Sezzle: provisions +130% while the book grew only +6%.

    A large divergence in EITHER direction is a tell:
      provision growth >> book growth  → credit deteriorating / prior under-provisioning catch-up;
      provision growth << book growth  → reserves not keeping pace with a growing (riskier) book.
    Returns (provision_growth, book_growth, is_flagged).
    """
    if provisions_prior <= 0 or loans_prior <= 0:
        raise ValueError("prior provisions and loans must be positive")
    prov_growth = provisions_curr / provisions_prior - 1.0
    book_growth = loans_curr / loans_prior - 1.0
    return prov_growth, book_growth, abs(prov_growth - book_growth) > max_gap


def reserve_suppression_flag(
    provision_rate_curr: float, provision_rate_prior: float, min_rate_drop: float,
    *,
    impaired_share_curr: float | None = None,
    impaired_share_prior: float | None = None,
    stress_relief_min_drop: float | None = None,
) -> bool:
    """Loan-loss provision RATE cut materially year-on-year — profit may be reserve-driven, not real.

    Sezzle converted a quarterly loss to a profit partly by cutting provisions from 3.5% to 1.2% of
    underlying merchant sales — INTO RISING DELINQUENCY, which is the half of the tell this function
    could not see until the staging notes became readable (ADR-0056/0058). A rate cut while the
    impaired share of the book FELL materially is a reserve *release* — the honest accounting of a
    book that got better — and the golden set's hard_recovery case (CreditAccess FY26: credit cost
    7.95% -> 6.36% while Stage-3 fell 4.79% -> 3.18%) is a clean lender this flag was punishing for
    fixing its book. Flags a rate cut of at least ``min_rate_drop`` UNLESS both impaired shares are
    supplied and their fall meets ``stress_relief_min_drop``; with no staging data the cut alone still
    flags, which is the conservative direction and the only one Sezzle-era inputs allow.
    """
    if (provision_rate_prior - provision_rate_curr) < min_rate_drop:
        return False
    stress_relieved = (impaired_share_curr is not None and impaired_share_prior is not None
                       and stress_relief_min_drop is not None
                       and (impaired_share_prior - impaired_share_curr) >= stress_relief_min_drop)
    return not stress_relieved


def held_for_sale_reserve_flag(
    loans_on_book: float,
    loss_allowance: float,
    loans_on_book_prior: float,
    min_allowance_ratio: float,
) -> bool:
    """Growing on-book loan balance carried with ~zero loss allowance (e.g. 'held for sale' avoids CECL).

    Carvana's on-balance-sheet loans grew ~50% to $553M while it booked no loss reserves at origination.
    Flags when the allowance is below ``min_allowance_ratio`` of the book AND the book is growing.
    """
    if loans_on_book <= 0:
        return False
    return (
        (loss_allowance / loans_on_book) < min_allowance_ratio
        and loans_on_book > loans_on_book_prior
    )


# --------------------------------------------------------------------------------------------------
# Universal checks named in SPEC §5 but previously uncoded (ADAPTIVE_FORENSICS §4 step 1).
# Thresholds are provisional until the Phase-6 golden set calibrates them per business model.
# --------------------------------------------------------------------------------------------------


def stock_flow_divergence(
    stock_curr: float, stock_prior: float, flow_curr: float, flow_prior: float, max_gap: float
) -> tuple[float, float, bool]:
    """A balance-sheet stock growing much faster than the flow that feeds it (SPEC §5).

    Receivables vs revenue: the classic channel-stuffing / fictitious-sales tell. Inventory vs revenue:
    valuation-parking / obsolescence tell. Flags only when the STOCK outruns the flow by more than
    ``max_gap`` (a stock shrinking faster than the flow is destocking, not manipulation).
    Returns (stock_growth, flow_growth, is_flagged).
    """
    if stock_prior <= 0 or flow_prior <= 0:
        raise ValueError("prior stock and flow must be positive")
    stock_g = stock_curr / stock_prior - 1.0
    flow_g = flow_curr / flow_prior - 1.0
    return stock_g, flow_g, (stock_g - flow_g) > max_gap


def other_income_share(other_income: float, pbt: float, max_share: float) -> tuple[float, bool]:
    """Other income as a share of PBT (SPEC §5) — how much of 'profit' is not the business.

    If PBT ≤ 0 while other income is positive, the operating business is loss-making and the reported
    picture rests entirely on non-operating income — effectively infinite dependence, so it flags
    (same convention as `gain_on_sale_reliance`). Returns (share, is_flagged).
    """
    if pbt <= 0:
        return (float("inf"), True) if other_income > 0 else (0.0, False)
    share = other_income / pbt
    return share, share > max_share


def revenue_inflation_tell(
    revenue_growth: float, gross_margin: float, min_growth: float, max_margin: float
) -> bool:
    """Trader/distributor signature: revenue exploding on a near-zero gross margin.

    Gross-vs-net booking (agency revenue recognised as principal) and circular trading both manufacture
    scale without profit — the tell is the *combination*: growth ≥ ``min_growth`` while gross margin ≤
    ``max_margin``. Either alone is unremarkable; together they demand an explanation.
    """
    return revenue_growth >= min_growth and gross_margin <= max_margin


# --------------------------------------------------------------------------------------------------
# Model-specific checks (ADAPTIVE_FORENSICS §2 matrix). Selected by the playbook, never fired blindly.
# All thresholds provisional until Phase-6 golden-set calibration.
# --------------------------------------------------------------------------------------------------


def contract_asset_divergence(
    contract_assets_curr: float,
    contract_assets_prior: float,
    revenue_curr: float,
    revenue_prior: float,
    max_gap: float,
) -> tuple[float, float, bool]:
    """EPC/infra: unbilled revenue (contract assets) outrunning billed revenue.

    Percentage-of-completion accounting lets a contractor book revenue before billing it. When contract
    assets grow far faster than revenue, profit is increasingly an estimate rather than an invoice.
    Thin wrapper over `stock_flow_divergence` so the EPC playbook has a named check.
    """
    return stock_flow_divergence(
        contract_assets_curr, contract_assets_prior, revenue_curr, revenue_prior, max_gap
    )


def guarantees_to_net_worth(
    guarantees: float, net_worth: float, max_ratio: float
) -> tuple[float, bool]:
    """Off-balance-sheet guarantees (typically to SPVs/subsidiaries) as a multiple of net worth.

    The EPC/infra failure pattern: the parent looks solvent while guaranteeing SPV debt that can be
    called. A ratio above ``max_ratio`` means the contingent exposure is material against equity.
    Non-positive net worth with guarantees outstanding is unbounded exposure → flags.
    """
    if net_worth <= 0:
        return (float("inf"), True) if guarantees > 0 else (0.0, False)
    ratio = guarantees / net_worth
    return ratio, ratio > max_ratio


def capitalised_cost_share(
    capitalised: float, total_spend: float, max_share: float
) -> tuple[float, bool]:
    """Share of a cost pool capitalised rather than expensed (R&D for pharma, dev cost for platforms).

    Capitalising what peers expense moves cost off the P&L into the balance sheet, flattering current
    margins and deferring the reckoning to an impairment. Returns (share, is_flagged).
    """
    if total_spend <= 0:
        raise ValueError("total_spend must be positive")
    share = capitalised / total_spend
    return share, share > max_share


def adjusted_ebitda_bridge_gap(
    adjusted_ebitda: float, statutory_ebitda: float, revenue: float, max_gap_of_revenue: float
) -> tuple[float, bool]:
    """Platform/new-age: the gap between "adjusted" EBITDA and the statutory figure, scaled by revenue.

    Every add-back is a claim that a real cost is not really a cost. Scaling by revenue (not by EBITDA,
    which is often near zero or negative) keeps the measure stable for loss-making companies.
    Returns (gap_as_share_of_revenue, is_flagged).
    """
    if revenue <= 0:
        raise ValueError("revenue must be positive")
    gap = (adjusted_ebitda - statutory_ebitda) / revenue
    return gap, gap > max_gap_of_revenue


def promoter_loan_share(
    loans_to_promoters: float, total_loans_advances: float, max_share: float
) -> tuple[float, bool]:
    """Loans/advances to promoters, directors and KMP as a share of the total book.

    Schedule III (2021) forces this disclosure precisely because it is a classic siphoning channel.
    Zero total advances is not a flag — there is nothing to divert. Returns (share, is_flagged).
    """
    if total_loans_advances <= 0:
        return 0.0, False
    share = loans_to_promoters / total_loans_advances
    return share, share > max_share


def disclosure_completeness(
    required_fields: Sequence[str], present_fields: Sequence[str]
) -> tuple[list[str], bool]:
    """Missing legally-required disclosure is itself a forensic signal (project-owner directive).

    For a listed company, all mandated data is public by law; an unexplained gap raises the question
    "what is being hidden?" rather than being silently skipped. Returns (sorted missing fields, flag).
    """
    missing = sorted(set(required_fields) - set(present_fields))
    return missing, len(missing) > 0


# --------------------------------------------------------------------------------------------------
# Aggregator — the deterministic Gate-B verdict (ADR-0005).
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Flag:
    name: str
    severity: Severity
    detail: str


class ForensicVerdict(str, Enum):
    PASS = "PASS"
    REVIEW = "REVIEW"
    HARD_FAIL = "HARD_FAIL"
    #: Nothing was actually evaluated, so no verdict about the COMPANY exists (EVAL-1, ADR-0058). Every
    #: `ForensicMetrics` field defaults to "not evaluated", which means an empty read produced zero
    #: flags and the screen said PASS — the exact boolean ambiguity the checks layer fixed long ago
    #: ("a default cannot tell you a check never ran"), surviving at the one boundary where the verdict
    #: is minted. PASS is a claim of looking and finding nothing; this is not having looked.
    INSUFFICIENT = "INSUFFICIENT"


@dataclass(frozen=True)
class ForensicMetrics:
    # NON_FINANCIAL signals (None when not applicable / not computed)
    cfo_pat: float | None = None
    cumulative_cfo_pat: float | None = None
    accrual_ratio: float | None = None
    beneish_m: float | None = None
    # FINANCIAL signals
    gnpa_drift: bool = False
    provision_coverage_low: bool = False
    restructured_book_high: bool = False
    # Cash-reality signals (apply to all)
    cash_interest_inconsistent: bool = False
    cash_debt_paradox: bool = False
    ageing_cwip: bool = False
    # Originate-to-sell / lender signals (apply by business model, any sector)
    gain_on_sale_reliant: bool = False
    provision_book_divergent: bool = False
    reserve_suppression: bool = False
    held_for_sale_no_reserve: bool = False
    # Disclosure-gap signal (missing legally-public data is itself a flag — project-owner directive)
    disclosure_gap: bool = False
    # Universal SPEC §5 signals (apply to any model; suppressed for FINANCIAL where meaningless)
    receivables_divergent: bool = False
    inventory_divergent: bool = False
    other_income_heavy: bool = False
    revenue_inflation: bool = False
    # Model-specific signals (ADAPTIVE_FORENSICS §2) — fired only when the playbook selects them
    contract_asset_divergent: bool = False
    guarantees_heavy: bool = False
    capitalised_cost_heavy: bool = False
    adjusted_ebitda_gap: bool = False
    promoter_lending: bool = False


@dataclass(frozen=True)
class ForensicThresholds:
    cfo_pat_min: float
    cumulative_cfo_pat_min: float
    sloan_accrual_flag: float
    beneish_m_threshold: float


@dataclass(frozen=True)
class ForensicScreenResult:
    verdict: ForensicVerdict
    hard_fail: bool
    flags: list[Flag] = field(default_factory=list)


def forensic_screen(
    sector_class: SectorClass, metrics: ForensicMetrics, thresholds: ForensicThresholds,
    *, checks_ran: int | None = None, checks_expected: int | None = None,
    min_ran_share: float | None = None,
) -> ForensicScreenResult:
    """Aggregate deterministic signals into a Gate-B verdict.

    Hard-fail = any SEVERE flag, or two-or-more HIGH-severity flags. The LLM forensic_accountant
    (Stage 4/5) still holds an absolute veto downstream, but this deterministic screen is what runs on
    the ~400-company Gate-B subset (ADR-0005).

    ``checks_ran`` is how many checks actually EVALUATED (PASS or FLAG) to produce ``metrics``
    (EVAL-1, ADR-0058): with zero, the screen returns INSUFFICIENT rather than mistaking an empty read
    for a clean company. The golden set then showed zero is not enough: on PC Jeweller FY21 the
    pipeline read one check in ten — a text-section scan — and the screen minted PASS from that
    sliver. So the screen also refuses when the RAN share of ``checks_expected`` falls below
    ``min_ran_share`` (policy from `config/thresholds.yaml:forensic.screen_min_ran_share`, provisional
    until the golden set calibrates it). A verdict about a company is a claim about how much was
    looked at, and the screen now carries that claim itself instead of leaning on the ladder above it.
    ``None`` on any of the three preserves the legacy contract for callers that assembled ``metrics``
    by hand and know their own evidence.
    """
    if checks_ran == 0:
        return ForensicScreenResult(verdict=ForensicVerdict.INSUFFICIENT, hard_fail=False, flags=[])
    if (checks_ran is not None and checks_expected and min_ran_share is not None
            and checks_ran / checks_expected < min_ran_share):
        return ForensicScreenResult(verdict=ForensicVerdict.INSUFFICIENT, hard_fail=False, flags=[])
    flags: list[Flag] = []

    if sector_class is SectorClass.NON_FINANCIAL:
        if metrics.cumulative_cfo_pat is not None and metrics.cumulative_cfo_pat < thresholds.cumulative_cfo_pat_min:
            flags.append(Flag("cumulative_cfo_pat_low", Severity.SEVERE,
                              f"ΣCFO/ΣPAT {metrics.cumulative_cfo_pat:.2f} < {thresholds.cumulative_cfo_pat_min:.2f}"))
        if metrics.cfo_pat is not None and metrics.cfo_pat < thresholds.cfo_pat_min:
            flags.append(Flag("cfo_pat_low", Severity.HIGH,
                              f"CFO/PAT {metrics.cfo_pat:.2f} < {thresholds.cfo_pat_min:.2f}"))
        if metrics.accrual_ratio is not None and abs(metrics.accrual_ratio) > thresholds.sloan_accrual_flag:
            flags.append(Flag("high_accruals", Severity.MEDIUM,
                              f"|accruals| {abs(metrics.accrual_ratio):.2f} > {thresholds.sloan_accrual_flag:.2f}"))
        if metrics.beneish_m is not None and metrics.beneish_m > thresholds.beneish_m_threshold:
            flags.append(Flag("beneish_manipulator", Severity.HIGH,
                              f"M-score {metrics.beneish_m:.2f} > {thresholds.beneish_m_threshold:.2f}"))
        # Universal SPEC §5 tells (meaningless for lenders — no trade receivables/inventory):
        if metrics.receivables_divergent:
            flags.append(Flag("receivables_divergent", Severity.HIGH,
                              "receivables outrunning revenue — channel-stuffing / fictitious-sales tell"))
        if metrics.inventory_divergent:
            flags.append(Flag("inventory_divergent", Severity.MEDIUM,
                              "inventory outrunning revenue — valuation-parking / obsolescence tell"))
        if metrics.other_income_heavy:
            flags.append(Flag("other_income_heavy", Severity.MEDIUM,
                              "other income is an outsized share of PBT — profit is not the business"))
        if metrics.revenue_inflation:
            flags.append(Flag("revenue_inflation", Severity.HIGH,
                              "revenue exploding on near-zero gross margin — gross-vs-net / circular tell"))
    else:  # FINANCIAL — Beneish/Piotroski/accruals suppressed (ADR-0002)
        if metrics.gnpa_drift:
            flags.append(Flag("gnpa_drift", Severity.HIGH, "GNPA ratio rising beyond threshold"))
        if metrics.provision_coverage_low:
            flags.append(Flag("provision_coverage_low", Severity.HIGH, "PCR below floor"))
        if metrics.restructured_book_high:
            flags.append(Flag("restructured_book_high", Severity.MEDIUM, "restructured book elevated"))

    # Cash-reality checks apply regardless of sector.
    if metrics.cash_interest_inconsistent:
        flags.append(Flag("cash_interest_inconsistent", Severity.SEVERE,
                          "implied cash yield far below risk-free — is the cash real?"))
    if metrics.cash_debt_paradox:
        flags.append(Flag("cash_debt_paradox", Severity.HIGH,
                          "large cash held while paying high-cost debt"))
    if metrics.ageing_cwip:
        flags.append(Flag("ageing_cwip", Severity.MEDIUM, "large CWIP not commissioning to PP&E"))

    # Originate-to-sell / lender signals — model-based, not sector-label-based (a "dealer" can be a
    # lender). These apply regardless of sector_class (FORENSIC_METHODOLOGY §7).
    if metrics.gain_on_sale_reliant:
        flags.append(Flag("gain_on_sale_reliant", Severity.HIGH,
                          "reported profit heavily dependent on discretionary loan-sale gains"))
    if metrics.reserve_suppression:
        flags.append(Flag("reserve_suppression", Severity.HIGH,
                          "loan-loss provision rate cut materially — profit may be reserve-driven"))
    if metrics.held_for_sale_no_reserve:
        flags.append(Flag("held_for_sale_no_reserve", Severity.HIGH,
                          "growing on-book loan balance carried with ~zero loss allowance"))
    if metrics.provision_book_divergent:
        flags.append(Flag("provision_book_divergent", Severity.MEDIUM,
                          "loan-loss provisions diverging sharply from loan-book growth"))

    # Model-specific signals (ADAPTIVE_FORENSICS §2) — the playbook decides which of these were run.
    if metrics.promoter_lending:
        flags.append(Flag("promoter_lending", Severity.SEVERE,
                          "material loans/advances to promoters, directors or KMP — siphoning channel"))
    if metrics.guarantees_heavy:
        flags.append(Flag("guarantees_heavy", Severity.HIGH,
                          "off-balance-sheet guarantees large versus net worth"))
    if metrics.contract_asset_divergent:
        flags.append(Flag("contract_asset_divergent", Severity.HIGH,
                          "unbilled revenue outrunning billed revenue — profit is an estimate"))
    if metrics.capitalised_cost_heavy:
        flags.append(Flag("capitalised_cost_heavy", Severity.MEDIUM,
                          "outsized share of costs capitalised rather than expensed"))
    if metrics.adjusted_ebitda_gap:
        flags.append(Flag("adjusted_ebitda_gap", Severity.MEDIUM,
                          "large gap between 'adjusted' and statutory EBITDA"))

    # Disclosure gap — missing legally-public data is a signal, never a silent skip (owner directive).
    if metrics.disclosure_gap:
        flags.append(Flag("disclosure_gap", Severity.MEDIUM,
                          "legally-required disclosure missing/unavailable — unexplained opacity"))

    any_severe = any(f.severity is Severity.SEVERE for f in flags)
    high_or_worse = sum(1 for f in flags if f.severity >= Severity.HIGH)
    hard_fail = any_severe or high_or_worse >= 2

    if hard_fail:
        verdict = ForensicVerdict.HARD_FAIL
    elif flags:
        verdict = ForensicVerdict.REVIEW
    else:
        verdict = ForensicVerdict.PASS
    return ForensicScreenResult(verdict=verdict, hard_fail=hard_fail, flags=flags)
