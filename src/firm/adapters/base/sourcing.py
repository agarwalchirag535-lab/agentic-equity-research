"""Primary-source-first policy — market-agnostic (Law 6; addresses the owner's #1 pain, ADR-0014).

The failure this prevents: an agent, offered the same fact by an audited filing (grade A) and by an
aggregator like screener (grade B/secondary), defaults to whichever is easiest to parse — usually the
aggregator. For a *listed* company the primary document is public by law, so a fact that ends up resting
only on a secondary source is either a sourcing failure or a disclosure gap — and either way it must be
flagged, never silently accepted.

Grade hierarchy (SPEC §4): A audited filing · B exchange filing / rating · C company claim · D media.
A and B are 'primary/primary-adjacent'; C and D are secondary for a numeric claim. Pure functions.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

_GRADE_RANK = {"A": 0, "B": 1, "C": 2, "D": 3}  # lower rank = more primary = preferred
_PRIMARY_GRADES = frozenset({"A", "B"})


@runtime_checkable
class Graded(Protocol):
    grade: str


def _valid(grade: str) -> str:
    if grade not in _GRADE_RANK:
        raise ValueError(f"unknown grade {grade!r} (expected one of A/B/C/D)")
    return grade


def is_primary(grade: str) -> bool:
    """A numeric claim may rest on a primary grade (A audited / B exchange); C/D are secondary."""
    return _valid(grade) in _PRIMARY_GRADES


def resolve_primary_first(candidates: Sequence[Graded]) -> Graded:
    """Given sources for the SAME fact, return the most-primary (lowest grade rank). Ties keep input
    order (stable). Raises on an empty candidate list."""
    if not candidates:
        raise ValueError("no candidate sources to resolve")
    best_idx = min(range(len(candidates)), key=lambda i: _GRADE_RANK[_valid(candidates[i].grade)])
    return candidates[best_idx]


@dataclass(frozen=True)
class SourcingVerdict:
    chosen_grade: str
    had_primary: bool
    secondary_only: bool     # True => a fact rests only on secondary sources — flag it
    detail: str


def assess_sourcing(candidates: Sequence[Graded], required_grade: str = "A") -> SourcingVerdict:
    """Assess whether a fact is backed by a source at least as primary as ``required_grade``.

    ``secondary_only`` is True when nothing meets ``required_grade`` — for a listed company that means
    either the primary filing wasn't fetched (a sourcing bug to fix) or it wasn't disclosed (a
    disclosure gap to flag). Both must surface; neither is an acceptable silent state.
    """
    _valid(required_grade)
    if not candidates:
        return SourcingVerdict("", False, True, "no source at all for this fact")
    best = resolve_primary_first(candidates)
    meets = _GRADE_RANK[best.grade] <= _GRADE_RANK[required_grade]
    return SourcingVerdict(
        chosen_grade=best.grade,
        had_primary=is_primary(best.grade),
        secondary_only=not meets,
        detail=(
            f"best available grade {best.grade}; required ≤ {required_grade}"
            + ("" if meets else " — resting on a weaker-than-required source, flag it")
        ),
    )
