"""Shared schema primitives inherited by every agent output (Laws 2 & 4).

Kept in one place so provenance and the observation/inference/speculation split are not copy-pasted
into 14 agent schemas. These are Pydantic models — agent outputs compose them.
"""

from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel, Field


class Grade(str, Enum):
    """Source reliability grade (SPEC §4). A thesis pillar may not rest on D alone."""

    A = "A"  # audited filing
    B = "B"  # exchange filing / rating rationale
    C = "C"  # company presentation / concall claim
    D = "D"  # media / broker note


class Citation(BaseModel):
    """Every numeric claim renders with one of these; a validator maps it to a fact (Law 2)."""

    fact_id: str
    doc_id: str
    locator: str = Field(description="page/paragraph within the source document")
    published_at: date
    extractor_version: str
    grade: Grade


class Confidence(BaseModel):
    """Numeric confidence, justified by evidence — never vibes (house style §5)."""

    value: float = Field(ge=0.0, le=1.0)
    evidence_count: int = Field(ge=0)
    lowest_grade_relied_on: Grade
    rationale: str


class Claim(BaseModel):
    """A single assertion tagged by epistemic status and cited."""

    text: str
    kind: str = Field(description="one of: observation | inference | speculation (house style §4)")
    citations: list[Citation] = Field(default_factory=list)
    confidence: Confidence | None = None


class AgentOutputBase(BaseModel):
    """Base every agent output extends. Prose lives in `narrative`, never as the return value (Law 4)."""

    agent: str
    agent_version: str
    ticker: str
    as_of: date
    observations: list[Claim] = Field(default_factory=list)
    inferences: list[Claim] = Field(default_factory=list)
    speculations: list[Claim] = Field(default_factory=list)
    open_questions: list[str] = Field(
        default_factory=list,
        description="An empty array is suspicious (house style §3).",
    )
    disconfirming_search: str = Field(
        description="What evidence against the emerging conclusion was sought, and what was found."
    )
    narrative: str = ""
