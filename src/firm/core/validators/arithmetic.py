"""Arithmetic validator (SPEC §9) — recompute a quoted number from source facts and compare.

An agent may narrate a ratio, but the number must equal what the compute layer produces from the facts.
This catches an LLM that 'rounds' or invents a figure.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ArithmeticCheck:
    label: str
    quoted: float
    computed: float
    ok: bool
    abs_diff: float


def check(label: str, quoted: float, computed: float, rel_tol: float = 1e-3, abs_tol: float = 1e-9) -> ArithmeticCheck:
    """Compare a quoted value to the authoritative computed value within tolerance."""
    diff = abs(quoted - computed)
    ok = diff <= max(rel_tol * abs(computed), abs_tol)
    return ArithmeticCheck(label=label, quoted=quoted, computed=computed, ok=ok, abs_diff=diff)


def all_ok(checks: list[ArithmeticCheck]) -> bool:
    return all(c.ok for c in checks)
