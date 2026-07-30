"""Probability-weighted scenario analysis (SPEC §5: bear/base/bull/disaster, probabilities sum to 1)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class Scenario:
    name: str
    probability: float
    return_multiple: float


def validate_probabilities(scenarios: Sequence[Scenario], tol: float = 1e-6) -> None:
    """Probabilities must be non-negative and sum to 1 (SPEC §5)."""
    if len(scenarios) == 0:
        raise ValueError("no scenarios")
    total = sum(s.probability for s in scenarios)
    if abs(total - 1.0) > tol:
        raise ValueError(f"probabilities must sum to 1, got {total}")
    for s in scenarios:
        if s.probability < 0:
            raise ValueError("probability cannot be negative")


def expectancy(scenarios: Sequence[Scenario]) -> float:
    """Expected return multiple = Σ p_i × return_i (SPEC §5 / PM expectancy)."""
    validate_probabilities(scenarios)
    return sum(s.probability * s.return_multiple for s in scenarios)
