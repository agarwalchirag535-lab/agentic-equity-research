"""Sensitivity tables (SPEC §5: 2-D tables on the two variables that actually matter)."""

from __future__ import annotations

from collections.abc import Callable, Sequence


def one_way(func: Callable[[float], float], values: Sequence[float]) -> list[tuple[float, float]]:
    """Evaluate ``func`` across one varying input."""
    return [(v, func(v)) for v in values]


def two_way(
    func: Callable[[float, float], float],
    row_values: Sequence[float],
    col_values: Sequence[float],
) -> list[list[float]]:
    """Evaluate ``func`` across a grid of two varying inputs (rows × columns)."""
    return [[func(r, c) for c in col_values] for r in row_values]
