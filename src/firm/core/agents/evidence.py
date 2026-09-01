"""Agent output → `EvidenceGraph` fragment (Phase 2, ADR-0021). The wire STATUS.md §3A said was missing.

Before this module, agents returned schema-valid Pydantic objects and the evidence graph existed with six
blocking invariants — but nothing connected them, so no agent conclusion was ever actually held to R1-R6.
This is that connection, and it is deliberately **deterministic**: an LLM writes the claim text, but code
decides what the claim *counts as*.

Three rules do the work:

1. **A citation to an unknown `fact_id` is a hard failure, not a warning** (Law 2). The known-id set comes
   from the fact store and the run's derivations, so an agent that invents `[fact:whatever]` to dress up a
   sentence is caught here rather than in a published report. Returned as `FragmentProblem`s; the pipeline
   refuses to assemble a report while any exist.
2. **The epistemic split is preserved, never flattened.** `observations` → `ClaimKind.OBSERVATION`,
   `inferences` → `INFERENCE`, `speculations` → `SPECULATION` (house style §4). A speculation can never be
   promoted to load-bearing, whatever confidence the agent asserted.
3. **Load-bearing is earned, not claimed.** A claim is promoted only when it is an inference or
   observation, its stated confidence clears the config floor, and it has at least one grade A/B
   citation — which is exactly what R1 demands, so a promoted claim passes the invariant by construction
   instead of by luck.

Ids are namespaced by agent (`forensic_accountant:inference:2`) so fragments from three agents merge into
one graph without collision, and so a claim in a published report traces back to which agent asserted it.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from firm.schemas._base import AgentOutputBase, Claim, Grade
from firm.schemas.evidence import (
    ClaimKind,
    ClaimStatus,
    Evidence,
    EvidenceClaim,
    EvidenceGraph,
    SourceClass,
)

_STRONG_GRADES = frozenset({Grade.A, Grade.B})

#: Evidence grade → the source class it most plausibly belongs to (FORENSIC_METHODOLOGY §2 second axis).
#: A: audited filing, B: exchange filing, C: company presentation/concall, D: media/broker note.
GRADE_TO_SOURCE_CLASS: Mapping[Grade, SourceClass] = {
    Grade.A: SourceClass.BINDING_FILING,
    Grade.B: SourceClass.BINDING_FILING,
    Grade.C: SourceClass.THIRD_PARTY_DATA,
    Grade.D: SourceClass.MEDIA,
}

_KIND_BY_FIELD: Mapping[str, ClaimKind] = {
    "observations": ClaimKind.OBSERVATION,
    "inferences": ClaimKind.INFERENCE,
    "speculations": ClaimKind.SPECULATION,
}


@dataclass(frozen=True)
class FragmentProblem:
    """A Law-2 violation in an agent's output: a number cited to a fact that does not exist."""

    agent: str
    claim_id: str
    fact_id: str
    reason: str = "citation references a fact_id unknown to this run"


@dataclass(frozen=True)
class Fragment:
    """One agent's contribution to the graph, plus anything wrong with it."""

    agent: str
    agent_version: str
    graph: EvidenceGraph
    problems: tuple[FragmentProblem, ...]
    load_bearing_claim_ids: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.problems


def _claim_is_promotable(
    claim: Claim, kind: ClaimKind, min_confidence: float
) -> bool:
    """Load-bearing promotion rule. Speculation is never load-bearing, however confident it sounds."""
    if kind is ClaimKind.SPECULATION:
        return False
    if claim.confidence is None or claim.confidence.value < min_confidence:
        return False
    return any(c.grade in _STRONG_GRADES for c in claim.citations)


