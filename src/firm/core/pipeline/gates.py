"""SPEC §8's funnel gates, evaluated for one company and REPORTED rather than enforced (ADR-0071).

WHY THEY DO NOT GATE HERE. The gates exist to keep a 3,000-company sweep affordable: Gate A drops the
illiquid and the out-of-band, Gate B the forensic hard-fails, and the expensive agents only ever see
survivors. That is the right economics for discovery, where the FIRM chooses the company.

It is the wrong behaviour entirely when the OWNER chooses (ADR-0064): research eligibility and
investment verdict are separate, and a company must never be refused a report because it failed an
investment gate. So in a deep dive every gate outcome is a FINDING — computed, printed with its
reason, and passed to no one as a licence to skip work. The same results feed the sweep, where they
do decide who gets looked at; that is the caller's choice, not this module's.

Everything here is arithmetic over already-computed inputs (Law 1). A gate whose inputs are missing
returns `None` for `passed` and says which input was absent — a gate that could not be evaluated is
not a gate that passed, and the difference is the whole point of the UNAVAILABLE discipline.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from firm.core.compute.multibagger import FeasibilityResult, GateVerdict
from firm.core.compute.quality import ForensicScreenResult
from firm.core.orchestrator.stages import Gate


@dataclass(frozen=True)
class GateFinding:
    """One gate's outcome for one company. `passed=None` means it could not be evaluated."""

    gate: Gate
    passed: bool | None
    reason: str

    @property
    def status(self) -> str:
        return "PASS" if self.passed else ("UNAVAILABLE" if self.passed is None else "FAIL")


def evaluate_gates(
    *,
    screen: ForensicScreenResult,
    feasibility: FeasibilityResult | None,
    history_years: int,
    thresholds: Mapping[str, Any],
    market_cap_cr: float | None = None,
    adv_cr: float | None = None,
    kill_criteria: Sequence[Any] = (),
    red_team_ran: bool = False,
) -> tuple[GateFinding, ...]:
    """Every gate in SPEC §8's funnel, applied to this one company."""
    out: list[GateFinding] = []

    # ---- Gate A: liquidity, cap band, history ----------------------------------------------------
    a_problems: list[str] = []
    a_unknown: list[str] = []
    floor, ceiling = float(thresholds["mcap_min_cr"]), float(thresholds["mcap_max_cr"])
    if market_cap_cr is None:
        a_unknown.append("market cap (needs a settled close and a share count)")
    elif not floor <= market_cap_cr <= ceiling:
        a_problems.append(f"market cap Rs {market_cap_cr:,.0f}cr is outside the Rs {floor:,.0f}-"
                          f"{ceiling:,.0f}cr universe band")
    adv_floor = float(thresholds["adv_floor_cr"])
    if adv_cr is None:
        a_unknown.append("average daily traded value (market:ADV)")
    elif adv_cr < adv_floor:
        a_problems.append(f"average daily traded value Rs {adv_cr:,.2f}cr is below the Rs "
                          f"{adv_floor:,.2f}cr liquidity floor")
    min_years = int(thresholds["min_history_years"])
    if history_years < min_years:
        a_problems.append(f"{history_years}y of history is below the {min_years}y floor")
    if a_problems:
        out.append(GateFinding(Gate.A, False, "; ".join(a_problems)))
    elif a_unknown:
        out.append(GateFinding(Gate.A, None, "not evaluable — missing " + "; ".join(a_unknown)))
    else:
        out.append(GateFinding(Gate.A, True, (
            f"in-band at Rs {market_cap_cr:,.0f}cr, liquid at Rs {adv_cr:,.2f}cr/day, "
            f"{history_years}y of history")))

    # ---- Gate B: no deterministic forensic hard fail (ADR-0005) -----------------------------------
    out.append(GateFinding(
        Gate.B, not screen.hard_fail,
        f"deterministic screen returned {screen.verdict.value}"
        + (f" — {', '.join(f.name for f in screen.flags)}" if screen.flags else "")))

    # ---- Gate C: a structural growth runway ------------------------------------------------------
    # Honestly unevaluable: "is there a runway?" is a judgment about the industry, and this firm has no
    # deterministic test for it. Asserting PASS because nothing contradicted it is exactly the
    # missing-reads-as-clean failure the house forbids.
    out.append(GateFinding(Gate.C, None, (
        "not evaluable deterministically — a structural growth runway is a judgment about the "
        "industry, and no computed test stands behind it. The sector and business sections carry what "
        "evidence there is")))

    # ---- Gate D: the §6.3 feasibility math --------------------------------------------------------
    if feasibility is None:
        out.append(GateFinding(Gate.D, None, (
            "not evaluable — ROIC is not derivable from the disclosed figures, so the self-funding "
            "test could not run")))
    else:
        passed = feasibility.verdict in (GateVerdict.SELF_FUNDED, GateVerdict.SELF_FUNDED_SURPLUS)
        out.append(GateFinding(Gate.D, passed,
                               f"{feasibility.verdict.value}: {feasibility.rationale}"))

    # ---- Gate E: the thesis survives a bear case, with kill criteria -------------------------------
    if not red_team_ran:
        out.append(GateFinding(Gate.E, None, (
            "not evaluable — `red_team` did not run, so no bear case was put to the thesis. An "
            "unchallenged thesis has not survived anything")))
    elif not kill_criteria:
        out.append(GateFinding(Gate.E, False, (
            "the thesis carries no dated kill criteria — a thesis that cannot be proved wrong does "
            "not ship (SPEC §7.1)")))
    else:
        out.append(GateFinding(Gate.E, True, (
            f"a bear case was put by `red_team` and the thesis carries {len(kill_criteria)} dated, "
            f"filing-resolvable kill criteria")))
    return tuple(out)
