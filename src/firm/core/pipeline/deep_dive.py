"""Phase 2 end-to-end: three agents, the evidence graph, and a published dual-verdict report (ADR-0021).

STATUS.md §3A described the gap precisely: "nothing in `core/agents/` or `core/orchestrator/` references
`EvidenceGraph` or `ResearchReport` … the machinery can detect and structure, but no report has yet been
published through the new pipeline." This module is that pipeline.

    facts (point-in-time, Law 3)
      → derivations, each carrying its input facts (Law 2)
        → optional audited-filing walk: grade-A figures + enumerated notes (owner directive 1 & 6)
          → business-model detection → playbook (ADR-0017)
            → line-by-line interrogation: every analyst question per statement line (ADR-0022)
            → every selected check evaluated explicitly (PASS/FLAG/UNAVAILABLE/NOT_APPLICABLE)
              → deterministic Gate-B forensic screen + §6.3 feasibility gate (Law 1)
                → three Tier-2 agents narrate, and ONLY narrate
                  → evidence-graph fragments, validated against R1-R6 (blocking)
                    → ResearchReport assembled, verdict chosen by code
                      → P1/P2/P3 publication gates (blocking)
                        → reports/{TICKER}/{run_id}/report.md + report.json

Four things are enforced here that no earlier phase could enforce, because they only exist once agents and
the report are joined:

1. **An agent may not produce a number** (Law 1). Every numeric schema field an agent returns is
   arithmetically checked against the compute layer's value; a field the compute layer cannot produce must
   come back `null`. Inventing one is a hard failure, not a note in a log.
2. **An agent may not cite a fact that does not exist** (Law 2). Narratives and claim texts are run
   through the citation validator against the run's known fact ids, with one corrective retry.
3. **An agent may not talk the firm out of a deterministic hard-fail.** The forensic agent's veto can only
   make a verdict worse; a `PASS` opinion over a deterministic HARD_FAIL is a discipline failure.
4. **A report that fails a publication gate never reaches disk** (`write_report` already refuses; here the
   violations are returned to the caller so a run can be debugged without publishing anything).

The run is keyed by `run_id = hash(tickers, as_of, agent versions, prompt versions, fact ids)` so the same
inputs produce the same directory (Law 5).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from functools import partial
from pathlib import Path
from typing import Any, Mapping, Sequence

from pydantic import BaseModel

from firm.core.agents.evidence import (
    Fragment,
    all_problems,
    build_fragment,
    cap_load_bearing,
    merge_graphs,
)
from firm.core.agents.loader import AgentSpec, load_agent
from firm.core.agents.packet import build_packet, load_house_style
from firm.core.agents.runner import run_agent
from firm.core.compute import multibagger, quality
from firm.core.compute.models import (
    BusinessModel,
    Playbook,
    StatementShape,
    build_playbook,
    detect_models,
)
from firm.core.config import (
    REPO_ROOT,
    forensic_thresholds,
    line_item_registry,
    load_thresholds,
    model_detection_thresholds,
    model_forensic_thresholds,
    model_playbooks,
    report_policy,
    universal_forensic_thresholds,
)
from firm.core.facts.store import Fact, FactStore
from firm.core.ingest.filings import restatement_log
from firm.core.llm.cache import make_key
from firm.core.llm.provider import Provider, StaticProvider
from firm.core.monitoring.predictions import Prediction, log_report_predictions
from firm.core.pipeline import derive as D
from firm.core.pipeline.checks import CheckEvaluation, ExternalInputs, evaluate_checks
from firm.core.pipeline.derive import CompanyFacts, DerivedSet
from firm.core.pipeline.filing import FilingSource, FilingWalk, disposition_notes, walk_filing
from firm.core.pipeline.interrogate import Interrogation, interrogate
from firm.core.pipeline.peers import PeerComparison, load_peer_comparisons
from firm.core.pipeline.peers import citable_values as peer_citable_values
from firm.core.pipeline.peers import payload_rows as peer_payload_rows
from firm.core.pipeline.valuation import load_valuation, valuation_derivations
from firm.core.report.assemble import (
    Narration,
    NotesReview,
    VerdictDecision,
    assemble_report,
    choose_verdict,
)
from firm.core.report.narration import deterministic_narration
from firm.core.report.publish import publish_or_degrade
from firm.core.report.render import write_report
from firm.core.validators import arithmetic, citation
from firm.core.validators.evidence_graph import GraphViolation, validate_graph
from firm.core.validators.publication import PublicationViolation, validate_report
from firm.schemas._base import AgentOutputBase
from firm.schemas.agents import AGENT_OUTPUTS
from firm.schemas.evidence import EvidenceGraph
from firm.schemas.report import CheckOutcome, ResearchReport

#: The Phase-2 roster, in run order (SPEC §11 Phase 2 — these three only). Retained as the default so an
#: existing caller behaves identically; `plan_agents()` is how a run picks its roster from Phase 3 onward.
PHASE2_AGENTS: tuple[str, ...] = (
    "business_analyst", "financial_statement_analyst", "forensic_accountant",
)


def plan_agents(
    *, phase: int, available_inputs: Sequence[str] = (), roster_path: str | Path | None = None
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """`(agents to run, coverage gaps)` for a run, from `config/roster.yaml` (ADR-0030/0033).

    Returns the gaps alongside the roster because they are the same decision seen from two sides: an agent
    that could not run is a hole in the report, and a report that does not say so is claiming coverage it
    does not have. The caller is expected to publish them — worded against the firm, never against the
    company (ADR-0019).
    """
    from firm.core.orchestrator.roster import load_roster, plan_run

    plan = plan_run(load_roster(roster_path), available_inputs=available_inputs, max_phase=phase)
    return plan.names, plan.disclosure_gaps()

#: Agent numeric field -> the derived metric it must equal. `None` = the compute layer cannot produce it
#: in this pipeline, so the agent MUST return null (Law 1: no LLM-authored numbers).
#:
#: EVERY top-level numeric field of every agent schema must appear here — `_numeric_discipline` checks
#: only what is registered, so an unregistered field is a number nobody validates. That hole was real:
#: the entire judgment tier's numeric fields (`base_case_value_per_share`, `position_size_pct`, ...) were
#: absent, latent only because Phase 4 had not run yet. `tests/schemas/test_numeric_registry.py` now
#: fails the build when a schema gains a numeric field that is neither registered here nor explicitly
#: classified as a judgment score below — coverage is structural, not remembered (the ADR-0021 lesson).
NUMERIC_FIELD_SOURCES: Mapping[str, str | None] = {
    "incremental_roic": "incremental_roic_3y",
    "cfo_to_ebitda": "cfo_to_ebitda_latest",
    "fcf_to_pat": "fcf_to_pat_cum",
    # The cash-conversion cycle IS working-capital days: receivable + inventory - payable. It became
    # derivable when the filing walk started reading the whole balance sheet (ADR-0037); until then the
    # field could only ever be null, and the schema had a slot no run could fill.
    "working_capital_days": "cash_conversion_cycle",
    "customer_concentration": None,
    "promise_delivery_score": None,
    "promoter_pledge_pct": None,
    # unit_economics_analyst — facts about the business; must trace to filings/compute or stay null.
    "units_today": None,
    "units_plausible_in_7y": None,
    "contribution_margin_per_unit": None,
    "payback_years": None,
    # ownership_flows_analyst — ADR-0007 wants smart money QUALITY-WEIGHTED, i.e. computed; until that
    # computation exists the score stays null and the judgment lives in prose, where it is validated.
    "smart_money_score": None,
    "days_to_exit_at_20pct_adv": None,
    # Phase-4 judgment tier (ADR-0062). The two valuation scalars now have real compute sources: the
    # valuation layer registers them as derivations on the run's DerivedSet, so the same Law-1 check
    # that polices `incremental_roic` polices these.
    "reverse_dcf_implied_growth": "reverse_dcf_implied_growth",
    "base_case_value_per_share": "base_case_value_per_share",
    # STILL NULL-ONLY, EACH FOR ITS OWN REASON — not because Phase 4 is unbuilt.
    #   `expectancy` and `position_size_pct` are functions of a JUDGMENT (how likely is the bull
    #   case?) and of computed multiples. An LLM may author neither, so the agent supplies the
    #   probabilities and the pipeline computes these from them (`scenarios.expectancy_from`). The
    #   agent must return null; a value here means it did the arithmetic itself.
    "position_size_pct": None,
    "expectancy": None,
    #   `base_rate_of_failure` is an empirical frequency ("how often has a business like this failed?")
    #   and this firm has no dataset behind it yet. Until one exists the honest answer is null and the
    #   argument lives in prose, where the citation gate can hold it to something real.
    "base_rate_of_failure": None,
    # Phase-5 post_mortem — produced by core/monitoring (resolver, Brier), never by the agent.
    "resolved_predictions": None,
    "brier": None,
}

#: Nested-model numeric fields an agent IS permitted to author, as `ClassName.field`. These are bounded
#: judgment scores, not financial facts — Law 1 governs financial numbers, and the house style *requires*
#: agents to state numeric confidence. Anything numeric and nested that is not listed here fails the
#: registry test, so adding a nested number forces this classification decision.
JUDGMENT_NUMERIC_FIELDS: frozenset[str] = frozenset({
    "Confidence.value",            # house style §5: numeric confidence, justified
    "Confidence.evidence_count",   # a count of the citations backing the claim
    "SectorScore.tailwind_score",  # bounded [-1, 1] sector judgment by design
    "SectorScore.horizon_years",   # the judgment's stated horizon
    # A scenario's PROBABILITY is the analyst's judgment and belongs here. Its return multiple does
    # not — see NESTED_COMPUTED_FIELDS.
    "ScenarioLine.probability",
})

#: Nested numeric fields that are neither free judgment nor a top-level metric: the compute layer
#: produces them per item, and the agent's copy is checked against it item by item (ADR-0062).
#:
#: `ScenarioLine.return_multiple` sat in the judgment allowlist while no valuation existed to check it
#: against, with a note saying to revisit this the day one did. This is that day. Allowlisting it now
#: would let an agent write "bull: 4.2x" beside a computed 0.22x and pass every gate — the single
#: easiest way to launder an invented number through this system.
NESTED_COMPUTED_FIELDS: frozenset[str] = frozenset({"ScenarioLine.return_multiple"})

_ARITHMETIC_REL_TOL = 0.01   # 1%: an agent restating a computed ratio may round it, not change it


class AgentDisciplineError(RuntimeError):
    """An agent broke a law: authored a number, cited a non-existent fact, or overrode a hard-fail."""

    def __init__(self, agent: str, problems: Sequence[str]) -> None:
        self.agent = agent
        self.problems = tuple(problems)
        super().__init__(f"{agent} violated {len(self.problems)} discipline rule(s): "
                         + "; ".join(self.problems))


@dataclass(frozen=True)
class DeepDiveResult:
    """Everything a run produced, publishable or not — so a blocked run is still fully debuggable."""

    ticker: str
    as_of: date
    run_id: str
    report: ResearchReport
    decision: VerdictDecision
    derived: DerivedSet
    evaluation: CheckEvaluation
    screen: quality.ForensicScreenResult
    feasibility: multibagger.FeasibilityResult | None
    models: tuple[BusinessModel, ...]
    playbook: Playbook
    notes: NotesReview
    interrogation: Interrogation
    graph: EvidenceGraph
    fragments: tuple[Fragment, ...]
    outputs: tuple[AgentOutputBase, ...]
    graph_violations: tuple[GraphViolation, ...]
    publication_violations: tuple[PublicationViolation, ...]
    markdown_path: Path | None = None
    json_path: Path | None = None
    #: Kill criteria logged to the prediction ledger. Empty unless the report published undegraded.
    predictions: tuple[Prediction, ...] = ()
    #: What the publication ladder had to withhold for this report to ship (ADR-0065). Empty means the
    #: report is exactly what the run assembled; non-empty means the same text is on the artifact.
    degradation: tuple[str, ...] = ()
    #: Gates still failing on the artifact that was WRITTEN. Should always be empty — the deterministic
    #: floor is built to satisfy them — so a non-empty value is a bug worth chasing, not a bad company.
    residual_violations: tuple[str, ...] = ()
    #: The report as FIRST assembled, kept only when the ladder published something else. The agents'
    #: narration is the most expensive thing a run produces and a gate failure should not vanish it from
    #: the operator's view; `firm deep-dive --force` writes this draft instead of the degraded report.
    assembled_report: ResearchReport | None = None

    @property
    def published(self) -> bool:
        return self.markdown_path is not None

    @property
    def degraded(self) -> bool:
        """True when the gates refused the assembled report and a lesser one was published instead."""
        return bool(self.degradation)

    @property
    def blocked_by(self) -> tuple[str, ...]:
        return tuple(v.rule for v in self.publication_violations)


def compute_run_id(
    ticker: str, as_of: date, specs: Sequence[AgentSpec], fact_ids: Sequence[str]
) -> str:
    """Content hash of everything that could change the output (Law 5: idempotent, resumable, cached)."""
    key = make_key(
        ticker, as_of.isoformat(),
        *[f"{s.name}@{s.version}" for s in specs],
        *sorted(fact_ids),
    )
    return f"{as_of.isoformat()}-{key[:12]}"


def statement_shape(facts: CompanyFacts, derived: DerivedSet) -> StatementShape:
    """Detection inputs from the statements as filed. Undisclosed ratios stay at their neutral default.

    `gross_margin` is deliberately left `None` unless COGS is disclosed: `models.detect_models` treats
    `None` as "not disclosed" and refuses to classify a trader on it, which is the behaviour we want (a
    zero would manufacture a TRADER tag out of missing data).
    """
    period = derived.last_period
    if period is None:
        return StatementShape()
    assets = facts.value(D.TOTAL_ASSETS, period) or 0.0
    if assets <= 0:
        return StatementShape()
    sales = facts.value(D.SALES, period) or 0.0
    return StatementShape(
        inventory_to_assets=(facts.value(D.INVENTORY, period) or 0.0) / assets,
        ppe_to_assets=(facts.value(D.FIXED_ASSETS, period) or 0.0) / assets,
        revenue_to_assets=sales / assets,
        gross_margin=None,
        # Without these two the detector could not see a lender however plainly the filing said so, and
        # the whole ADR-0002 branch — the suppression of Beneish/accruals/inventory checks that would be
        # meaningless on a loan book — was unreachable from a real filing.
        loan_book_to_assets=(facts.value(D.LOAN_BOOK, period) or 0.0) / assets,
        interest_income_to_revenue=(
            (facts.value(D.INTEREST_INCOME_PNL, period) or 0.0) / sales if sales > 0 else 0.0),
        employee_cost_to_revenue=(
            (facts.value(D.EMPLOYEE_COST, period) or 0.0) / sales if sales > 0 else 0.0),
    )


def feasibility_at_target(derived: DerivedSet, policy: Mapping[str, Any],
                 mb: Mapping[str, float], *, target_multiple: float | None = None,
                 target_years: int | None = None) -> multibagger.FeasibilityResult | None:
    """The §6.3 gate at the run's return target. None when ROIC is not derivable — never assumed.

    The target defaults to the config policy and may be overridden per run (ADR-0063): 5x/7y is the
    firm's house question, not a property of every company worth asking about.
    """
    roic = derived.value("roic_latest")
    if roic is None or roic <= 0:
        return None
    g = multibagger.required_earnings_cagr(
        float(target_multiple if target_multiple is not None else policy["target_return_multiple"]),
        int(target_years if target_years is not None else policy["target_years"]), 1.0)
    return multibagger.feasibility_gate(
        g_required=g, roic=roic,
        self_fund_ceiling=mb["self_fund_ceiling"], high_quality_ceiling=mb["high_quality_ceiling"],
        debt_capacity_available=True, thesis_allows_dilution=False,
    )


def agent_facts_payload(
    derived: DerivedSet, evaluation: CheckEvaluation, screen: quality.ForensicScreenResult,
    feasibility: multibagger.FeasibilityResult | None, models: Sequence[BusinessModel],
    notes: NotesReview, guidance: Sequence[Fact] = (),
    peers: Sequence[PeerComparison] = (),
    valuation: Any | None = None,
) -> dict[str, Any]:
    """What the agents are shown: computed numbers WITH their fact ids, and nothing they must compute.

    Every metric arrives as `{value, formula, fact_ids, grade}` so the agent can cite it correctly — the
    citation validator will hold it to exactly these ids, and the arithmetic validator to exactly these
    values.
    """
    return {
        "ticker": derived.ticker,
        "as_of": derived.as_of.isoformat(),
        "history": f"{derived.first_period}-{derived.last_period} ({derived.years}y)",
        "business_models_detected": [m.value for m in models] or ["none matched — universal checks only"],
        "computed_metrics": {
            name: {
                "value": d.value,
                "formula": d.formula,
                "fact_ids": list(d.fact_ids),
                "cite_as": f"[fact:derived:{name}]",
                "grade": d.citation.grade.value,
            }
            for name, d in derived.values.items()
        },
        "metrics_unavailable": {k: list(v) for k, v in derived.missing.items()},
        "forensic_screen": {
            "verdict": screen.verdict.value,
            "hard_fail": screen.hard_fail,
            "flags": [{"name": f.name, "severity": f.severity.name, "detail": f.detail}
                      for f in screen.flags],
        },
        "checklist": [
            {"check": r.name, "outcome": r.outcome.value, "detail": r.detail, "reason": r.reason}
            for r in evaluation.records
        ],
        "notes_to_accounts": {
            "enumerated": notes.notes_total,
            "coverage": notes.coverage,
            "substantive_share": notes.substantive_share,
            "disclosure_gaps": list(notes.disclosure_gaps),
        },
        # The sector read, deterministically (Phase 3). Every row is measured on ONE period both companies
        # cover, so `sector_analyst` cannot accidentally compare the subject's newest year against a peer's
        # older one; a measure with no common period arrives as a stated reason, not as an absent row.
        "peer_comparison": peer_payload_rows(peers),
        # Management's own forward numbers, quoted verbatim from Reg-30 transcripts (ADR-0039). A quarter
        # is present only when a transcript was ingested for it; the series reads oldest first so drift is
        # visible as a sequence. House standard applies: these are data about MANAGEMENT, not the business.
        "management_guidance": [
            {
                "period": f.period,
                "topic": f.metric.removeprefix("guidance:"),
                "value": f.value,
                "unit": f.unit,
                "quoted": f.locator,
                "cite_as": f"[fact:{f.fact_id}]",
                "grade": f.grade,
            }
            for f in guidance
        ],
        # The priced grid, for the judgment tier (ADR-0070). The valuation's SCALARS already reach the
        # agent through `computed_metrics` (they are derivations on the run's DerivedSet, so they carry
        # citable ids); the scenario ROWS do not, and `valuation_modeler` cannot assign probabilities to
        # scenarios it cannot see. Every row here is priced by the compute layer: the agent argues about
        # how likely each is, never about what each is worth.
        "valuation": None if valuation is None else {
            "status": valuation.status,
            "missing": list(valuation.missing),
            "price": valuation.price,
            "price_on": valuation.price_on.isoformat() if valuation.price_on else None,
            "implied_growth": valuation.implied_growth,
            "implied_growth_note": valuation.implied_growth_note,
            "realised_growth": valuation.realised_growth,
            "scenarios": [
                {"name": s.name, "growth": s.growth, "value_per_share": s.value_per_share,
                 "return_multiple": s.return_multiple}
                for s in valuation.scenarios
            ],
            "assumptions": dict(valuation.assumptions),
            "rule": ("these numbers are computed. Assign probabilities and argue about them; restating "
                     "a value per share or a return multiple differently from the rows above is a "
                     "Law-1 violation and fails the run"),
        },
        "feasibility_gate": None if feasibility is None else {
            "target": (f"{feasibility.g_required:.1%} earnings CAGR — the growth the run's return "
                       f"target demands with no re-rating and no dilution (SPEC §6.2)"),
            "g_required": feasibility.g_required,
            "roic": feasibility.roic,
            "required_reinvestment": feasibility.required_reinvestment,
            "verdict": feasibility.verdict.value,
            "rationale": feasibility.rationale,
        },
        "rules": [
            "Do NOT compute, adjust or invent any number. Quote only the values above.",
            "Every number you write in prose must be followed by its [fact:...] token.",
            "Numeric schema fields must equal the computed value above, or be null.",
            "open_questions must not be empty; disconfirming_search must describe a real search.",
        ],
    }


def _numeric_discipline(output: AgentOutputBase, derived: DerivedSet) -> list[str]:
    """Law 1 check: every numeric field the agent filled must match a computed value, or be null."""
    problems: list[str] = []
    for field_name, metric in NUMERIC_FIELD_SOURCES.items():
        if not hasattr(output, field_name):
            continue
        quoted = getattr(output, field_name)
        if quoted is None:
            continue
        computed = None if metric is None else derived.value(metric)
        if computed is None:
            problems.append(
                f"field '{field_name}' = {quoted} but the compute layer produced no such number "
                f"({'no derivation exists in this pipeline' if metric is None else metric + ' unavailable'})"
                " — Law 1: agents never author numbers"
            )
            continue
        check = arithmetic.check(field_name, float(quoted), float(computed),
                                rel_tol=_ARITHMETIC_REL_TOL)
        if not check.ok:
            problems.append(
                f"field '{field_name}' = {quoted} but {metric} computes to {computed} "
                f"(difference {check.abs_diff:.6g})"
            )
    return problems


def _scenario_discipline(
    output: AgentOutputBase, priced: Mapping[str, float]
) -> list[str]:
    """Every scenario line an agent returned must match the compute layer's priced grid (ADR-0062).

    Checked by NAME, so an agent cannot quietly relabel which column is "base" — the label an
    optimistic reading reassigns first. A line naming a scenario the compute layer never priced is a
    fabrication, and is reported as one rather than ignored.
    """
    lines = getattr(output, "scenarios", None)
    if not lines:
        return []
    problems: list[str] = []
    for line in lines:
        name = getattr(line, "name", "")
        quoted = getattr(line, "return_multiple", None)
        if quoted is None:
            continue
        if name not in priced:
            problems.append(
                f"scenario '{name}' has a return multiple of {quoted} but the compute layer never "
                f"priced a scenario by that name (priced: {sorted(priced)}) — Law 1: agents never "
                "author numbers")
            continue
        check = arithmetic.check(f"scenario[{name}].return_multiple", float(quoted),
                                 float(priced[name]), rel_tol=_ARITHMETIC_REL_TOL)
        if not check.ok:
            problems.append(
                f"scenario '{name}' return multiple {quoted} but the DCF prices it at "
                f"{priced[name]:.4f} (difference {check.abs_diff:.6g})")
    return problems


#: Fields the harness sets, not the agent: they carry version digits ("1.0.0") that are labels, not claims.
_IDENTITY_FIELDS = frozenset({"agent", "agent_version", "ticker", "as_of"})
#: Structured provenance, not prose: a `Citation` is *made* of ids, doc names and extractor versions full of
#: digits, and it is validated by id lookup (`build_fragment`) rather than by reading it as a sentence.
_NON_PROSE_FIELDS = frozenset({"citations", "citation"})


def _walk_strings(label: str, value: object, out: list[tuple[str, str]]) -> None:
    if isinstance(value, str):
        out.append((label, value))
    elif isinstance(value, BaseModel):
        for name in type(value).model_fields:
            if name in _IDENTITY_FIELDS or name in _NON_PROSE_FIELDS:
                continue
            _walk_strings(f"{label}.{name}" if label else name, getattr(value, name), out)
    elif isinstance(value, list):
        for index, item in enumerate(value, start=1):
            _walk_strings(f"{label}[{index}]", item, out)


def authored_texts(output: AgentOutputBase) -> list[tuple[str, str]]:
    """Every string the agent authored, labelled by where it came from.

    Deliberately derived from the schema rather than from a list of field names. The first version of this
    checked only `narrative` and the claim texts — and `business_analyst.what_it_does`,
    `disconfirming_search` and `open_questions` are all rendered into the published report, so an invented
    figure could ride into a `COMPOUNDER` note through a field nobody was looking at. Enumerating fields by
    hand re-opens that hole every time a schema grows a field, so instead: **any string an agent returns is
    prose, and prose is checked** (Laws 1 and 2). It recurses into nested models too, so the Phase-3/4
    agents (`SectorScore.falsifier`, `ScenarioLine.name`, …) are covered before they are wired. Numeric
    schema fields are covered separately by `_numeric_discipline`.
    """
    out: list[tuple[str, str]] = []
    _walk_strings("", output, out)
    return out


def _citation_problems(
    output: AgentOutputBase, known: set[str], values: Mapping[str, float] | None = None
) -> list[str]:
    """Law 2 check: every number an agent wrote carries a `[fact:...]` token naming a real fact — and,
    when the run's values are supplied, states that fact's actual figure rather than a corrupted one."""
    problems: list[str] = []
    for label, text in authored_texts(output):
        for problem in citation.validate(text, known, values=values):
            problems.append(f"{label}: number {problem.number!r} — {problem.reason}")
    return problems


def _run_one_agent(
    spec: AgentSpec,
    schema: type[AgentOutputBase],
    *,
    provider: Provider,
    model: str,
    system: str,
    user: str,
    derived: DerivedSet,
    known_fact_ids: set[str],
    known_values: Mapping[str, float],
    max_citation_retries: int,
    #: {scenario name: return multiple} from the priced grid, for `_scenario_discipline`. Empty when the
    #: valuation could not run — in which case an agent quoting ANY return multiple is authoring it.
    priced_scenarios: Mapping[str, float] | None = None,
) -> AgentOutputBase:
    """Run an agent and hold it to Laws 1 and 2, with one corrective retry before failing the run."""
    prompt = user
    last: list[str] = []
    for attempt in range(max_citation_retries + 1):
        output = run_agent(provider, system=system, user=prompt, model=model, schema=schema)
        problems = (_numeric_discipline(output, derived)
                    + _scenario_discipline(output, priced_scenarios or {})
                    + _citation_problems(output, known_fact_ids, known_values))
        if not problems:
            return output
        last = problems
        prompt = (
            f"{user}\n\n## Your previous answer broke the house laws — fix these and resend the JSON\n"
            + "\n".join(f"- {p}" for p in problems)
            + "\n\nEvery number in prose needs its [fact:...] token; numeric fields must equal the "
              "computed values or be null."
        )
    raise AgentDisciplineError(spec.name, last)


def build_packets(
    payload: Mapping[str, Any],
    *,
    agents_dir: Path,
    repo_root: Path,
    agents: Sequence[str] = PHASE2_AGENTS,
) -> dict[str, tuple[AgentSpec, str, str]]:
    """{agent: (spec, system, user)} — the exact prompts a provider will see.

    Exposed separately so `firm packets` can write them to disk for the Claude-in-the-loop path
    (ADR-0010): no API key, subscription only, and the answer comes back through `StaticProvider`.
    """
    house = load_house_style(repo_root)
    out: dict[str, tuple[AgentSpec, str, str]] = {}
    for name in agents:
        spec = load_agent(agents_dir / f"{name}.md")
        schema = AGENT_OUTPUTS[name]
        system, user = build_packet(spec, dict(payload), schema.model_json_schema(), house)
        out[name] = (spec, system, user)
    return out


def _thesis_prose(
    outputs: Mapping[str, AgentOutputBase], ba: AgentOutputBase | None
) -> str:
    """The thesis: `thesis_synthesizer`'s when it ran, the business analyst's case when it did not.

    `thesis_synthesizer` owns the "this returns Nx if and only if A, B and C" form (SPEC §7), and its
    three load-bearing assumptions are the part a reader checks first — so they are rendered as a list
    rather than buried in the paragraph. Its `feasibility_verdict` is NOT printed here: the gate's own
    verdict is computed and already rendered in the Return-potential section, and printing an agent's
    restatement beside it invites the two to disagree.
    """
    ts = outputs.get("thesis_synthesizer")
    if ts is None:
        return ba.narrative if ba is not None else ""
    parts = [ts.narrative.strip()] if ts.narrative.strip() else []
    if getattr(ts, "return_multiple_if", "").strip():
        parts.append(f"**Returns its multiple if and only if:** {ts.return_multiple_if.strip()}")
    assumptions = [a for a in getattr(ts, "three_load_bearing_assumptions", []) if a.strip()]
    if assumptions:
        parts.append(
            "**The load-bearing assumptions — the thesis fails if any of these fails:**\n"
            + "\n".join(f"{i}. {a.strip()}" for i, a in enumerate(assumptions, 1))
        )
    if ba is not None and ba.narrative.strip():
        parts.append(f"**business_analyst:** {ba.narrative.strip()}")
    return "\n\n".join(parts)


def _narration(
    outputs: Mapping[str, AgentOutputBase],
    screen: quality.ForensicScreenResult,
    evaluation: CheckEvaluation,
    derived: DerivedSet,
    feasibility: multibagger.FeasibilityResult | None,
) -> Narration:
    """Compose the report's prose sections from the three agents' designated fields.

    Phase 2 has no `thesis_synthesizer` (Phase 4) and no `red_team`, so the report does not pretend to
    have one: the thesis is the business analyst's case, and the anti-thesis is built from every agent's
    **mandatory** `disconfirming_search` plus the flags that actually fired. Both sections therefore have
    a real author, and P2's "the opposing case is mandatory" gate is satisfied by evidence rather than by
    a paragraph invented to satisfy a validator.
    """
    ba = outputs.get("business_analyst")
    fsa = outputs.get("financial_statement_analyst")
    fa = outputs.get("forensic_accountant")

    # §3 is the plain-language money-flow description (`what_it_does`); §8 is the case the same agent
    # makes from it (`narrative`). Keeping them separate stops one paragraph being printed twice.
    business = getattr(ba, "what_it_does", "") if ba is not None else ""

    anti_parts: list[str] = []
    for name, out in outputs.items():
        if out.disconfirming_search.strip():
            anti_parts.append(f"**{name} (disconfirming search):** {out.disconfirming_search.strip()}")
    fired = [r for r in evaluation.records if r.outcome is CheckOutcome.FLAG]
    if fired:
        anti_parts.append(
            "**Checks that fired:** " + "; ".join(f"`{r.name}` — {r.detail}" for r in fired)
        )
    unavailable = [r for r in evaluation.records if r.outcome is CheckOutcome.UNAVAILABLE]
    if unavailable:
        anti_parts.append(
            f"**Not verifiable from the sources read:** {len(unavailable)} of "
            f"{len(evaluation.expected)} applicable checks could not be evaluated, so the case against "
            "this company includes everything we could not look at."
        )

    # THE JUDGMENT TIER (ADR-0070). Same rule as the sector and governance sections: list the
    # section's authors and render whoever ran, so a newly staffed agent appears the day it is added
    # rather than the day someone remembers to edit this function (the ADR-0034 lesson).
    #
    # The deterministic Valuation section carries the reverse DCF and the priced grid (ADR-0069), so
    # this note must never claim that tier is missing — it renders directly above this text. When no
    # judgment agent ran, it says the true thing instead: the arithmetic is there and nobody has
    # argued with it.
    judgment_agents = [n for n in ("valuation_modeler", "portfolio_manager") if n in outputs]
    judgment_prose = "\n\n".join(
        f"**{n}:** {outputs[n].narrative.strip()}"
        for n in judgment_agents if outputs[n].narrative.strip()
    )
    if judgment_prose:
        valuation = judgment_prose
        # `staged_entry` is a schema field with no reader — the ADR-0034 failure at field level. It is
        # the one part of the portfolio manager's output that says WHEN, and it is framed as staging
        # against evidence rather than as an instruction: this firm publishes research, never orders.
        staged = getattr(outputs.get("portfolio_manager"), "staged_entry", None)
        if staged and staged.strip():
            valuation += f"\n\n**Staging (research view, not an instruction):** {staged.strip()}"
        absent_judgment = [n for n in ("valuation_modeler", "portfolio_manager")
                           if n not in outputs]
        if absent_judgment:
            valuation += (
                f"\n\nNot staffed on this run: {', '.join(f'`{n}`' for n in absent_judgment)} — that "
                "reading is absent rather than favourable."
            )
    else:
        base = (
            "No analyst has yet argued with the computed valuation above. The reverse DCF and the "
            "scenario grid are deterministic — priced from the company's own realised growth against "
            "the settled exchange close — and the judgment tier that would weigh their probabilities "
            "(`valuation_modeler`, `red_team`) is not staffed in this run. Read the section above as "
            "arithmetic about the price, not as a view on it."
        )
        valuation = base if feasibility is None else (
            f"The self-funding test and the price test are different questions and both are answered "
            f"here. Feasibility: {feasibility.rationale} {base}"
        )

    # The red team's bear case belongs in the anti-thesis, where P2 makes it structural, and its
    # narrative is prefixed like every other disconfirming contribution so the author is visible.
    rt = outputs.get("red_team")
    if rt is not None:
        bear = getattr(rt, "bear_case", "").strip()
        if bear:
            anti_parts.insert(0, f"**red_team (bear case):** {bear}")
        for criterion in getattr(rt, "kill_criteria", []):
            anti_parts.append(f"**red_team (kill criterion):** {criterion}")
    # EVERY AGENT THAT RAN MUST BE READABLE SOMEWHERE. `sector_analyst`, `macro_strategist` and
    # `unit_economics_analyst` were validating, entering `agent_versions` — so the report named them as
    # contributors — and then having their narratives dropped, because `_narration` only read six agents
    # by name. The peer comparison the sector agent exists to make reached no page at all. Listing the
    # section's authors, rather than naming three more agents here, means a tenth agent renders the day
    # it is added instead of the day someone remembers to edit this function.
    sector_agents = [name for name in ("sector_analyst", "macro_strategist", "unit_economics_analyst")
                     if name in outputs]
    sector = "\n\n".join(
        f"**{name}:** {outputs[name].narrative.strip()}"
        for name in sector_agents if outputs[name].narrative.strip()
    )

    # THE MANAGEMENT SECTION MUST DESCRIBE THE RUN THAT HAPPENED. This was hardcoded to say the three
    # governance agents "did not run", which was true while the roster was a fixed Phase-2 trio and became
    # a false statement in a published report the moment Phase 3 staffed them (ADR-0034). A report that
    # misdescribes its own coverage is worse than one with a gap, because the gap is at least honest.
    governance_agents = [name for name in
                         ("management_analyst", "transcript_analyst", "ownership_flows_analyst")
                         if name in outputs]
    if governance_agents:
        management = "\n\n".join(
            f"**{name}:** {outputs[name].narrative.strip()}"
            for name in governance_agents if outputs[name].narrative.strip()
        ) or (
            "The governance agents ran but returned no narrative, which is a defect in this run rather "
            "than a finding about the company."
        )
        absent = [name for name in
                  ("management_analyst", "transcript_analyst", "ownership_flows_analyst")
                  if name not in outputs]
        if absent:
            management += (
                f"\n\nNot staffed on this run: {', '.join(f'`{n}`' for n in absent)} — the findings that "
                "agent would produce are absent rather than clean."
            )
    else:
        management = (
            "No management or governance assessment is made in this report: `management_analyst`, "
            "`transcript_analyst` and `ownership_flows_analyst` did not run. Promoter-pledge, "
            "promise-vs-delivery and board-interlock findings are therefore absent rather than clean."
        )

    open_questions: list[str] = []
    for out in outputs.values():
        open_questions += [f"{out.agent}: {q}" for q in out.open_questions]
    for record in evaluation.records:
        if record.outcome is CheckOutcome.UNAVAILABLE:
            open_questions.append(f"{record.name}: {record.reason}")

    replication = [
        (f"Re-run `python -m firm deep-dive --ticker {derived.ticker} "
         f"--as-of {derived.as_of.isoformat()}`; the run id is a content hash of the inputs, so the "
         "same facts reproduce this report byte-for-byte."),
        ("Every figure in §4 lists its formula and input fact ids; each fact resolves to "
         "(doc_id, page/line, published_at, grade) in the fact store."),
    ]
    for record in evaluation.records:
        if record.outcome is CheckOutcome.FLAG:
            replication.append(
                f"`{record.name}`: {record.detail} — recompute from fact ids "
                f"{', '.join(record.fact_ids) or '(see §4)'}."
            )

    return Narration(
        executive_summary=(fsa.narrative if fsa is not None else ""),
        business_model_plain=business,
        forensic_narrative=(fa.narrative if fa is not None else ""),
        sector_narrative=sector,
        management_narrative=management,
        valuation_narrative=valuation,
        thesis=_thesis_prose(outputs, ba),
        anti_thesis="\n\n".join(anti_parts),
        open_questions=tuple(dict.fromkeys(open_questions)),
        replication_notes=tuple(replication),
    )


@dataclass
class _AgentRun:
    outputs: dict[str, AgentOutputBase] = field(default_factory=dict)
    fragments: list[Fragment] = field(default_factory=list)


def run_deep_dive(
    store: FactStore,
    ticker: str,
    as_of: date,
    *,
    provider: Provider | None = None,
    answers: Mapping[str, str] | None = None,
    company_name: str | None = None,
    filing: FilingSource | None = None,
    model: str = "analysis",
    reports_root: str | Path = "reports",
    memory_root: str | Path | None = None,
    agents_dir: str | Path | None = None,
    repo_root: str | Path | None = None,
    agents: Sequence[str] = PHASE2_AGENTS,
    #: Coverage gaps from `plan_agents` — agents the roster planned but could not run (ADR-0033). Passed
    #: in rather than recomputed so the report states exactly the plan this run was executed against.
    coverage_gaps: Sequence[str] = (),
    #: Tickers to compare against, for `sector_analyst`. Their facts are read point-in-time like the
    #: subject's, and a named peer with no facts as-of the date is reported as a coverage gap.
    peers: Sequence[str] = (),
    #: None (default) = the window is what the evidence covers (ADR-0055); an explicit
    #: year deliberately narrows the record and is never how the record is defined.
    start_year: int | None = None,
    write: bool = True,
    max_citation_retries: int = 1,
    #: The return target this run is judged against (ADR-0063/0068). None = the config default (5x/7y).
    #: Whatever is used is printed in the report's Return-potential section.
    target_multiple: float | None = None,
    target_years: int | None = None,
    #: ADR-0046 walk options: a verified reading already covers the numeric rows (so the row-locator must
    #: not re-register them), and may supply verified note/related-party enumerations in place of the
    #: pattern scanners. Defaults preserve the walker-only path unchanged.
    walk_numeric_rows: bool = True,
    notes_override: Sequence[Any] | None = None,
    related_party_override: Any | None = None,
) -> DeepDiveResult:
    """Run Phase 2 for one company and publish the report if it passes every gate.

    `answers` is the Claude-in-the-loop path: {agent name: raw JSON} answered outside this process, used
    instead of `provider` per agent. Exactly one of `provider` / `answers` must cover each agent.
    """
    repo = Path(repo_root or REPO_ROOT)
    agents_path = Path(agents_dir or repo / "agents")
    policy = report_policy()
    thresholds = load_thresholds()

    # ---- 1. facts + derivations (Laws 2 & 3) -----------------------------------------------------
    facts = D.load_company_facts(store, ticker, as_of, start_year=start_year)
    walk: FilingWalk | None = None
    # Law 3 applies to the DOCUMENT, not only to its figures: a filing disseminated after `as_of` must not
    # be read at all. Filtering its facts at the query layer would still leak its notes, its Schedule III
    # rows and its auditor language into the run — exactly the look-ahead the point-in-time rule exists to
    # prevent once this pipeline is replayed over history (Phase 6).
    if filing is not None and filing.published_at <= as_of:
        walk = walk_filing(store, ticker, filing, numeric_rows=walk_numeric_rows,
                           notes_override=notes_override,
                           related_party_override=related_party_override)
        facts = D.load_company_facts(store, ticker, as_of, start_year=start_year)  # re-read: AR facts
    derived = D.derive_metrics(facts)

    # ---- 2. business model -> playbook (ADR-0017) ------------------------------------------------
    models = tuple(detect_models(statement_shape(facts, derived), model_detection_thresholds()))
    playbook = build_playbook(models, model_playbooks())

    # ---- 2b. line-by-line interrogation (ADR-0022) ------------------------------------------------
    # Runs before the checks because it is the wider net: the forensic playbook asks whether the numbers
    # are honest, this asks whether anyone has established what the numbers mean. Both feed the verdict.
    interrogation = interrogate(derived, [m.value for m in models], line_item_registry())

    # ---- 3. evaluate every selected check, then the deterministic screens (Law 1) -----------------
    external = walk.external if walk is not None else ExternalInputs()
    evaluation = evaluate_checks(
        playbook, derived, facts,
        forensic=thresholds["forensic"], universal=universal_forensic_thresholds(),
        model_specific=model_forensic_thresholds(), external=external,
    )
    sector = (quality.SectorClass.FINANCIAL if BusinessModel.LENDER in models
              or BusinessModel.BANK in models else quality.SectorClass.NON_FINANCIAL)
    screen = quality.forensic_screen(sector, evaluation.metrics, forensic_thresholds(),
                                    checks_ran=evaluation.ran, checks_expected=len(evaluation.applicable),
                                    min_ran_share=float(thresholds["forensic"].get("screen_min_ran_share", 0)))
    feasibility = feasibility_at_target(
        derived, policy, thresholds["multibagger"],
        target_multiple=target_multiple, target_years=target_years)

    # ---- 3b. the valuation (Phase 4, ADR-0062/0069) ----------------------------------------------
    # Runs after the checks and before the agents, because its outputs become DERIVATIONS: merged onto
    # the run's DerivedSet, they are policed by the same Law-1 arithmetic validator that polices
    # `incremental_roic`, so an agent restating a scenario's value per share is checked against the
    # priced grid rather than trusted. A run with no price still produces a valuation — one whose
    # status is `unavailable` and whose missing inputs are named.
    valuation = load_valuation(store, ticker, as_of, facts, derived,
                               policy=thresholds["valuation"])
    derived = derived.extended(valuation_derivations(valuation))

    notes, _dispositions = (
        disposition_notes(walk.notes, evaluation, disclosure_gaps_found=walk.missing_disclosures,
                          reconciliations=walk.reconciliations)
        if walk is not None else (NotesReview(), ())
    )

    # ---- 4. the agents: narration only -----------------------------------------------------------
    # Guidance is read through its own point-in-time query, not CompanyFacts: one call quarter carries
    # several guided figures under one metric, and the per-(metric, period) resolution that is right for a
    # balance-sheet row would silently drop all but one of them (ADR-0040).
    guidance = store.query_metric_prefix(ticker, "guidance:", as_of)
    peer_comparisons = load_peer_comparisons(store, ticker, peers, as_of, start_year=start_year)
    peer_values = peer_citable_values(peer_comparisons)
    payload = agent_facts_payload(derived, evaluation, screen, feasibility, models, notes,
                                  guidance=guidance, peers=peer_comparisons, valuation=valuation)
    packets = build_packets(payload, agents_dir=agents_path, repo_root=repo, agents=agents)
    known_fact_ids = (set(facts.all_fact_ids()) | {f"derived:{n}" for n in derived.values}
                      | {f.fact_id for f in guidance} | set(peer_values))
    # {fact_id: value} so a number cited to a real fact must state that fact's figure (Law 1): the most
    # plausible way an LLM corrupts a number is to keep the citation and change the digits.
    known_values: dict[str, float] = {
        f.fact_id: f.value for metric in facts.series for f in facts.series[metric].values()
    }
    known_values.update({f"derived:{n}": d.value for n, d in derived.values.items()})
    known_values.update({f.fact_id: f.value for f in guidance})
    known_values.update(peer_values)

    # PRE-FLIGHT (ADR-0033). On the Claude-in-the-loop path (`--answers`) an agent with no answer file used
    # to fall through to whatever provider was configured — by default the local stub, whose output fails
    # schema validation. The run then burned three retries PER unstaffed agent and died with
    # "agent output failed validation after 3 attempts", naming no agent and not hinting at the real cause.
    # A roster that plans more agents than the operator has answered is an ordinary situation now that the
    # roster grows with the build phase, so it deserves a precise error rather than a confusing one.
    if answers is not None:
        unanswered = [name for name in packets if name not in answers]
        if unanswered:
            raise ValueError(
                f"no prepared answer for {len(unanswered)} planned agent(s): {', '.join(unanswered)}. "
                f"Write their packets with `firm packets --ticker {ticker} --phase <n>`, answer each one, "
                f"and place the JSON at {{agent}}.json — or lower --phase so the roster plans only the "
                f"agents you have answered."
            )

    # The priced grid, keyed by name, so `_scenario_discipline` can check an agent's scenario lines item
    # by item. ADR-0062 wrote that check — calling it "the single easiest way to launder an invented
    # number through this system" — and nothing ever called it, so until now an agent could write
    # "bull: 4.2x" beside a computed 0.03x and pass every gate (ADR-0070).
    priced_scenarios = {s.name: s.return_multiple for s in valuation.scenarios}

    run = _AgentRun()
    specs = [spec for spec, _, _ in packets.values()]
    # Guidance and peer ids join the key: two runs seeing different transcripts, or a different peer set,
    # are different runs (Law 5).
    run_id = compute_run_id(
        ticker, as_of, specs,
        tuple(facts.all_fact_ids()) + tuple(f.fact_id for f in guidance) + tuple(sorted(peer_values)))

    for name, (spec, system, user) in packets.items():
        agent_provider = provider
        if answers is not None and name in answers:
            agent_provider = StaticProvider(answers[name])
        if agent_provider is None:
            raise ValueError(f"no provider and no prepared answer for agent {name!r}")
        output = _run_one_agent(
            spec, AGENT_OUTPUTS[name], provider=agent_provider, model=model, system=system, user=user,
            derived=derived, known_fact_ids=known_fact_ids, known_values=known_values,
            max_citation_retries=max_citation_retries, priced_scenarios=priced_scenarios,
        )
        run.outputs[name] = output
        run.fragments.append(build_fragment(
            output, known_fact_ids=known_fact_ids,
            min_confidence=float(policy["load_bearing_min_confidence"]),
            max_load_bearing=int(policy["load_bearing_max_points"]),
        ))

    problems = all_problems(run.fragments)
    if problems:
        raise AgentDisciplineError(
            "evidence_graph",
            [f"{p.agent}/{p.claim_id} cites unknown fact {p.fact_id!r}" for p in problems],
        )

    # The forensic agent may not narrate its way past a deterministic hard fail (agent card: forbidden).
    forensic_out = run.outputs.get("forensic_accountant")
    if forensic_out is not None and screen.hard_fail and not getattr(forensic_out, "veto", False):
        raise AgentDisciplineError("forensic_accountant", [
            (f"deterministic screen returned HARD_FAIL "
             f"({', '.join(f.name for f in screen.flags)}) but the agent returned "
             f"verdict={getattr(forensic_out, 'verdict', '?')!r} with veto=False — a "
             "deterministic hard-fail cannot be overturned on narrative grounds")
        ])

    # ---- 5. evidence graph: blocking invariants R1-R6 --------------------------------------------
    graph = merge_graphs([f.graph for f in run.fragments])
    load_bearing_ids = cap_load_bearing(
        graph,
        [cid for f in run.fragments for cid in f.load_bearing_claim_ids],
        int(policy["load_bearing_max_points"]),
    )
    graph_violations = tuple(validate_graph(graph, as_of))

    # ---- 6. verdict + report ---------------------------------------------------------------------
    decision = choose_verdict(
        screen, evaluation, notes, feasibility,
        policy=policy, history_years=derived.years,
        min_history_years=int(thresholds["screen"]["min_history_years"]),
        forensic_veto=bool(getattr(forensic_out, "veto", False)) if forensic_out else False,
        interrogation=interrogation,
        # NOT `coverage_gaps`. The verdict must never move because the FIRM failed to look — ADR-0019.
        # They reach the report (below) so a reader sees them, and stop there.
    )
    # Everything run-constant is bound once: the publication ladder (ADR-0065) may have to re-assemble
    # this report two or three times, and a second literal argument list is a second place to drift.
    assemble = partial(
        assemble_report,
        ticker=ticker, company_name=company_name or ticker, as_of=as_of, run_id=run_id,
        derived=derived, evaluation=evaluation, models=models, notes=notes,
        agent_versions={o.agent: o.agent_version for o in run.outputs.values()},
        forensic=thresholds["forensic"], policy=policy,
        feasibility=feasibility,
        self_fund_ceiling=float(thresholds["multibagger"]["self_fund_ceiling"]),
        interrogation=interrogation,
        target_multiple=target_multiple, target_years=target_years, valuation=valuation,
        # Quiet revisions between visible filings (lesson 3 of the first prediction resolution): every
        # figure a later filing changed, point-in-time, from the overlap classifier. Deterministic; the
        # Ind AS transition legitimately produces a cluster, which is why the section explains itself.
        restatements=restatement_log(
            store, ticker, None, as_of, thresholds["reconciliation"]),
    )
    agent_narration = _narration(run.outputs, screen, evaluation, derived, feasibility)
    assembled = assemble(
        decision=decision, graph=graph, load_bearing_ids=load_bearing_ids,
        narration=agent_narration, coverage_gaps=coverage_gaps,
    )

    publication_violations = tuple(validate_report(assembled))
    # ADR-0064/0065: a company the owner chose is never left without an artifact. The gates stay
    # blocking — `publication_violations` above still records exactly what they refused — but the
    # fallback when they block is a report that asserts LESS, never a lowered gate.
    report, degradation, residual_violations = publish_or_degrade(
        assemble=assemble, as_of=as_of, report=assembled, decision=decision,
        publication_violations=publication_violations, graph_violations=graph_violations,
        agent_narration=agent_narration,
        fallback_narration=deterministic_narration(
            evaluation=evaluation, screen=screen, notes=notes,
            interrogation=interrogation, feasibility=feasibility,
        ),
        graph=graph, load_bearing_ids=load_bearing_ids, coverage_gaps=coverage_gaps,
    )

    md_path = json_path = None
    logged: tuple[Prediction, ...] = ()
    if write:
        # `force` only ever applies on the ladder's last rung, where the artifact names its own failed
        # gates in the body — an unpublishable draft that says so beats silence (ADR-0065).
        md_path, json_path = write_report(report, reports_root, force=bool(residual_violations))
        # Phase 5 (ADR-0023): a published report's dated kill criteria become scoreable predictions.
        # Only on a clean publish — a report the gates refused was never a forecast, and logging one
        # would let the calibration record fill up with theses the firm declined to stand behind.
        if not degradation:
            ledger = Path(memory_root) if memory_root is not None else Path(repo) / "memory"
            logged = tuple(log_report_predictions(report, ledger / "predictions.jsonl"))

    return DeepDiveResult(
        ticker=ticker, as_of=as_of, run_id=run_id, report=report, decision=decision, derived=derived,
        evaluation=evaluation, screen=screen, feasibility=feasibility, models=models,
        playbook=playbook, notes=notes, interrogation=interrogation, graph=graph,
        fragments=tuple(run.fragments),
        outputs=tuple(run.outputs.values()), graph_violations=graph_violations,
        publication_violations=publication_violations, markdown_path=md_path, json_path=json_path,
        predictions=logged, degradation=degradation, residual_violations=residual_violations,
        assembled_report=assembled if degradation else None,
    )


def write_packets(
    payload: Mapping[str, Any], out_dir: str | Path, *, agents_dir: str | Path | None = None,
    repo_root: str | Path | None = None, agents: Sequence[str] = PHASE2_AGENTS,
) -> list[Path]:
    """Write each agent's packet to disk for the Claude-in-the-loop path (ADR-0010). Returns the paths."""
    repo = Path(repo_root or REPO_ROOT)
    packets = build_packets(
        payload, agents_dir=Path(agents_dir or repo / "agents"), repo_root=repo, agents=agents)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, (spec, system, user) in packets.items():
        path = out / f"{name}.md"
        path.write_text(
            f"<!-- agent: {spec.name}@{spec.version} · answer with ONE JSON object matching the schema "
            f"at the end · save it as {name}.json in this directory -->\n\n"
            f"# SYSTEM\n\n{system}\n\n# USER\n\n{user}\n"
        )
        written.append(path)
    (out / "facts.json").write_text(json.dumps(payload, indent=2, default=str) + "\n")
    return written


def read_answers(answers_dir: str | Path, agents: Sequence[str] = PHASE2_AGENTS) -> dict[str, str]:
    """Read `{agent}.json` answers written by the Claude-in-the-loop path. Missing files are skipped."""
    directory = Path(answers_dir)
    out: dict[str, str] = {}
    for name in agents:
        path = directory / f"{name}.json"
        if path.exists():
            out[name] = path.read_text()
    return out


__all__ = [
    "NUMERIC_FIELD_SOURCES",
    "PHASE2_AGENTS",
    "AgentDisciplineError",
    "DeepDiveResult",
    "agent_facts_payload",
    "build_packets",
    "compute_run_id",
    "feasibility_at_target",
    "read_answers",
    "run_deep_dive",
    "statement_shape",
    "write_packets",
]
