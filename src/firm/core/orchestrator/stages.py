"""Pipeline stages and gates (SPEC §8). The gate structure is what keeps cost sane."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Stage(int, Enum):
    UNIVERSE = 0
    SCREEN = 1
    FORENSIC_QUICK_KILL = 2
    SECTOR_BUSINESS = 3
    DEEP_FINANCIALS = 4
    MANAGEMENT_OWNERSHIP = 5
    VALUATION = 6
    RED_TEAM = 7
    SYNTHESIS = 8
    MONITORING = 9


class Gate(str, Enum):
    A = "A"  # liquidity, mcap band, data completeness, min history
    B = "B"  # no hard forensic fail (deterministic — ADR-0005)
    C = "C"  # structural growth runway exists
    D = "D"  # §6.3 feasibility math passes
    E = "E"  # thesis survives bear case with kill criteria


@dataclass(frozen=True)
class GateResult:
    gate: Gate
    ticker: str
    passed: bool
    reason: str


# Approximate funnel from SPEC §8 — used for sanity-checking a run's gate counts.
EXPECTED_FUNNEL = {
    Stage.UNIVERSE: 3000,
    Gate.A: 400,
    Gate.B: 150,
    Gate.C: 60,
    Gate.D: 20,
    Gate.E: 8,
}
