"""Tests for the evidence-graph invariants (FORENSIC_METHODOLOGY §4). Every rule R1-R6 + a real-finding demo."""

from datetime import date

from firm.core.validators.evidence_graph import (
    dangling_references,
    lookahead_violations,
    numbers_without_provenance,
    refutation_cascade,
    unadjudicated_contradictions,
    unsupported_conclusions,
    validate_graph,
)
from firm.schemas._base import Citation, Grade
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


def _cite(fact_id="f1", grade=Grade.B, published="2024-11-01"):
    return Citation(
        fact_id=fact_id, doc_id="d1", locator="p.2", published_at=date.fromisoformat(published),
        extractor_version="v1", grade=grade,
    )


def _ev(eid, grade=Grade.B, source=SourceClass.PUBLIC_RECORD, asserts_number=False, fact_id="f1",
        published="2024-11-01"):
    return Evidence(id=eid, summary=eid, source_class=source, asserts_number=asserts_number,
                    citation=_cite(fact_id=fact_id, grade=grade, published=published))


# ---- R1: no load-bearing conclusion without grade A/B support ----------------------------------
def test_r1_unsupported_conclusion():
    g = EvidenceGraph(
        evidence={"e1": _ev("e1", grade=Grade.C)},
        claims={"c1": EvidenceClaim(id="c1", statement="x", kind=ClaimKind.INFERENCE,
                                    load_bearing=True, supporting=["e1"])},
    )
    v = unsupported_conclusions(g)
    assert len(v) == 1 and v[0].rule == "R1_unsupported"


def test_r1_satisfied_by_grade_b():
    g = EvidenceGraph(
        evidence={"e1": _ev("e1", grade=Grade.B)},
        claims={"c1": EvidenceClaim(id="c1", statement="x", kind=ClaimKind.INFERENCE,
                                    load_bearing=True, supporting=["e1"])},
    )
    assert unsupported_conclusions(g) == []


def test_r1_ignores_non_load_bearing():
    g = EvidenceGraph(
        evidence={"e1": _ev("e1", grade=Grade.D)},
        claims={"c1": EvidenceClaim(id="c1", statement="x", kind=ClaimKind.OBSERVATION,
                                    load_bearing=False, supporting=["e1"])},
    )
    assert unsupported_conclusions(g) == []


# ---- R2: a refuted-evidence claim must be adjudicated -------------------------------------------
def test_r2_unadjudicated_contradiction():
    g = EvidenceGraph(
        evidence={"e1": _ev("e1")},
        claims={"c1": EvidenceClaim(id="c1", statement="x", kind=ClaimKind.INFERENCE, refuting=["e1"])},
    )
    v = unadjudicated_contradictions(g)
    assert len(v) == 1 and v[0].rule == "R2_unadjudicated"


def test_r2_satisfied_when_adjudicated():
    g = EvidenceGraph(
        evidence={"e1": _ev("e1")},
        claims={"c1": EvidenceClaim(id="c1", statement="x", kind=ClaimKind.INFERENCE, refuting=["e1"],
                                    adjudication="filing contradicted by public records; we side with records")},
    )
    assert unadjudicated_contradictions(g) == []


# ---- R3: number-asserting evidence must have a fact id ------------------------------------------
def test_r3_number_without_provenance():
    g = EvidenceGraph(evidence={"e1": _ev("e1", asserts_number=True, fact_id="  ")})
    v = numbers_without_provenance(g)
    assert len(v) == 1 and v[0].rule == "R3_no_provenance"


def test_r3_ok_with_fact_id():
    g = EvidenceGraph(evidence={"e1": _ev("e1", asserts_number=True, fact_id="fact-42")})
    assert numbers_without_provenance(g) == []


# ---- R4: refutation cascade ---------------------------------------------------------------------
def test_r4_refutation_cascade():
    g = EvidenceGraph(
        claims={
            "parent": EvidenceClaim(id="parent", statement="p", kind=ClaimKind.INFERENCE,
                                    status=ClaimStatus.REFUTED),
            "child": EvidenceClaim(id="child", statement="c", kind=ClaimKind.INFERENCE,
                                   status=ClaimStatus.SUPPORTED, depends_on=["parent"]),
        },
    )
    v = refutation_cascade(g)
    assert len(v) == 1 and v[0].rule == "R4_cascade" and v[0].node_id == "child"


def test_r4_ok_when_child_reopened():
    g = EvidenceGraph(
        claims={
            "parent": EvidenceClaim(id="parent", statement="p", kind=ClaimKind.INFERENCE,
                                    status=ClaimStatus.REFUTED),
            "child": EvidenceClaim(id="child", statement="c", kind=ClaimKind.INFERENCE,
                                   status=ClaimStatus.UNKNOWN, depends_on=["parent"]),
        },
    )
    assert refutation_cascade(g) == []


