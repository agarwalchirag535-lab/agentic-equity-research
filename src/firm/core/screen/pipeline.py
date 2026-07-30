"""History-based pipeline routing (ADR-0008).

Companies are ROUTED, never silently dropped. A short track record sends a company to the EMERGING
track (a real, lighter thesis path) rather than excluding it — so good young businesses are not a blind
spot. Deterministic; no LLM.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Pipeline(str, Enum):
    MAIN = "MAIN"            # >= min_history_years: full trend-based analysis
    EMERGING = "EMERGING"    # emerging_min <= x < min_history_years: lighter, point-in-time-heavy track
    QUARANTINE = "QUARANTINE"  # < emerging_min: too little to say anything; revisit later


@dataclass(frozen=True)
class RouteResult:
    pipeline: Pipeline
    history_years: float
    reason: str


def route_by_history(
    history_years: float, *, min_history_years: float, emerging_min_years: float
) -> RouteResult:
    """Route a company by how much operating history exists.

    - history >= min_history_years            -> MAIN
    - emerging_min_years <= history < min      -> EMERGING (routed, not dropped — ADR-0008)
    - history < emerging_min_years             -> QUARANTINE (revisit as history accrues)
    """
    if history_years < 0:
        raise ValueError("history_years cannot be negative")
    if history_years >= min_history_years:
        return RouteResult(Pipeline.MAIN, history_years, "sufficient history for trend-based analysis")
    if history_years >= emerging_min_years:
        return RouteResult(
            Pipeline.EMERGING,
            history_years,
            "short history — lighter track: DRHP + unit economics + point-in-time cash-reality checks; "
            "multi-year-trend forensics suppressed; thesis must flag short history",
        )
    return RouteResult(
        Pipeline.QUARANTINE,
        history_years,
        "too little history to analyse responsibly; re-check as filings accrue",
    )


def graduates_to_main(history_years: float, min_history_years: float) -> bool:
    """An EMERGING company graduates to MAIN once it crosses min_history_years."""
    return history_years >= min_history_years
