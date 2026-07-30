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
    "ArithmeticCheck", "all_ok", "check",
    "CitationProblem", "validate",
    "Contradiction", "MetricClaim", "find_contradictions",
    "GraphViolation", "validate_graph", "unsupported_conclusions",
    "unadjudicated_contradictions", "numbers_without_provenance", "refutation_cascade",
    "dangling_references", "lookahead_violations",
    "find_hedges", "has_hedges",
]
