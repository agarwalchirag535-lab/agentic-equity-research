"""Entity-graph traversal for related-party detection (FORENSIC_METHODOLOGY §4, patterns P6/P9).

Edges in an ``EvidenceGraph`` are directed (src→dst) but affiliation/control/transaction relationships
are, for reachability purposes, treated as **undirected**: if a trust is controlled by a fund and a
director is affiliated with that fund, the director and the trust are related regardless of edge
direction. All functions are pure and deterministic (Law 1).
"""

from __future__ import annotations

from typing import Iterable

from firm.schemas.evidence import EvidenceGraph


def adjacency(graph: EvidenceGraph, relations: Iterable[str] | None = None) -> dict[str, set[str]]:
    """Undirected adjacency map over entity edges, optionally filtered to a set of relation types."""
    allow = set(relations) if relations is not None else None
    adj: dict[str, set[str]] = {eid: set() for eid in graph.entities}
    for edge in graph.edges:
        if allow is not None and edge.relation not in allow:
            continue
        if edge.src in adj and edge.dst in adj:  # ignore edges to unknown entities (R5 catches those)
            adj[edge.src].add(edge.dst)
            adj[edge.dst].add(edge.src)
    return adj


def neighbors(graph: EvidenceGraph, entity_id: str, relations: Iterable[str] | None = None) -> set[str]:
    """Entities directly connected to ``entity_id`` (undirected), optionally by given relations."""
    return adjacency(graph, relations).get(entity_id, set())


def paths_between(
    graph: EvidenceGraph, src: str, dst: str, max_hops: int = 3, relations: Iterable[str] | None = None
) -> list[list[str]]:
    """All simple (no repeated node) undirected paths from ``src`` to ``dst`` within ``max_hops`` edges.

    Shorter paths first. Returns [] if either endpoint is unknown or none exists within the budget.
    """
    if src not in graph.entities or dst not in graph.entities or max_hops < 1:
        return []
    adj = adjacency(graph, relations)
    found: list[list[str]] = []

    def dfs(node: str, target: str, path: list[str], visited: set[str]) -> None:
        if len(path) - 1 > max_hops:  # path length in edges exceeded budget
            return
        if node == target and len(path) > 1:
            found.append(list(path))
            return
        for nxt in sorted(adj.get(node, set())):
            if nxt in visited:
                continue
            visited.add(nxt)
            path.append(nxt)
            dfs(nxt, target, path, visited)
            path.pop()
            visited.remove(nxt)

    dfs(src, dst, [src], {src})
    found.sort(key=len)
    return found


def undisclosed_related_party_paths(
    graph: EvidenceGraph,
    counterparty: str,
    insiders: Iterable[str],
    max_hops: int = 3,
    relations: Iterable[str] | None = None,
) -> dict[str, list[list[str]]]:
    """P6/P9: for a transaction counterparty declared 'unrelated', find any chain linking it to a known
    insider. A non-empty result contradicts an 'unrelated third party' claim and warrants disclosure.

    Returns {insider_id: [paths...]} for insiders reachable within ``max_hops``; absent insiders had no
    path (or are unknown entities).
    """
    out: dict[str, list[list[str]]] = {}
    for insider in insiders:
        paths = paths_between(graph, counterparty, insider, max_hops=max_hops, relations=relations)
        if paths:
            out[insider] = paths
    return out
