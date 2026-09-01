"""The publication ladder: the gates stay blocking, and an owner-chosen company still gets an artifact.

ADR-0064 separated research eligibility from investment verdict — a company is never refused a report
for looking bad. ADR-0065 closes the hole that was left on the FIRM's side of that promise: until now a
run whose publication gates (P1-P4) or evidence-graph invariants (R1-R6) failed returned a debuggable
object and wrote nothing to disk, so the answer to "research this company" could be silence.

Silence is the one outcome that is never honest. The fix is emphatically NOT to relax a gate: every
gate polices the firm's own claims, and lowering one to make an artifact appear would trade honesty
for completeness, which the invariants forbid. The fix is to publish something the gates already
accept — strictly *less* assertion — and to carry the record of what was withheld, and why, on the
artifact itself.

The ladder, stopping at the first rung that validates:

1. **As assembled.** The gates passed; nothing to do.
2. **Supplemented.** The agents' prose stands and the deterministic layer fills what the gates found
   missing (an absent anti-thesis, no replication notes). The analysts' work survives a gate failure
   instead of being thrown away with it.
3. **Verdict withheld.** The judgment drops to INSUFFICIENT_EVIDENCE — "we could not look hard enough
   to judge", which is precisely true when the firm's own gates refuse its report — while the
   narration stands. The deterministic checklist is untouched and still carries every FLAG, so a
   withheld verdict can never bury a red flag.
4. **Deterministic floor.** No agent narration, no evidence graph, verdict withheld. This is the
   report the firm can always write: every part of it is code-authored from records carrying their own
   fact ids, so it cannot violate a citation or framing gate.
5. **Forced.** If even the floor fails a gate, the floor is written anyway with the residual rules
   named on the artifact. This should never fire; it exists so the failure is visible instead of
   silent.

Degrading never *improves* a verdict: every rung asserts less than the one above it. A run that
reached FORENSIC_CAUTION cannot be talked up by this module, only quietened to "we withheld judgment"
— and even then the flags stay in the checklist, in the anti-thesis and in the open questions.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date

from firm.core.report.assemble import Narration, VerdictDecision
from firm.core.report.narration import merge_narration
from firm.core.validators.evidence_graph import GraphViolation, validate_graph
from firm.core.validators.publication import PublicationViolation, validate_report
from firm.schemas.evidence import EvidenceGraph
from firm.schemas.report import ResearchReport, Verdict


def _rules(
    publication: Sequence[PublicationViolation], graph: Sequence[GraphViolation]
) -> tuple[str, ...]:
    return tuple(dict.fromkeys([v.rule for v in publication] + [v.rule for v in graph]))


def publish_or_degrade(
    *,
    assemble: Callable[..., ResearchReport],
    as_of: date,
    report: ResearchReport,
    decision: VerdictDecision,
    publication_violations: Sequence[PublicationViolation],
    graph_violations: Sequence[GraphViolation],
    agent_narration: Narration,
    fallback_narration: Narration,
    graph: EvidenceGraph,
    load_bearing_ids: Sequence[str],
    coverage_gaps: Sequence[str] = (),
) -> tuple[ResearchReport, tuple[str, ...], tuple[str, ...]]:
    """Return the report that should be written, the degradation record, and any residual rules.

    `assemble` is `assemble_report` with everything run-constant already bound; this function varies
    only `decision`, `narration`, `graph`, `load_bearing_ids` and `coverage_gaps`.

    An empty degradation record means rung 1 — the report is exactly what the run assembled. A
    non-empty one is published *in the report* as a coverage gap, because a reader who cannot tell a
    degraded report from a full one has been misled by omission.
    """
    blocked = _rules(publication_violations, graph_violations)
    if not blocked:
        return report, (), ()

    def attempt(
        *, decision_: VerdictDecision, narration: Narration, graph_: EvidenceGraph,
        ids: Sequence[str], note: str,
    ) -> tuple[ResearchReport, tuple[str, ...]]:
        candidate = assemble(
            decision=decision_, narration=narration, graph=graph_, load_bearing_ids=ids,
            coverage_gaps=tuple(coverage_gaps) + (note,),
        )
        return candidate, _rules(validate_report(candidate), validate_graph(graph_, as_of))

    listed = ", ".join(blocked)
    supplemented = merge_narration(agent_narration, fallback_narration)

    # Rung 2 — the gates found a hole the deterministic layer can fill. Verdict and analysis intact.
    note = (
        f"Publication gate(s) {listed} refused the report as first assembled; the deterministic layer "
        f"supplied the missing section(s). The analysts' narration and the verdict are unchanged."
    )
    candidate, residual = attempt(
        decision_=decision, narration=supplemented, graph_=graph, ids=load_bearing_ids, note=note)
    if not residual:
        return candidate, (note,), ()

    # Rung 3 — the verdict itself is what the gates will not carry. Withhold the judgment, keep the
    # evidence. The original verdict is NAMED so that nothing is buried by the downgrade.
    withheld = VerdictDecision(
        verdict=Verdict.INSUFFICIENT_EVIDENCE,
        rationale=(
            f"the deterministic ladder reached {decision.verdict.value} ({decision.rationale}), but "
            f"the firm's own publication gates refused that report ({listed}); the judgment is "
            f"therefore withheld. This is a limit of this run, not a finding about the company — the "
            f"checklist below is unchanged and still carries every check that flagged."
        ),
    )
    note = (
        f"Publication gate(s) {listed} refused the {decision.verdict.value} verdict; it is withheld as "
        f"INSUFFICIENT_EVIDENCE. Every deterministic check, flag and disclosure gap is unaffected and "
        f"still reported below."
    )
    candidate, residual = attempt(
        decision_=withheld, narration=supplemented, graph_=graph, ids=load_bearing_ids, note=note)
    if not residual:
        return candidate, (note,), ()

    # Rung 4 — the narration or the evidence graph is the problem. Publish the report the firm can
    # always write: code-authored throughout, no agent claims, no verdict asserted.
    note = (
        f"Publication gate(s) {listed} could not be satisfied with the agents' narration, so this is "
        f"the deterministic report: no agent prose and no agent claims, verdict withheld as "
        f"INSUFFICIENT_EVIDENCE. The agents that ran are still named in `agent_versions`; their "
        f"narration was withheld by the firm, not absent."
    )
    candidate, residual = attempt(
        decision_=withheld, narration=fallback_narration, graph_=EvidenceGraph(), ids=(), note=note)
    if not residual:
        return candidate, (note,), ()

    # Rung 5 — should never happen. Write the floor anyway; an artifact that names its own failure is
    # more honest than no artifact at all, which is the one thing ADR-0064 forbids.
    residual_note = (
        f"THIS REPORT FAILS THE FIRM'S OWN PUBLICATION GATES ({', '.join(residual)}) and is published "
        f"only because an owner-requested company is never left without an artifact (ADR-0064). Treat "
        f"every conclusion in it as unverified by the firm's standards."
    )
    candidate = assemble(
        decision=withheld, narration=fallback_narration, graph=EvidenceGraph(), load_bearing_ids=(),
        coverage_gaps=tuple(coverage_gaps) + (note, residual_note),
    )
    return candidate, (note, residual_note), residual