# ---- R5: dangling references --------------------------------------------------------------------
def test_r5_dangling_evidence_claim_and_entity():
    g = EvidenceGraph(
        entities={"ok": Entity(id="ok", name="OK Co", entity_type="company")},
        claims={"c1": EvidenceClaim(id="c1", statement="x", kind=ClaimKind.INFERENCE,
                                    supporting=["missing_ev"], depends_on=["missing_claim"])},
        edges=[EvidenceEdge(src="ok", dst="ghost", relation="controls")],
    )
    rules = [v.detail for v in dangling_references(g)]
    assert any("missing evidence 'missing_ev'" in d for d in rules)
    assert any("missing claim 'missing_claim'" in d for d in rules)
    assert any("missing entity 'ghost'" in d for d in rules)


# ---- R6: point-in-time (look-ahead) -------------------------------------------------------------
def test_r6_lookahead():
    g = EvidenceGraph(evidence={"e1": _ev("e1", published="2025-01-15")})
    assert lookahead_violations(g, date(2024, 12, 31)) and not lookahead_violations(g, date(2025, 2, 1))


def test_validate_graph_runs_r6_only_with_as_of():
    g = EvidenceGraph(evidence={"e1": _ev("e1", published="2025-01-15")})
    assert validate_graph(g) == []                       # no as_of => R6 skipped, otherwise clean
    assert validate_graph(g, as_of=date(2024, 12, 31))   # as_of given => R6 fires


# ---- Real-finding demo: Carvana's undisclosed related-party chain models & validates -----------
def test_carvana_cerberus_chain_validates_clean():
    """The §4 set-piece: the '$800M buyer is an undisclosed related party' finding, as a graph.

    Public-records support (UCC + registry + ISDA) outranks the issuer's binding-filing claim of
    'unrelated third party', which is recorded as refuting evidence and explicitly adjudicated.
    """
    g = EvidenceGraph(
        entities={
            "carvana": Entity(id="carvana", name="Carvana Co.", entity_type="company"),
            "cerberus": Entity(id="cerberus", name="Cerberus Capital", entity_type="fund"),
            "quayle": Entity(id="quayle", name="Dan Quayle", entity_type="person"),
            "towd": Entity(id="towd", name="Towd Point Auto Trust 2024", entity_type="trust"),
        },
        edges=[
            EvidenceEdge(src="towd", dst="cerberus", relation="controls", evidence_ids=["e_registry"]),
            EvidenceEdge(src="quayle", dst="cerberus", relation="affiliated_with", evidence_ids=["e_role"]),
            EvidenceEdge(src="quayle", dst="carvana", relation="director_of", evidence_ids=["e_role"]),
            EvidenceEdge(src="carvana", dst="towd", relation="transacted_with", evidence_ids=["e_ucc"]),
        ],
        evidence={
            "e_ucc": _ev("e_ucc", grade=Grade.B, source=SourceClass.PUBLIC_RECORD, fact_id="ucc-2024"),
            "e_registry": _ev("e_registry", grade=Grade.B, source=SourceClass.PUBLIC_RECORD, fact_id="md-reg"),
            "e_isda": _ev("e_isda", grade=Grade.B, source=SourceClass.PUBLIC_RECORD, fact_id="isda-1"),
            "e_10q": _ev("e_10q", grade=Grade.A, source=SourceClass.BINDING_FILING,
                         asserts_number=True, fact_id="cvna-10q-800m"),
            "e_role": _ev("e_role", grade=Grade.C, source=SourceClass.BINDING_FILING, fact_id="proxy-1"),
        },
        claims={
            "c_related": EvidenceClaim(
                id="c_related",
                statement="The $800M loan buyer is an undisclosed related party (Cerberus-affiliated).",
                kind=ClaimKind.INFERENCE, status=ClaimStatus.SUPPORTED, load_bearing=True,
                supporting=["e_ucc", "e_registry", "e_isda"],
                refuting=["e_10q"],  # the filing claims 'unrelated third party'
                adjudication="Filing asserts 'unrelated'; three independent public records place the "
                             "trust at Cerberus HQ and link a Carvana director to Cerberus. Records win.",
                replication="AZ UCC lien search for 'TOWD POINT AUTO TRUST 2024'; MD entity search; ISDA lookup.",
            ),
        },
    )
    assert validate_graph(g, as_of=date(2024, 12, 31)) == []
