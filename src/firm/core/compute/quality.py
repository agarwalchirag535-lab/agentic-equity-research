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

from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Sequence


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


def cash_interest_consistency(
    interest_income: float, avg_cash: float, risk_free_rate: float, floor_ratio: float
) -> tuple[float, bool]:
    """'Is the cash real?' — implied yield on reported cash vs the risk-free rate.

    If ₹X of cash earns interest implying a yield far below risk-free, the cash may be fictitious,
    encumbered, or parked with related parties. Returns (implied_yield, is_flagged).
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
# Schedule III ageing schedules (ADR-0039). The tables are a legal disclosure, so every one of these
# questions is answerable from a primary source for any Indian company filing FY22 or later — and each
# is a question no summary feed can answer at all.
#
# All four return `(share, flagged)` rather than a bare bool: the published checklist prints the value it
# compared against the threshold (ADR-0021), so a reader can disagree with the policy number without
# re-running anything.
# --------------------------------------------------------------------------------------------------


def suspended_capex_share(
    suspended_cwip: float, total_cwip: float, limit: float
) -> tuple[float, bool]:
    """Share of capital work in progress in projects the company itself calls temporarily suspended.

    This is the ageing-CWIP question with the company's own label on it. `ageing_cwip` infers that
    capital is stuck by watching a balance stay large across years; the schedule states it outright, and
    a project that is suspended is by definition not becoming productive plant while the money sits at
    cost on the balance sheet.
    """
    if total_cwip <= 0:
        raise ValueError("total_cwip must be positive")
    share = suspended_cwip / total_cwip
    return share, share > limit


def ageing_tail_share(aged_beyond: float, total: float, limit: float) -> tuple[float, bool]:
    """Share of a receivable/payable/CWIP balance aged past a bucket boundary — the tail.

    A deteriorating book grows its tail before its total moves, which is why a stock-flow divergence
    check (receivables vs revenue) can pass while the collectable quality is already falling: the same
    ₹230cr of receivables is a different asset when a tenth of it is two years old.
    """
    if total <= 0:
        raise ValueError("total must be positive")
    share = aged_beyond / total
    return share, share > limit


def disputed_balance_share(
    disputed: float, credit_impaired: float, total: float, limit: float
) -> tuple[float, bool]:
    """Share of a balance the company has itself classified as disputed or credit-impaired.

    Both are admissions against interest, which is what makes them worth more than any ratio: the
    company is reporting that it does not expect to collect this at face value while still carrying it.
    """
    if total <= 0:
        raise ValueError("total must be positive")
    share = (disputed + credit_impaired) / total
    return share, share > limit


def finished_goods_buildup(
    finished_goods: float, gross_inventory: float,
    prior_finished_goods: float, prior_gross_inventory: float, limit: float,
) -> tuple[float, bool]:
    """Change in the finished-goods SHARE of inventory, in share points — goods the channel did not take.

    The share, not the level: a company that grows 30% and holds its mix constant is building stock to
    sell, while one whose mix tilts toward finished goods is producing into a market that is not clearing.
    The total inventory line moves identically in both cases, which is why the stock-flow check
    (`inventory_divergent`) cannot tell them apart and this one can.
    """
    if gross_inventory <= 0 or prior_gross_inventory <= 0:
        raise ValueError("gross inventory must be positive in both periods")
    shift = finished_goods / gross_inventory - prior_finished_goods / prior_gross_inventory
    return shift, shift > limit


def inventory_provision_absent(
    provision: float, gross_inventory: float, floor: float
) -> tuple[float, bool]:
    """Write-down carried against inventory, as a share of the gross book.

    A material book with no provision at all is the finding. Every real inventory contains something that
    will not sell at cost — spares for retired plant, a discontinued grade, a returned batch — so a company
    reporting exactly zero is either newly built or not looking. It is a MEDIUM signal precisely because
    the innocent explanations are common.
    """
    if gross_inventory <= 0:
        raise ValueError("gross_inventory must be positive")
    share = provision / gross_inventory
    return share, share < floor


def contingent_to_net_worth(contingent: float, net_worth: float, limit: float) -> tuple[float, bool]:
    """Claims not acknowledged as debt, against net worth — what a bad day in court would cost.

    These are disclosed precisely because the company does not expect to pay them. That is a judgement,
    and sizing it against net worth is how a reader decides whether to accept it: a claim worth 3% of
    equity is a footnote, and one worth 60% is the thesis.
    """
    if net_worth <= 0:
        raise ValueError("net_worth must be positive")
    ratio = contingent / net_worth
    return ratio, ratio > limit


def ageing_reconciliation_gap(schedule_total: float, statement_total: float) -> float:
    """|ageing schedule total − the statement line it ages| as a share of the statement line.

    Deliberately returns the gap and no verdict. A mismatch is far more likely to be OUR extraction than
    the company's arithmetic, so the caller reports it as an unavailable check naming a possible
    extraction fault — never as a finding against the company (the ADR-0025 rule).
    """
    if statement_total <= 0:
        raise ValueError("statement_total must be positive")
    return abs(schedule_total - statement_total) / statement_total


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
    except ZeroDivisionError as exc:  # noqa: F841
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
    provision_rate_curr: float, provision_rate_prior: float, min_rate_drop: float
) -> bool:
    """Loan-loss provision RATE cut materially year-on-year — profit may be reserve-driven, not real.

    Sezzle converted a quarterly loss to a profit partly by cutting provisions from 3.5% to 1.2% of
    underlying merchant sales. Flags when the rate falls by at least ``min_rate_drop`` (in rate points).
    """
    return (provision_rate_prior - provision_rate_curr) >= min_rate_drop


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
    #: Read off the Schedule III ageing schedules (ADR-0039) rather than inferred from balance-sheet
    #: snapshots. `stalled_capex` applies to any sector; the receivable/payable tails are meaningless
    #: for a lender and are raised only for NON_FINANCIAL, exactly like `receivables_divergent`.
    stalled_capex: bool = False
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
    receivables_ageing_tail: bool = False
    receivables_disputed: bool = False
    payables_ageing_tail: bool = False
    #: Read from the notes rather than the face of the statements (ADR-0040).
    finished_goods_buildup: bool = False
    inventory_provision_absent: bool = False
    # Model-specific signals (ADAPTIVE_FORENSICS §2) — fired only when the playbook selects them
    contract_asset_divergent: bool = False
    guarantees_heavy: bool = False
    contingent_liabilities_heavy: bool = False
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
    sector_class: SectorClass, metrics: ForensicMetrics, thresholds: ForensicThresholds
) -> ForensicScreenResult:
    """Aggregate deterministic signals into a Gate-B verdict.

    Hard-fail = any SEVERE flag, or two-or-more HIGH-severity flags. The LLM forensic_accountant
    (Stage 4/5) still holds an absolute veto downstream, but this deterministic screen is what runs on
    the ~400-company Gate-B subset (ADR-0005).
    """
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
        # Schedule III ageing tails (ADR-0039). `disputed` outranks the plain tail because it is the
        # company's own admission that a balance it still carries at value is contested.
        if metrics.receivables_disputed:
            flags.append(Flag("receivables_disputed", Severity.HIGH,
                              "material receivables the company itself calls disputed or credit-impaired"))
        if metrics.receivables_ageing_tail:
            flags.append(Flag("receivables_ageing_tail", Severity.MEDIUM,
                              "outsized share of the receivable book aged past a year — collection quality "
                              "falling ahead of the total"))
        if metrics.payables_ageing_tail:
            flags.append(Flag("payables_ageing_tail", Severity.MEDIUM,
                              "outsized share of trade payables overdue past a year — the company is "
                              "funding itself on its suppliers"))
        # Inventory composition (ADR-0040) — meaningless for a lender, like every other stock signal here.
        if metrics.finished_goods_buildup:
            flags.append(Flag("finished_goods_buildup", Severity.MEDIUM,
                              "inventory mix tilting toward finished goods — production the channel is "
                              "not clearing, which the total inventory line cannot show"))
        if metrics.inventory_provision_absent:
            flags.append(Flag("inventory_provision_absent", Severity.MEDIUM,
                              "a material inventory book carried with no write-down at all — every real "
                              "inventory contains something that will not sell at cost"))
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
    if metrics.stalled_capex:
        flags.append(Flag("stalled_capex", Severity.MEDIUM,
                          "material capital work in progress sits in projects the company reports as "
                          "temporarily suspended — capex that is not becoming productive plant"))

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
    if metrics.contingent_liabilities_heavy:
        flags.append(Flag("contingent_liabilities_heavy", Severity.MEDIUM,
                          "claims not acknowledged as debt are large against net worth — the company's "
                          "judgement that it will not pay them is load-bearing"))
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
