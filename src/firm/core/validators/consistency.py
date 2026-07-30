"""Consistency validator (SPEC §9) — surface cross-agent contradictions, never silently resolve them."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MetricClaim:
    agent: str
    metric: str
    value: float


@dataclass(frozen=True)
class Contradiction:
    metric: str
    agent_a: str
    value_a: float
    agent_b: str
    value_b: float
    rel_gap: float


def find_contradictions(claims: list[MetricClaim], rel_tol: float = 0.02) -> list[Contradiction]:
    """Two agents asserting materially different values for the same metric are surfaced, not merged."""
    contradictions: list[Contradiction] = []
    by_metric: dict[str, list[MetricClaim]] = {}
    for c in claims:
        by_metric.setdefault(c.metric, []).append(c)

    for metric, group in by_metric.items():
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                a, b = group[i], group[j]
                denom = max(abs(a.value), abs(b.value), 1e-9)
                gap = abs(a.value - b.value) / denom
                if gap > rel_tol:
                    contradictions.append(
                        Contradiction(metric, a.agent, a.value, b.agent, b.value, gap)
                    )
    return contradictions
