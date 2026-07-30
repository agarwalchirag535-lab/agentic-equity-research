"""Evidence graph — the claim ↔ evidence ↔ entity data model (FORENSIC_METHODOLOGY.md §4).

Turns triangulation into an auditable structure and makes "no unsupported conclusion" enforceable by a
validator instead of by good intentions. Composes the shared primitives in ``schemas/_base.py`` (Grade,
Citation, Confidence) rather than re-declaring them, so Laws 2 & 3 (provenance, point-in-time) come for
free on every evidence node.

This module is pure data (Pydantic). The blocking invariants live in
``core/validators/evidence_graph.py`` and are deterministic (Law 1) — no LLM decides whether a graph is
valid.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from firm.schemas._base import Citation, Confidence


class SourceClass(str, Enum):
    """Second axis beside Grade (FORENSIC_METHODOLOGY §2). *What kind* of source, orthogonal to *how
    reliable*. Government/public records and directly-observed ground truth outrank issuer filings on
    conflict because the target did not author them and they are independently replicable."""

    BINDING_FILING = "binding_filing"          # issuer-authored: 10-K/AR, proxy, trust report
    PUBLIC_RECORD = "public_record"            # gov/registry/court/UCC — target cannot retract
    THIRD_PARTY_DATA = "third_party_data"      # Morningstar/S&P, price/index, Form-4 aggregators
    LITIGATION = "litigation"                  # complaint/exhibit — allegation, not finding
    FOIA_INTEL = "foia_intel"                  # FOIA / regulatory-intelligence, second-hand
    HUMINT_INSIDER = "humint_insider"          # former employee/director — intent/mechanism only
    HUMINT_COUNTERPARTY = "humint_counterparty"  # counterparty/competitor
    GROUND_TRUTH = "ground_truth"              # directly observed: product/site/count
    COMPLAINT_CORPUS = "complaint_corpus"      # BBB/Trustpilot/Reddit/CFPB — D alone, C in aggregate
    WEB_ARCHIVE = "web_archive"                # Wayback etc., timestamped
    MEDIA = "media"


class ClaimKind(str, Enum):
    """House-style observation / inference / speculation split (epistemics.md), never blended."""

    OBSERVATION = "observation"
    INFERENCE = "inference"
    SPECULATION = "speculation"


class ClaimStatus(str, Enum):
    """Three states, never two (epistemics.md). 'unknown' is a first-class, often-correct answer."""

    SUPPORTED = "supported"
    REFUTED = "refuted"
    UNKNOWN = "unknown"


class Evidence(BaseModel):
    """An atomic piece of evidence. Carries its Citation, so grade + provenance + published_at travel
    with it (Laws 2 & 3). ``asserts_number`` marks evidence that carries a figure — such evidence must
    trace to a fact id (Law 1/2), enforced by the validator."""

    id: str
    summary: str
    source_class: SourceClass
    citation: Citation
    asserts_number: bool = False


class Entity(BaseModel):
    """A person/company/trust/fund. Relationships are graph edges, not fields — so P6/P9 questions
    ('is there a path from this counterparty to an insider?') become graph queries."""

    id: str
    name: str
    entity_type: str = Field(description="person | company | trust | fund")


class EvidenceEdge(BaseModel):
    """A typed relationship between two entities (FORENSIC_METHODOLOGY §4 entity graph)."""

    src: str
    dst: str
    relation: str = Field(description="affiliated_with | controls | transacted_with | employed_by | ...")
    evidence_ids: list[str] = Field(default_factory=list)


class EvidenceClaim(BaseModel):
    """A single assertion, linked to the evidence for and against it. Richer than ``_base.Claim``: it
    adds the supporting/refuting split, dependency links (so a refuted parent re-opens its children),
    and the 'how would a third party reproduce this?' field the reports always supply."""

    id: str
    statement: str
    kind: ClaimKind
    status: ClaimStatus = ClaimStatus.UNKNOWN
    load_bearing: bool = False
    supporting: list[str] = Field(default_factory=list)   # evidence ids
    refuting: list[str] = Field(default_factory=list)     # evidence ids
    depends_on: list[str] = Field(default_factory=list)   # claim ids
    confidence: Confidence | None = None
    open_questions: list[str] = Field(default_factory=list)
    replication: str = Field(default="", description="how a third party reproduces this finding")
    adjudication: str = Field(default="", description="required when `refuting` is non-empty")


class EvidenceGraph(BaseModel):
    """The container. Nodes keyed by id for O(1) reference-integrity checks by the validator."""

    claims: dict[str, EvidenceClaim] = Field(default_factory=dict)
    evidence: dict[str, Evidence] = Field(default_factory=dict)
    entities: dict[str, Entity] = Field(default_factory=dict)
    edges: list[EvidenceEdge] = Field(default_factory=list)