def build_fragment(
    output: AgentOutputBase,
    *,
    known_fact_ids: Iterable[str],
    min_confidence: float,
    max_load_bearing: int,
) -> Fragment:
    """Turn one validated agent output into an evidence-graph fragment.

    Evidence nodes are created per citation and keyed by `fact_id`, so two agents citing the same fact
    converge on the same evidence node when the fragments merge — which is what makes triangulation
    ("two independent agents rest on the same single fact") visible instead of implied.
    """
    known = set(known_fact_ids)
    graph = EvidenceGraph()
    problems: list[FragmentProblem] = []
    promoted: list[tuple[float, str]] = []

    for field, kind in _KIND_BY_FIELD.items():
        for index, claim in enumerate(getattr(output, field), start=1):
            claim_id = f"{output.agent}:{kind.value}:{index}"
            supporting: list[str] = []
            for citation in claim.citations:
                if citation.fact_id not in known:
                    problems.append(FragmentProblem(output.agent, claim_id, citation.fact_id))
                    continue
                evidence_id = f"ev:{citation.fact_id}"
                if evidence_id not in graph.evidence:
                    graph.evidence[evidence_id] = Evidence(
                        id=evidence_id,
                        summary=f"{citation.doc_id} {citation.locator}",
                        source_class=GRADE_TO_SOURCE_CLASS[citation.grade],
                        citation=citation,
                        asserts_number=True,
                    )
                if evidence_id not in supporting:
                    supporting.append(evidence_id)

            promotable = _claim_is_promotable(claim, kind, min_confidence)
            graph.claims[claim_id] = EvidenceClaim(
                id=claim_id,
                statement=claim.text,
                kind=kind,
                status=ClaimStatus.SUPPORTED if supporting else ClaimStatus.UNKNOWN,
                load_bearing=False,          # set below, after ranking by confidence
                supporting=supporting,
                confidence=claim.confidence,
                open_questions=list(output.open_questions),
                replication=(
                    f"re-read {', '.join(c.doc_id + ' ' + c.locator for c in claim.citations)} "
                    f"as-of {output.as_of.isoformat()} and recompute with core/compute"
                ) if claim.citations else "",
            )
            if promotable:
                promoted.append((claim.confidence.value, claim_id))

    # Highest-confidence claims first; cap so a report cannot rest on twenty "load-bearing" points.
    promoted.sort(key=lambda pair: (-pair[0], pair[1]))
    load_bearing = tuple(cid for _, cid in promoted[:max_load_bearing])
    for cid in load_bearing:
        graph.claims[cid] = graph.claims[cid].model_copy(update={"load_bearing": True})

    return Fragment(output.agent, output.agent_version, graph, tuple(problems), load_bearing)


def merge_graphs(graphs: Sequence[EvidenceGraph]) -> EvidenceGraph:
    """Union fragments into one graph. Later nodes never silently overwrite earlier ones.

    Claim ids are agent-namespaced so a collision means the same agent ran twice — which is a caller bug,
    not something to paper over. Evidence keyed by fact_id is expected to collide, and converging on one
    node is the point: it makes shared dependence on a single fact visible to R1.
    """
    merged = EvidenceGraph()
    for graph in graphs:
        for cid, claim in graph.claims.items():
            if cid in merged.claims:
                raise ValueError(f"duplicate claim id across fragments: {cid!r}")
            merged.claims[cid] = claim
        for eid, evidence in graph.evidence.items():
            merged.evidence.setdefault(eid, evidence)
        for eid, entity in graph.entities.items():
            merged.entities.setdefault(eid, entity)
        merged.edges.extend(graph.edges)
    return merged


def cap_load_bearing(
    graph: EvidenceGraph, candidate_ids: Sequence[str], max_points: int
) -> tuple[str, ...]:
    """Reduce per-agent promotions to ONE report-wide set, and demote the rest **in the graph**.

    Each fragment promotes up to `max_points` claims on its own, so three agents could arrive with nine
    "load-bearing" points — which would make the phrase meaningless and let a report stack weak claims
    into apparent strength. Two corrections, both in place:

    * duplicate statements collapse (three agents restating one metric is one point, not three);
    * only the highest-confidence `max_points` survive; everything else is demoted in the graph itself, so
      the R1 invariant and the published headline claims describe the same set.
    """
    ranked: list[tuple[float, str]] = []
    seen_statements: set[str] = set()
    for cid in candidate_ids:
        claim = graph.claims.get(cid)
        if claim is None:
            continue
        key = claim.statement.strip().lower()
        if key in seen_statements:
            continue
        seen_statements.add(key)
        ranked.append((claim.confidence.value if claim.confidence else 0.0, cid))

    ranked.sort(key=lambda pair: (-pair[0], pair[1]))
    kept = tuple(cid for _, cid in ranked[:max_points])
    for cid, claim in graph.claims.items():
        should_be = cid in kept
        if claim.load_bearing != should_be:
            graph.claims[cid] = claim.model_copy(update={"load_bearing": should_be})
    return kept


def all_problems(fragments: Sequence[Fragment]) -> tuple[FragmentProblem, ...]:
    return tuple(p for f in fragments for p in f.problems)
