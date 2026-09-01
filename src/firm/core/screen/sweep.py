"""The sweep: many companies through the deterministic layer, one funnel report out (ADR-0085).

This is the discovery half of the firm — the owner's 2026-08-01 goal item — and it is deliberately a
THIN loop over pieces that already exist: facts → derived metrics → model detection → the check
playbook → the forensic screen → the feasibility gate → the priced view → Gates A–E. **No agent runs
and no LLM is called**: a sweep's job is to decide where the expensive attention goes, and the
deterministic layer is what makes that decision affordable at hundreds of companies (SPEC §8).

Two rules carried over from elsewhere in the firm, because a sweep is where they are easiest to lose:

* **Nothing is silently dropped.** A company that fails a gate stays in the output with the gate and
  the reason — the register's exclusion discipline (ADR-0061), applied to discovery. In a SWEEP the
  gates genuinely decide who gets deep attention (that is their purpose and their economics); what they
  never decide is whether the company appears in the sweep report.
* **Short history routes, never drops** (ADR-0008). `route_by_history` was written in Phase 0 for
  exactly this and had no caller until now: a young company goes to the EMERGING track, and the sweep
  says so rather than comparing its two-year record against ten-year floors.

An owner-named deep dive is unaffected by any of this: eligibility for a REPORT is not decided here or
anywhere (ADR-0064). The sweep ranks where to look next; it does not decide what may be looked at.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from firm.core.compute import multibagger, quality
from firm.core.compute.models import BusinessModel, detect_models
from firm.core.config import (
    load_thresholds,
    model_detection_thresholds,
    model_forensic_thresholds,
    universal_forensic_thresholds,
)
from firm.core.pipeline import derive as D
from firm.core.pipeline.checks import ExternalInputs, evaluate_checks
from firm.core.pipeline.deep_dive import feasibility_at_target, statement_shape
from firm.core.pipeline.gates import GateFinding, evaluate_gates
from firm.core.pipeline.valuation import load_valuation
from firm.core.screen.pipeline import Pipeline, RouteResult, route_by_history


@dataclass(frozen=True)
class SweepRow:
    """One company's deterministic read. Everything needed to decide whether it earns a deep dive."""

    ticker: str
    route: RouteResult
    models: tuple[BusinessModel, ...]
    screen: quality.ForensicScreenResult
    checks_ran: int
    checks_applicable: int
    feasibility: multibagger.FeasibilityResult | None
    gates: tuple[GateFinding, ...]
    market_cap_cr: float | None
    #: Why this row has no numbers at all (no facts at the as-of date). Still a row — never dropped.
    empty_reason: str = ""

    @property
    def survives_funnel(self) -> bool:
        """Would the discovery funnel spend agent attention here? Gate A and B both passing.

        `None` (unavailable) does NOT survive: spending the expensive tier on a company whose
        liquidity could not even be established is how a funnel stops being one. The row itself
        remains in the report either way.
        """
        by_gate = {g.gate.value: g for g in self.gates}
        return bool(by_gate.get("A") and by_gate["A"].passed) and bool(
            by_gate.get("B") and by_gate["B"].passed)


