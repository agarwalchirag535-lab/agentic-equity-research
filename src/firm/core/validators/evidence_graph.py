"""Evidence-graph invariants (FORENSIC_METHODOLOGY.md §4) — deterministic, blocking.

The graph is only worth building if illegal states cannot ship. These pure functions enforce the house
rules as hard invariants (SPEC §9 / Laws 1-3):

  R1  no load-bearing conclusion without a grade A/B supporting-evidence path;
  R2  a claim with refuting evidence must be explicitly adjudicated, never silently resolved;
  R3  every number-asserting piece of evidence must carry a fact id (provenance, Law 2);
  R4  a claim that depends on a REFUTED claim must be re-opened (refutation cascade);
  R5  no dangling references (a claim/edge pointing at a node that isn't in the graph);
  R6  point-in-time: no evidence with published_at after the run's as_of (look-ahead, Law 3).

No LLM decides validity; this is math over the graph. Empty result = clean.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from firm.schemas._base import Grade
from firm.schemas.evidence import ClaimStatus, EvidenceGraph

_STRONG_GRADES = frozenset({Grade.A, Grade.B})


@dataclass(frozen=True)
class GraphViolation:
    rule: str        # 'R1_unsupported' | 'R2_unadjudicated' | 'R3_no_provenance' | ...
    node_id: str
    detail: str


def unsupported_conclusions(graph: EvidenceGraph) -> list[GraphViolation]:
    """R1: a load-bearing claim must rest on at least one grade A or B piece of evidence."""
    out: list[GraphViolation] = []
    for cid, claim in graph.claims.items():
        if not claim.load_bearing:
            continue
        grades = {
            graph.evidence[e].citation.grade
            for e in claim.supporting
            if e in graph.evidence
        }
        if not (grades & _STRONG_GRADES):
            out.append(GraphViolation(
                "R1_unsupported", cid,
                "load-bearing claim has no grade-A/B support "
                f"(grades relied on: {sorted(g.value for g in grades) or 'none'})",
            ))
    return out


def unadjudicated_contradictions(graph: EvidenceGraph) -> list[GraphViolation]:
    """R2: a claim with refuting evidence must carry a non-empty adjudication note."""
    return [
        GraphViolation("R2_unadjudicated", cid,
                       f"{len(claim.refuting)} refuting item(s) but no adjudication")
        for cid, claim in graph.claims.items()
        if claim.refuting and not claim.adjudication.strip()
    ]


def numbers_without_provenance(graph: EvidenceGraph) -> list[GraphViolation]:
    """R3: number-asserting evidence must carry a fact id (Law 2)."""
    return [
        GraphViolation("R3_no_provenance", eid,
                       "evidence asserts a number but its citation has no fact_id")
        for eid, ev in graph.evidence.items()
        if ev.asserts_number and not ev.citation.fact_id.strip()
    ]


def refutation_cascade(graph: EvidenceGraph) -> list[GraphViolation]:
    """R4: a claim depending on a REFUTED claim must not still stand as SUPPORTED — re-open it."""
    out: list[GraphViolation] = []
    for cid, claim in graph.claims.items():
        for parent in claim.depends_on:
            p = graph.claims.get(parent)
            if p is not None and p.status is ClaimStatus.REFUTED and claim.status is ClaimStatus.SUPPORTED:
                out.append(GraphViolation(
                    "R4_cascade", cid,
                    f"claim is SUPPORTED but depends on refuted claim '{parent}' — must be re-opened",
                ))
    return out


def dangling_references(graph: EvidenceGraph) -> list[GraphViolation]:
    """R5: every referenced evidence/claim/entity id must exist in the graph."""
    out: list[GraphViolation] = []
    for cid, claim in graph.claims.items():
        for e in (*claim.supporting, *claim.refuting):
            if e not in graph.evidence:
                out.append(GraphViolation("R5_dangling", cid, f"references missing evidence '{e}'"))
        for parent in claim.depends_on:
            if parent not in graph.claims:
                out.append(GraphViolation("R5_dangling", cid, f"references missing claim '{parent}'"))
    for i, edge in enumerate(graph.edges):
        for end in (edge.src, edge.dst):
            if end not in graph.entities:
                out.append(GraphViolation("R5_dangling", f"edge[{i}]", f"references missing entity '{end}'"))
    return out


def lookahead_violations(graph: EvidenceGraph, as_of: date) -> list[GraphViolation]:
    """R6: no evidence may carry a published_at after the run's as_of (Law 3, point-in-time)."""
    return [
        GraphViolation("R6_lookahead", eid,
                       f"evidence published_at {ev.citation.published_at} is after as_of {as_of}")
        for eid, ev in graph.evidence.items()
        if ev.citation.published_at > as_of
    ]


def validate_graph(graph: EvidenceGraph, as_of: date | None = None) -> list[GraphViolation]:
    """Run every invariant. Empty list = the graph may ship. R6 runs only when an as_of is given."""
    violations = [
        *unsupported_conclusions(graph),
        *unadjudicated_contradictions(graph),
        *numbers_without_provenance(graph),
        *refutation_cascade(graph),
        *dangling_references(graph),
    ]
    if as_of is not None:
        violations += lookahead_violations(graph, as_of)
    return violations
