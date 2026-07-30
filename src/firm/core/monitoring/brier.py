"""Brier scoring + calibration (SPEC §7.2 step 2). Lower is better; 0 is perfect, 0.25 is a coin flip."""

from __future__ import annotations

from collections import defaultdict

from firm.core.monitoring.predictions import Prediction


def brier_score(pairs: list[tuple[float, bool]]) -> float:
    """mean((probability − outcome)²) over resolved predictions."""
    if not pairs:
        raise ValueError("no resolved predictions to score")
    return sum((p - (1.0 if o else 0.0)) ** 2 for p, o in pairs) / len(pairs)


def brier_by_agent(preds: list[Prediction]) -> dict[str, float]:
    """Brier score grouped by agent — an agent that never beats a coin flip is dead weight (SPEC §7.5)."""
    grouped: dict[str, list[tuple[float, bool]]] = defaultdict(list)
    for p in preds:
        if p.resolved and p.outcome is not None:
            grouped[p.agent].append((p.probability, p.outcome))
    return {agent: brier_score(pairs) for agent, pairs in grouped.items()}
