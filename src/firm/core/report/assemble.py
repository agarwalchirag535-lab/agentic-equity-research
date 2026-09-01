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

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from firm.core.compute.models import BusinessModel
from firm.core.compute.multibagger import FeasibilityResult, GateVerdict
from firm.core.compute.quality import ForensicScreenResult, Severity
from firm.core.pipeline.checks import CheckEvaluation
from firm.core.pipeline.derive import DerivedSet
from firm.core.pipeline.interrogate import Interrogation
from firm.core.report.criteria import kill_criteria, rehabilitation_criteria
from firm.schemas._base import Citation, Confidence, Grade
from firm.schemas.evidence import EvidenceGraph
from firm.schemas.report import (
    AnswerStatus,
    CheckOutcome,
    GapKind,
    LineItemAnswer,
    LineItemSection,
    ReportClaim,
    ResearchReport,
    RestatementLine,
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
    undispositioned: tuple[str, ...] = ()
    substantive_share: float = 0.0
    notes_total: int = 0
    disclosure_gaps: tuple[str, ...] = ()
    scanned: bool = False
    #: Note numbers missing from the filed sequence — notes that exist and the enumerator could not see.
    #: `coverage` measures dispositions against the notes we FOUND, so it reads 100% while a note is
    #: invisible; that is how the contingent-liabilities note went unread behind a perfect score
    #: (ADR-0045). A CAPABILITY gap: it lowers our confidence, never the company's verdict.
    unenumerated: tuple[int, ...] = ()


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
    interrogation: Interrogation | None = None,
    # Deliberately takes NO `coverage_gaps`. An agent the firm could not staff must never move the verdict
    # (ADR-0019); those gaps go to `assemble_report` so a reader sees them, and no further.
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

    # ONLY the company's own non-disclosure may produce this verdict (ADR-0051). The share of checks we
    # simply cannot run yet is our limitation: it lowers confidence and is printed as ours, but it must
    # never be published as an accusation. CreditAccess Grameen — a lender that discloses its asset
    # quality in full — was headed for INSUFFICIENT_DISCLOSURE over notes this firm does not read, with
    # the rationale "the inputs are public by law, so the gap is the finding". That sentence would have
    # been false about the company and true about us.
    undisclosed = evaluation.disclosure_gap_share
    if undisclosed > float(policy["max_unavailable_share"]):
        names = ", ".join(r.name for r in evaluation.applicable
                          if r.gap is GapKind.DISCLOSURE) or "unnamed"
        return VerdictDecision(Verdict.INSUFFICIENT_DISCLOSURE, (
            f"{undisclosed:.0%} of the applicable playbook was looked for and not disclosed (ceiling "
            f"{float(policy['max_unavailable_share']):.0%}) — the inputs are public by law, so the gap "
            f"is the finding: {names}"
        ))
    # Same rule for the notes (ADR-0051). Notes we never opened are not notes the company withheld: if
    # no filing was walked at all, `scanned` is False and this rung has nothing to say about the company.
    if notes.scanned and notes.coverage < 1.0:
        return VerdictDecision(Verdict.INSUFFICIENT_DISCLOSURE, (
            f"notes-to-accounts coverage {notes.coverage:.0%} < 100% "
            f"(undispositioned: {list(notes.undispositioned) or 'unlisted'})"
        ))
    # Also gated on `scanned` (ADR-0051): "0% of 0 notes carry a substantive disposition" is a sentence
    # about a filing nobody opened, and publishing it as the company's opacity is the same false claim.
    # Before judging the business at all: did the firm actually look at enough of it? This rung is about
    # US and says so (ADR-0051). It sits after the disclosure rungs so a company that IS opaque is still
    # reported as opaque, and before every rung that asserts something about the business, so a thesis is
    # never published off a playbook that barely ran.
    if evaluation.unavailable_share > float(policy["max_unavailable_share"]):
        mine = ", ".join(r.name for r in evaluation.applicable if r.gap is GapKind.CAPABILITY)
        return VerdictDecision(Verdict.INSUFFICIENT_EVIDENCE, (
            f"{evaluation.unavailable_share:.0%} of the applicable playbook could not be evaluated "
            f"(ceiling {float(policy['max_unavailable_share']):.0%}), and "
            f"{evaluation.capability_gap_share:.0%} of it for want of this firm's own reach rather than "
            f"the company's disclosure — no judgment about the business is supportable yet: {mine}"
        ))

    if notes.scanned and notes.substantive_share < float(policy["min_note_review_share"]):
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

    # Line-by-line sufficiency (ADR-0022), and its position in the ladder is load-bearing.
    #
    # It sits BELOW the short-history rung deliberately: a three-year-old company cannot have a three-year
    # incremental return on capital, and calling that a disclosure failure would punish a young business
    # for its age. ADR-0008 says short history is routed to WATCH, never dropped, so WATCH must be reached
    # first. What remains here is the real case — a company with the history, clean checks and a passing
    # feasibility gate whose *business* is still unread: revenue undecomposed, buyers unknown,
    # related-party flows unseen. A thesis on that is a thesis about a ratio table.
    #
    # Only DISCLOSURE gaps are consulted. CAPABILITY gaps (no extractor written yet) are excluded on
    # purpose: charging a company for our unfinished note-parser would reject every good business we
    # cannot yet read and call it rigour. Those lower `report_confidence` instead — the honest place for
    # "we know less" as opposed to "they disclosed less".
    if interrogation is not None:
        ceiling = int(policy["max_unanswered_high_line_items"])
        blocking = interrogation.undisclosed_high
        if len(blocking) > ceiling:
            named = ", ".join(f"{a.line_item}.{a.question_id}" for a in blocking[:5])
            return VerdictDecision(Verdict.INSUFFICIENT_DISCLOSURE, (
                f"{len(blocking)} high-severity line-item question(s) put to the filings and unanswerable "
                f"from them (ceiling {ceiling}), line-by-line coverage {interrogation.coverage:.0%}: "
                f"{named}{' …' if len(blocking) > 5 else ''} — the ratios are clean but the business is "
                "unread"
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
    graph: EvidenceGraph,
    evaluation: CheckEvaluation,
    notes: NotesReview,
    interrogation: Interrogation | None = None,
) -> Confidence:
    """Numeric confidence justified by what was actually evidenced, not by tone (house style §5).

    Starts from the share of the applicable playbook that could be evaluated, is scaled by the share of
    notes read substantively, scaled again by line-by-line coverage, and capped by the weakest grade the
    graph relies on. A report resting on grade C/D cannot claim high confidence however many claims it
    stacks up.

    Line-item coverage enters *here* rather than in the verdict on purpose (ADR-0022). A question we never
    built the extractor for is a limit on what this report knows, not a fact about the company — so it
    belongs in a graded number that says "we know less", never in a categorical judgment that says "they
    disclosed less".
    """
    evaluated = 1.0 - evaluation.unavailable_share
    grades = {e.citation.grade for e in graph.evidence.values()}
    lowest = _lowest_grade([e.citation for e in graph.evidence.values()]) if grades else Grade.D
    cap = {Grade.A: 0.90, Grade.B: 0.75, Grade.C: 0.55, Grade.D: 0.40}[lowest]
    # Coverage damps rather than dominates: half weight, so a thorough forensic pass on a partly-read set
    # of lines still earns a usable number instead of collapsing to zero.
    line_cover = interrogation.coverage if interrogation is not None else 1.0
    value = min(cap, round(evaluated * (0.5 + 0.5 * notes.substantive_share)
                           * (0.5 + 0.5 * line_cover), 2))
    return Confidence(
        value=max(0.0, min(1.0, value)),
        evidence_count=len(graph.evidence),
        lowest_grade_relied_on=lowest,
        rationale=(
            f"{evaluated:.0%} of the applicable playbook was evaluable, "
            f"{notes.substantive_share:.0%} of notes carry a substantive disposition, "
            f"{line_cover:.0%} of the line-by-line questions could be answered, and the weakest "
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
        notes_unenumerated=list(notes.unenumerated),
        notes_undispositioned=list(notes.undispositioned),
        disclosure_gaps=list(notes.disclosure_gaps),
    )


def build_line_items(interrogation: Interrogation | None) -> list[LineItemSection]:
    """Project the line-by-line interrogation onto the report contract (ADR-0022).

    Straight projection, deliberately: every judgment already happened in `interrogate.py` against
    thresholds in `config/line_items.yaml`, so there is nowhere here for a second opinion to creep in.
    """
    if interrogation is None:
        return []
    return [
        LineItemSection(
            line_item=d.line_item,
            label=d.label,
            why=d.why,
            coverage=d.coverage,
            answers=[
                LineItemAnswer(
                    question_id=a.question_id,
                    question=a.question,
                    status=AnswerStatus(a.status.value),
                    severity=a.severity,
                    gap=GapKind(a.gap.value),
                    finding=a.finding,
                    metric=a.metric,
                    value=a.value,
                    citation=a.citation,
                    fact_ids=list(a.fact_ids),
                    needs=list(a.needs),
                    reason=a.reason,
                )
                for a in d.answers
            ],
        )
        for d in interrogation.dossiers
    ]


def _unavailable_items(
    evaluation: CheckEvaluation, coverage_gaps: Sequence[str] = ()
) -> list[str]:
    """Everything this run could not establish: the company's non-disclosure AND our own coverage holes.

    Both belong in one section because a reader needs a single place to see what is unestablished — but
    they are phrased so the distinction survives (ADR-0019). A check whose inputs the company did not
    disclose reads as a disclosure gap; an agent that never ran says in its own words that the gap is
    OURS. Only the first kind may move a verdict, and a report that showed the second as a company failing
    would be charging a company for the firm's missing extractor.
    """
    return [
        f"{r.name}: {r.reason}"
        for r in evaluation.records
        if r.outcome is CheckOutcome.UNAVAILABLE
    ] + list(coverage_gaps)


@dataclass(frozen=True)
class Narration:
    """Everything an agent is allowed to contribute. Prose only — every number here came from code."""

    executive_summary: str = ""
    business_model_plain: str = ""
    forensic_narrative: str = ""
    sector_narrative: str = ""
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
    interrogation: Interrogation | None = None,
    #: Agents the roster planned but could not staff (ADR-0030/0033). Published as the
    #: FIRM's gaps, never as the company's, and they reach no verdict.
    coverage_gaps: Sequence[str] = (),
    #: Quiet revisions between visible filings (`restatement_log`), rendered as their own section.
    restatements: Sequence[Any] = (),
) -> ResearchReport:
    """Build the report object. Publication gates run separately (`core/report/render.write_report`).

    Criteria are attached by verdict class, not by taste: positives get kill criteria, negatives get
    rehabilitation criteria (ADR-0016 symmetry, enforced by the P2 validator).
    """
    # Imported here, not at module scope: `questions` needs `NotesReview` from this module, so a
    # top-level import would close the cycle. The alternative — moving NotesReview into a third module —
    # would touch a dozen import sites to save one deferred import.
    from firm.core.report.questions import management_questions

    checklist = build_checklist(evaluation, models, notes)
    computed = {name: d.value for name, d in derived.values.items()}
    citations = {name: d.citation for name, d in derived.values.items()}

    report = ResearchReport(
        ticker=ticker,
        company_name=company_name,
        as_of=as_of,
        run_id=run_id,
        verdict=decision.verdict,
        confidence=report_confidence(graph, evaluation, notes, interrogation),
        agent_versions=dict(agent_versions),
        executive_summary=narration.executive_summary,
        load_bearing_points=load_bearing_points(graph, load_bearing_ids),
        business_model_plain=narration.business_model_plain,
        computed_facts=computed,
        fact_citations=citations,
        line_items=build_line_items(interrogation),
        line_item_coverage=interrogation.coverage if interrogation else 0.0,
        disclosure_backlog=list(interrogation.needs_index()) if interrogation else [],
        checklist=checklist,
        forensic_narrative=narration.forensic_narrative,
        sector_narrative=narration.sector_narrative,
        management_narrative=narration.management_narrative,
        valuation_narrative=narration.valuation_narrative,
        thesis=narration.thesis,
        anti_thesis=narration.anti_thesis,
        open_questions=list(dict.fromkeys(narration.open_questions)),
        # ADR-0066: computed on EVERY report, from the same records the verdict rests on. Not narration
        # — an agent cannot add to this list or remove from it.
        management_questions=management_questions(evaluation, notes, interrogation),
        replication_notes=list(narration.replication_notes),
        unavailable_items=_unavailable_items(evaluation, coverage_gaps),
        restatements=[
            RestatementLine(metric=r.metric, period=r.period,
                            earlier_doc=r.earlier_doc, earlier_value=r.earlier_value,
                            later_doc=r.later_doc, later_value=r.later_value)
            for r in restatements
        ],
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
