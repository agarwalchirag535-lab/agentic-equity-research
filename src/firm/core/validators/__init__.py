"""Blocking anti-hallucination validators (SPEC §9)."""

from firm.core.validators.arithmetic import ArithmeticCheck, all_ok, check
from firm.core.validators.citation import CitationProblem, validate
from firm.core.validators.consistency import Contradiction, MetricClaim, find_contradictions
from firm.core.validators.evidence_graph import (
    GraphViolation,
    dangling_references,
    lookahead_violations,
    numbers_without_provenance,
    refutation_cascade,
    unadjudicated_contradictions,
    unsupported_conclusions,
    validate_graph,
)
from firm.core.validators.hedge import find_hedges, has_hedges

__all__ = [
    "ArithmeticCheck",
    "CitationProblem",
    "Contradiction",
    "GraphViolation",
    "MetricClaim",
    "all_ok",
    "check",
    "dangling_references",
    "find_contradictions",
    "find_hedges",
    "has_hedges",
    "lookahead_violations",
    "numbers_without_provenance",
    "refutation_cascade",
    "unadjudicated_contradictions",
    "unsupported_conclusions",
    "validate",
    "validate_graph",
]
