"""Pydantic output contracts for all 14 agents (Law 4). Each extends AgentOutputBase.

Prose always lives in the inherited `narrative` field; the typed fields below are what downstream agents
actually read. Financial numbers in these fields must originate from `core/compute` (Law 1).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from firm.schemas._base import AgentOutputBase


# ---- Tier 1: top-down --------------------------------------------------------------------------
class SectorScore(BaseModel):
    sector: str
    tailwind_score: float = Field(ge=-1.0, le=1.0)
    horizon_years: int
    falsifier: str


class MacroStrategistOutput(AgentOutputBase):
    cycle_position: str
    sector_scores: list[SectorScore] = Field(default_factory=list)


class SectorAnalystOutput(AgentOutputBase):
    profit_pool: str
    pricing_power_holders: list[str] = Field(default_factory=list)
    structural_vs_cyclical: str
    kpi_set: list[str] = Field(default_factory=list)


# ---- Tier 2: company deep dive -----------------------------------------------------------------
class BusinessAnalystOutput(AgentOutputBase):
    what_it_does: str
    moat: str | None = None
    customer_concentration: float | None = None
    national_relevance: bool = False


class UnitEconomicsOutput(AgentOutputBase):
    unit_definition: str
    # Optional, not int-with-0: "0 units" meaning unknown is the ForensicMetrics boolean defect in
    # integer form — a reader cannot tell "counted, and zero" from "never counted". Unknown is None.
    units_today: int | None = None
    units_plausible_in_7y: int | None = None
    contribution_margin_per_unit: float | None = None
    payback_years: float | None = None


class FinancialStatementOutput(AgentOutputBase):
    incremental_roic: float | None = None
    cfo_to_ebitda: float | None = None
    fcf_to_pat: float | None = None
    working_capital_days: float | None = None


class ForensicAccountantOutput(AgentOutputBase):
    verdict: str  # PASS | REVIEW | HARD_FAIL
    flags: list[str] = Field(default_factory=list)
    veto: bool = False  # absolute veto — no other agent can overturn a forensic hard-fail


class ManagementAnalystOutput(AgentOutputBase):
    promise_delivery_score: float | None = Field(default=None, ge=0.0, le=1.0)
    capital_allocation_grade: str | None = None
    promoter_pledge_pct: float | None = None


class TranscriptAnalystOutput(AgentOutputBase):
    guidance_drift: str
    dodged_questions: list[str] = Field(default_factory=list)
    tone_trace: list[str] = Field(default_factory=list)


class OwnershipFlowsOutput(AgentOutputBase):
    smart_money_score: float | None = None  # quality-weighted (ADR-0007)
    days_to_exit_at_20pct_adv: float | None = None
    institutional_absence_read: str | None = None  # undiscovered vs looked-and-passed


# ---- Tier 3: judgment --------------------------------------------------------------------------
class ScenarioLine(BaseModel):
    name: str
    probability: float = Field(ge=0.0, le=1.0)
    return_multiple: float


class ValuationModelerOutput(AgentOutputBase):
    reverse_dcf_implied_growth: float | None = None
    base_case_value_per_share: float | None = None
    scenarios: list[ScenarioLine] = Field(default_factory=list)


class ThesisSynthesizerOutput(AgentOutputBase):
    return_multiple_if: str
    three_load_bearing_assumptions: list[str] = Field(default_factory=list)
    feasibility_verdict: str  # from §6.3 gate


class RedTeamOutput(AgentOutputBase):
    bear_case: str
    base_rate_of_failure: float | None = None
    kill_criteria: list[str] = Field(default_factory=list)  # a thesis without these does not ship


class PortfolioManagerOutput(AgentOutputBase):
    position_size_pct: float | None = None
    expectancy: float | None = None
    staged_entry: str | None = None


# ---- Tier 4: meta ------------------------------------------------------------------------------
class PostMortemOutput(AgentOutputBase):
    resolved_predictions: int = 0
    brier: float | None = None
    lessons: list[str] = Field(default_factory=list)


AGENT_OUTPUTS = {
    "macro_strategist": MacroStrategistOutput,
    "sector_analyst": SectorAnalystOutput,
    "business_analyst": BusinessAnalystOutput,
    "unit_economics_analyst": UnitEconomicsOutput,
    "financial_statement_analyst": FinancialStatementOutput,
    "forensic_accountant": ForensicAccountantOutput,
    "management_analyst": ManagementAnalystOutput,
    "transcript_analyst": TranscriptAnalystOutput,
    "ownership_flows_analyst": OwnershipFlowsOutput,
    "valuation_modeler": ValuationModelerOutput,
    "thesis_synthesizer": ThesisSynthesizerOutput,
    "red_team": RedTeamOutput,
    "portfolio_manager": PortfolioManagerOutput,
    "post_mortem": PostMortemOutput,
}
