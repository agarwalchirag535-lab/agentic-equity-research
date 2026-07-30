"""Assemble a `ResearchReport` from deterministic evidence + agent narration (Phase 2, ADR-0021).

This is the join STATUS.md §3A named as the real gap: the compute layer, the checklist, the evidence
graph and the three Tier-2 agents all existed, but nothing turned them into a publishable artifact.

The division of labour is the whole design, and it is enforced here rather than requested politely:

| decided by code (this module)                  | written by an agent                       |
|------------------------------------------------|-------------------------------------------|
| the verdict                                    | why the verdict reads the way it does     |
| every number and its citation                  | the argument connecting the numbers       |
| which claims are load-bearing                  | the claim text                            |
| kill / rehabilitation criteria                 | the thesis and the anti-thesis prose      |
| what was checked, and what could not be        | the interpretation of what was checked    |

Verdict order matters and is not negotiable: an evidenced red flag outranks an opacity finding, which
outranks a valuation/feasibility judgment, which outranks "promising but unproven". Reading the ladder
top-down is the argument for it — the strongest thing you can say about a company is that its own
filings contradict themselves; the weakest is that you have not seen enough yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Mapping, Sequence

from firm.core.compute.models import BusinessModel
from firm.core.compute.multibagger import FeasibilityResult, GateVerdict
from firm.core.compute.quality import ForensicScreenResult, Severity
from firm.core.pipeline.checks import CheckEvaluation
from firm.core.pipeline.derive import DerivedSet
from firm.core.report.criteria import kill_criteria, rehabilitation_criteria
from firm.schemas._base import Citation, Confidence, Grade
from firm.schemas.evidence import EvidenceGraph
from firm.schemas.report import (
    CheckOutcome,
    ReportClaim,
    ResearchReport,
    Verdict,
    VerifiedCleanChecklist,
)

_GRADE_ORDER = (Grade.A, Grade.B, Grade.C, Grade.D)


@dataclass(frozen=True)
class NotesReview:
    """The line-by-line record (ADR-0017). `substantive_share` is the anti-theatre number.

    100% coverage where every note is dispositioned `unknown` satisfies the letter of the coverage gate
    while reading nothing. `substantive_share` (clean/flag dispositions ÷ notes) is what the verdict
    actually consults, so that loophole cannot buy a positive verdict.
    """

    coverage: float = 0.0
    undispositioned: tuple[int, ...] = ()
    substantive_share: float = 0.0
    notes_total: int = 0
    disclosure_gaps: tuple[str, ...] = ()
    scanned: bool = False


@dataclass(frozen=True)
class VerdictDecision:
    verdict: Verdict
    rationale: str


def choose_verdict(
    screen: ForensicScreenResult,
    evaluation: CheckEvaluation,
    notes: NotesReview,
    feasibility: FeasibilityResult | None,
    *,
    policy: Mapping[str, Any],
    history_years: int,
    min_history_years: int,
    forensic_veto: bool = False,
) -> VerdictDecision:
    """The deterministic verdict ladder. No LLM votes; `forensic_veto` is the one agent-supplied input.

    `forensic_veto` exists because the forensic agent holds an absolute veto (SPEC, agent card) — but it
    can only ever make the verdict *worse*, never better, so it cannot be used to talk a company up.
    """
    min_severity = Severity(int(policy["caution_min_severity"]))
    severe = [f for f in screen.flags if f.severity >= min_severity]
    if screen.hard_fail or severe or forensic_veto:
        names = ", ".join(f.name for f in severe) or "forensic agent veto"
        return VerdictDecision(Verdict.FORENSIC_CAUTION, (
            f"deterministic screen returned {screen.verdict.value} with {len(screen.flags)} flag(s); "
            f"at or above severity {min_severity.name}: {names}"
        ))

    unavailable = evaluation.unavailable_share
    if unavailable > float(policy["max_unavailable_share"]):
        return VerdictDecision(Verdict.INSUFFICIENT_DISCLOSURE, (
            f"{unavailable:.0%} of the applicable playbook could not be evaluated (ceiling "
            f"{float(policy['max_unavailable_share']):.0%}) — the inputs are public by law, so the gap "
            "is the finding"
        ))
    if notes.coverage < 1.0:
        return VerdictDecision(Verdict.INSUFFICIENT_DISCLOSURE, (
            f"notes-to-accounts coverage {notes.coverage:.0%} < 100% "
            f"(undispositioned: {list(notes.undispositioned) or 'unlisted'})"
        ))
    if notes.substantive_share < float(policy["min_note_review_share"]):
        return VerdictDecision(Verdict.INSUFFICIENT_DISCLOSURE, (
            f"only {notes.substantive_share:.0%} of {notes.notes_total} notes carry a substantive "
            f"disposition (floor {float(policy['min_note_review_share']):.0%}); the rest are 'unknown', "
            "which is coverage without reading"
        ))

    if feasibility is None:
        return VerdictDecision(Verdict.WATCH, (
            "the §6.3 feasibility gate could not run (ROIC not derivable from disclosed figures), so no "
            "compounding claim is provable yet"
        ))
    if feasibility.verdict in (GateVerdict.HARD_FAIL, GateVerdict.NEEDS_EXTERNAL_FUNDING):
        return VerdictDecision(Verdict.QUALITY_WRONG_PRICE, (
            f"forensically clean, but the feasibility gate returned {feasibility.verdict.value}: "
            f"{feasibility.rationale}"
        ))
    if history_years < min_history_years:
        return VerdictDecision(Verdict.WATCH, (
            f"only {history_years}y of history (floor {min_history_years}y) — structural promise, thesis "
            "not yet provable"
        ))
    return VerdictDecision(Verdict.COMPOUNDER, (
        f"clean on every check that could run, notes fully dispositioned, and the feasibility gate "
        f"returned {feasibility.verdict.value}: {feasibility.rationale}"
    ))


def _lowest_grade(citations: Sequence[Citation]) -> Grade:
    seen = {c.grade for c in citations}
    for grade in reversed(_GRADE_ORDER):
        if grade in seen:
            return grade
    return Grade.D


def load_bearing_points(
    graph: EvidenceGraph, load_bearing_ids: Sequence[str]
) -> list[ReportClaim]:
    """The report's headline claims, taken from the graph's promoted claims (never re-chosen here).

    Using the same ids the evidence graph marked load-bearing is what keeps R1 and the report honest
    about each other: what the report headlines is exactly what the invariant checked.
    """
    out: list[ReportClaim] = []
    for cid in load_bearing_ids:
        claim = graph.claims.get(cid)
        if claim is None:
            continue
        citations = [graph.evidence[e].citation for e in claim.supporting if e in graph.evidence]
        out.append(ReportClaim(
            text=claim.statement,
            kind=claim.kind.value,
            lowest_grade=_lowest_grade(citations),
            citations=citations,
        ))
    return out


def report_confidence(
    graph: EvidenceGraph, evaluation: CheckEvaluation, notes: NotesReview
) -> Confidence:
    """Numeric confidence justified by what was actually evidenced, not by tone (house style §5).

    Starts from the share of the applicable playbook that could be evaluated, is scaled by the share of
    notes read substantively, and is capped by the weakest grade the graph relies on. A report resting on
    grade C/D cannot claim high confidence however many claims it stacks up.
    """
    evaluated = 1.0 - evaluation.unavailable_share
    grades = {e.citation.grade for e in graph.evidence.values()}
    lowest = _lowest_grade([e.citation for e in graph.evidence.values()]) if grades else Grade.D
    cap = {Grade.A: 0.90, Grade.B: 0.75, Grade.C: 0.55, Grade.D: 0.40}[lowest]
    value = min(cap, round(evaluated * (0.5 + 0.5 * notes.substantive_share), 2))
    return Confidence(
        value=max(0.0, min(1.0, value)),
        evidence_count=len(graph.evidence),
        lowest_grade_relied_on=lowest,
        rationale=(
            f"{evaluated:.0%} of the applicable playbook was evaluable, "
            f"{notes.substantive_share:.0%} of notes carry a substantive disposition, and the weakest "
            f"grade relied on is {lowest.value} (cap {cap:.2f})"
        ),
    )


def build_checklist(
    evaluation: CheckEvaluation, models: Sequence[BusinessModel], notes: NotesReview
) -> VerifiedCleanChecklist:
    """The credibility backbone: every expected check, its outcome, and the notes-coverage proof."""
    return VerifiedCleanChecklist(
        business_models=[m.value for m in models],
        expected_checks=list(evaluation.expected),
        records=list(evaluation.records),
        note_coverage=notes.coverage,
        notes_undispositioned=list(notes.undispositioned),
        disclosure_gaps=list(notes.disclosure_gaps),
    )


def _unavailable_items(evaluation: CheckEvaluation) -> list[str]:
    return [
        f"{r.name}: {r.reason}"
        for r in evaluation.records
        if r.outcome is CheckOutcome.UNAVAILABLE
    ]


@dataclass(frozen=True)
class Narration:
    """Everything an agent is allowed to contribute. Prose only — every number here came from code."""

    executive_summary: str = ""
    business_model_plain: str = ""
    forensic_narrative: str = ""
    management_narrative: str = ""
    valuation_narrative: str = ""
    thesis: str = ""
    anti_thesis: str = ""
    open_questions: tuple[str, ...] = ()
    replication_notes: tuple[str, ...] = ()


def assemble_report(
    *,
    ticker: str,
    company_name: str,
    as_of: date,
    run_id: str,
    decision: VerdictDecision,
    derived: DerivedSet,
    evaluation: CheckEvaluation,
    models: Sequence[BusinessModel],
    notes: NotesReview,
    graph: EvidenceGraph,
    load_bearing_ids: Sequence[str],
    narration: Narration,
    agent_versions: Mapping[str, str],
    forensic: Mapping[str, Any],
    policy: Mapping[str, Any],
    feasibility: FeasibilityResult | None = None,
    self_fund_ceiling: float = 1.0,
) -> ResearchReport:
    """Build the report object. Publication gates run separately (`core/report/render.write_report`).

    Criteria are attached by verdict class, not by taste: positives get kill criteria, negatives get
    rehabilitation criteria (ADR-0016 symmetry, enforced by the P2 validator).
    """
    checklist = build_checklist(evaluation, models, notes)
    computed = {name: d.value for name, d in derived.values.items()}
    citations = {name: d.citation for name, d in derived.values.items()}

    report = ResearchReport(
        ticker=ticker,
        company_name=company_name,
        as_of=as_of,
        run_id=run_id,
        verdict=decision.verdict,
        confidence=report_confidence(graph, evaluation, notes),
        agent_versions=dict(agent_versions),
        executive_summary=narration.executive_summary,
        load_bearing_points=load_bearing_points(graph, load_bearing_ids),
        business_model_plain=narration.business_model_plain,
        computed_facts=computed,
        fact_citations=citations,
        checklist=checklist,
        forensic_narrative=narration.forensic_narrative,
        management_narrative=narration.management_narrative,
        valuation_narrative=narration.valuation_narrative,
        thesis=narration.thesis,
        anti_thesis=narration.anti_thesis,
        open_questions=list(dict.fromkeys(narration.open_questions)),
        replication_notes=list(narration.replication_notes),
        unavailable_items=_unavailable_items(evaluation),
    )

    if report.is_positive:
        report.kill_criteria = kill_criteria(
            derived, forensic=forensic, policy=policy, as_of=as_of)
    else:
        report.rehabilitation_criteria = rehabilitation_criteria(
            derived, checklist, forensic=forensic, policy=policy, as_of=as_of,
            feasibility=feasibility, self_fund_ceiling=self_fund_ceiling)
        # A withheld verdict still needs its tripwires stated: if the case rehabilitates, these are the
        # numbers that would then have to hold. Publishing them now stops a future upgrade being ad hoc.
        report.kill_criteria = kill_criteria(
            derived, forensic=forensic, policy=policy, as_of=as_of)

    # The verdict rationale is code-authored, so it belongs in the report body rather than in a log where
    # a reader could not check it.
    marker = f"**Verdict rationale (deterministic):** {decision.rationale}"
    report.executive_summary = (
        f"{report.executive_summary}\n\n{marker}" if report.executive_summary else marker
    )
    return report
