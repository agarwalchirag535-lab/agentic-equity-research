"""Structured output contracts (Law 4)."""

from firm.schemas._base import AgentOutputBase, Citation, Claim, Confidence, Grade
from firm.schemas.agents import AGENT_OUTPUTS
from firm.schemas.evidence import (
    ClaimKind,
    ClaimStatus,
    Entity,
    Evidence,
    EvidenceClaim,
    EvidenceEdge,
    EvidenceGraph,
    SourceClass,
)

__all__ = [
    "AgentOutputBase", "Citation", "Claim", "Confidence", "Grade", "AGENT_OUTPUTS",
    # evidence graph
    "ClaimKind", "ClaimStatus", "Entity", "Evidence", "EvidenceClaim", "EvidenceEdge",
    "EvidenceGraph", "SourceClass",
]