def sweep_company(store: Any, ticker: str, as_of: date) -> SweepRow:
    """The deterministic layer for one company — the same pieces a deep dive runs, minus the agents."""
    thresholds = load_thresholds()
    facts = D.load_company_facts(store, ticker, as_of)
    derived = D.derive_metrics(facts)

    screen_cfg = thresholds["screen"]
    route = route_by_history(
        derived.years, min_history_years=float(screen_cfg["min_history_years"]),
        emerging_min_years=float(screen_cfg["emerging_min_years"]))

    if not derived.values:
        return SweepRow(
            ticker=ticker, route=route, models=(), checks_ran=0, checks_applicable=0,
            screen=quality.ForensicScreenResult(quality.ForensicVerdict.PASS, False, []),
            feasibility=None, gates=(), market_cap_cr=None,
            empty_reason=(f"no facts at or before {as_of.isoformat()} — ingest filings "
                          f"(`firm discover-filings` / `firm ingest`) before sweeping this name"))

    models = tuple(detect_models(statement_shape(facts, derived), model_detection_thresholds()))
    from firm.core.compute.models import build_playbook
    from firm.core.config import model_playbooks

    playbook = build_playbook(models, model_playbooks())
    evaluation = evaluate_checks(
        playbook, derived, facts, forensic=thresholds["forensic"],
        universal=universal_forensic_thresholds(), model_specific=model_forensic_thresholds(),
        external=ExternalInputs())
    sector = (quality.SectorClass.FINANCIAL
              if BusinessModel.LENDER in models or BusinessModel.BANK in models
              else quality.SectorClass.NON_FINANCIAL)
    from firm.core.config import forensic_thresholds as _ft

    screen = quality.forensic_screen(
        sector, evaluation.metrics, _ft(), checks_ran=evaluation.ran,
        checks_expected=len(evaluation.applicable),
        min_ran_share=float(thresholds["forensic"].get("screen_min_ran_share", 0)))
    feasibility = feasibility_at_target(derived, thresholds["report"], thresholds["multibagger"])
    valuation = load_valuation(store, ticker, as_of, facts, derived,
                               policy=thresholds["valuation"])
    from firm.core.ingest.prices import ADV, latest_market_fact

    adv = latest_market_fact(store, ticker, ADV, as_of)
    gates = evaluate_gates(
        screen=screen, feasibility=feasibility, history_years=derived.years,
        thresholds=screen_cfg, market_cap_cr=valuation.market_cap_cr,
        adv_cr=adv.value if adv is not None else None,
        kill_criteria=(), red_team_ran=False)

    return SweepRow(
        ticker=ticker, route=route, models=models, screen=screen,
        checks_ran=evaluation.ran, checks_applicable=len(evaluation.applicable),
        feasibility=feasibility, gates=gates, market_cap_cr=valuation.market_cap_cr)


def render_sweep(rows: Sequence[SweepRow], as_of: date) -> str:
    """The funnel, as a page. Survivors first, then routed, then excluded — everyone visible."""
    survivors = [r for r in rows if not r.empty_reason and r.survives_funnel
                 and r.route.pipeline is Pipeline.MAIN]
    emerging = [r for r in rows if not r.empty_reason and r.route.pipeline is not Pipeline.MAIN]
    excluded = [r for r in rows if not r.empty_reason and not r.survives_funnel
                and r.route.pipeline is Pipeline.MAIN]
    unread = [r for r in rows if r.empty_reason]

    def line(r: SweepRow) -> str:
        gate_bits = " ".join(f"{g.gate.value}:{g.status}" for g in r.gates)
        cap = f"₹{r.market_cap_cr:,.0f}cr" if r.market_cap_cr is not None else "cap n/a"
        gate_d = next((g for g in r.gates if g.gate.value == "D"), None)
        feas = gate_d.status if gate_d else "n/a"
        return (f"| {r.ticker} | {r.screen.verdict.value} ({r.checks_ran}/{r.checks_applicable}) "
                f"| {feas} | {cap} | {gate_bits} |")

    out = [
        f"# Sweep — {len(rows)} company(ies) as of {as_of.isoformat()}",
        "",
        (f"_Deterministic layer only: no agent ran and no LLM was called. The funnel decides where "
         f"deep-dive attention goes next; it never decides report eligibility — any company here can "
         f"still be deep-dived by name (ADR-0064). {len(survivors)} survive the funnel, "
         f"{len(emerging)} routed by history, {len(excluded)} excluded with reasons, "
         f"{len(unread)} not yet ingested._"),
        "",
    ]
    if survivors:
        out += ["## Survives the funnel — earns a deep dive", "",
                "| ticker | screen (ran) | §6.3 gate | mkt cap | gates |", "|---|---|---|---|---|"]
        out += [line(r) for r in survivors] + [""]
    if emerging:
        out += ["## Routed by history (ADR-0008 — routed, never dropped)", ""]
        out += [f"- **{r.ticker}** → {r.route.pipeline.value} ({r.route.history_years:.0f}y): "
                f"{r.route.reason}" for r in emerging] + [""]
    if excluded:
        out += ["## Excluded by the funnel — with the reason, per the register discipline", ""]
        for r in excluded:
            # Only the gates that DECIDE funnel survival (A, B) may be cited as the exclusion reason.
            # Gate D failing is a finding about the return target, not why attention was withheld —
            # citing it here misattributes the exclusion, and the first live run did exactly that.
            deciding = [g for g in r.gates if g.gate.value in "AB" and g.passed is not True]
            why = "; ".join(f"Gate {g.gate.value}: {g.reason}" for g in deciding) \
                  or "gate outcome unavailable"
            out += [f"- **{r.ticker}** — {why}"]
        out += [""]
    if unread:
        out += ["## Not yet ingested", ""]
        out += [f"- **{r.ticker}** — {r.empty_reason}" for r in unread] + [""]
    return "\n".join(out).rstrip() + "\n"
