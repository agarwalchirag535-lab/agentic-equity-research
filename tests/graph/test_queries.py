"""Tests for entity-graph traversal / related-party detection (FORENSIC_METHODOLOGY §4, P6/P9)."""

from firm.core.graph.queries import (
    adjacency,
    neighbors,
    paths_between,
    undisclosed_related_party_paths,
)
from firm.schemas.evidence import Entity, EvidenceEdge, EvidenceGraph


def _carvana_graph() -> EvidenceGraph:
    # towd -controls- cerberus -affiliated- quayle -director_of- carvana -transacted- towd
    return EvidenceGraph(
        entities={
            "carvana": Entity(id="carvana", name="Carvana", entity_type="company"),
            "cerberus": Entity(id="cerberus", name="Cerberus", entity_type="fund"),
            "quayle": Entity(id="quayle", name="Dan Quayle", entity_type="person"),
            "towd": Entity(id="towd", name="Towd Point Trust", entity_type="trust"),
            "lonely": Entity(id="lonely", name="Unconnected Co", entity_type="company"),
        },
        edges=[
            EvidenceEdge(src="towd", dst="cerberus", relation="controls"),
            EvidenceEdge(src="quayle", dst="cerberus", relation="affiliated_with"),
            EvidenceEdge(src="quayle", dst="carvana", relation="director_of"),
            EvidenceEdge(src="carvana", dst="towd", relation="transacted_with"),
            EvidenceEdge(src="quayle", dst="ghost", relation="affiliated_with"),  # unknown entity → ignored
        ],
    )


def test_adjacency_is_undirected_and_ignores_unknown_endpoints():
    adj = adjacency(_carvana_graph())
    assert adj["cerberus"] == {"towd", "quayle"}   # both directions
    assert "ghost" not in adj                        # unknown entity never added
    assert "ghost" not in adj["quayle"]              # edge to unknown endpoint ignored


def test_adjacency_relation_filter():
    adj = adjacency(_carvana_graph(), relations={"controls"})
    assert adj["towd"] == {"cerberus"} and adj["quayle"] == set()


def test_neighbors():
    assert neighbors(_carvana_graph(), "carvana") == {"quayle", "towd"}


def test_paths_between_finds_short_chain():
    paths = paths_between(_carvana_graph(), "towd", "quayle", max_hops=3)
    assert ["towd", "cerberus", "quayle"] in paths
    assert paths == sorted(paths, key=len)  # shorter first


def test_paths_between_respects_hop_budget():
    # towd→quayle shortest is 2 hops; a 1-hop budget finds nothing
    assert paths_between(_carvana_graph(), "towd", "quayle", max_hops=1) == []


def test_paths_between_unknown_endpoint_or_bad_budget():
    g = _carvana_graph()
    assert paths_between(g, "towd", "nope", max_hops=3) == []
    assert paths_between(g, "towd", "cerberus", max_hops=0) == []


def test_paths_between_no_route_to_isolated_node():
    assert paths_between(_carvana_graph(), "towd", "lonely", max_hops=5) == []


def test_undisclosed_related_party_detection():
    g = _carvana_graph()
    # Carvana claims 'towd' is an unrelated third party; is it linked to insider 'quayle'?
    hits = undisclosed_related_party_paths(g, "towd", ["quayle", "lonely"], max_hops=3)
    assert "quayle" in hits            # linked -> claim of 'unrelated' is contradicted
    assert "lonely" not in hits        # genuinely unconnected insider yields no path
    assert ["towd", "cerberus", "quayle"] in hits["quayle"]
