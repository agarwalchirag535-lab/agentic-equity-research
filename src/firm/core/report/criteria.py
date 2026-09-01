"""Kill and rehabilitation criteria, generated deterministically (Phase 2, ADR-0021).

SPEC §7.1 wants criteria that are *dated, observable, and resolvable from a future filing without human
judgment*. That requirement collides head-on with Law 1: a criterion is mostly a **number** (metric,
operator, threshold, date), and Law 1 forbids an LLM from producing numbers. `red_team` may argue about
*which* risks matter; it may not author the tripwire.

So criteria are computed here, from three inputs and nothing else:

* the run's derived metrics — the level the company is at today;
* `config/thresholds.yaml` — the policy floors the firm already committed to publicly;
* `config/thresholds.yaml:report` — the horizon, the filing lag, and the headroom.

The threshold for a kill criterion sits `criteria_headroom` *inside* today's value (or at the policy
floor, whichever binds first), so the criterion is a genuine tripwire rather than a restatement of the
status quo — a criterion that can never trigger is the failure mode `red_team` is explicitly warned about.

Dates: `resolve_by = the company's next FY close + filing_lag_days` — the first date a third party
could actually check the claim in a filing. The close is the company's own, read from its filings'
stated period ends (ADR-0049: Symphony closed on 30 June until FY16); 31 March is only the Indian
statutory default for a company no filing has dated yet.

Symmetry (ADR-0016) is structural: positives get kill criteria, negatives get rehabilitation criteria,
and both come out of the same deterministic machinery so optimism gets no easier standard.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, timedelta
from typing import Any

from firm.core.compute import periods
from firm.core.compute.multibagger import FeasibilityResult
from firm.core.pipeline.derive import DerivedSet
from firm.schemas.report import CheckOutcome, Criterion, VerifiedCleanChecklist


def resolve_by(
    as_of: date, horizon_years: int, filing_lag_days: int, fy_close: date | None = None,
) -> date:
    """The first date a future filing could resolve a criterion set today.

    The next FY close on/after ``as_of`` plus the statutory filing lag. `horizon_years` shifts it
    further out for slower-moving claims.

    ``fy_close`` is the company's own latest stated fiscal close (ADR-0049): a June closer's criterion
    resolves against a 30-June filing, not a 31-March one that never comes. When no filing has stated
    a close, 31 March is the Indian statutory default — policy, not an inference about the company.
    """
    anchor = fy_close if fy_close is not None else date(as_of.year, 3, 31)
    close = periods.next_close(as_of, anchor)
    return (periods.shift_months(close, 12 * (horizon_years - 1))
            + timedelta(days=filing_lag_days))


def _floor_with_headroom(current: float, policy_floor: float, headroom: float) -> float:
    """A tripwire strictly below today's level but never below the published policy floor.

    If the company already sits at or under the floor, the floor itself is the tripwire — there is no
    room to give away.
    """
    if current <= policy_floor:
        return round(policy_floor, 4)
    return round(max(policy_floor, current * (1.0 - headroom)), 4)


def kill_criteria(
    derived: DerivedSet,
    *,
    forensic: Mapping[str, Any],
    policy: Mapping[str, Any],
    as_of: date,
) -> list[Criterion]:
    """Dated tripwires for a positive verdict: the things whose failure ends the thesis.

    Ordered by how load-bearing they are: cash conversion first (if profit stops becoming cash, nothing
    else matters), then returns on capital, then growth. Only criteria whose metric was actually derived
    are emitted — an undated criterion on an unavailable metric would be unresolvable theatre.
    """
    headroom = float(policy["criteria_headroom"])
    horizon = int(policy["criteria_horizon_years"])
    lag = int(policy["filing_lag_days"])
    deadline = resolve_by(as_of, horizon, lag, fy_close=derived.fy_close)
    out: list[Criterion] = []

    if (cum := derived.get("cum_cfo_pat")) is not None:
        threshold = _floor_with_headroom(cum.value, forensic["cumulative_cfo_pat_min"], headroom)
        out.append(Criterion(
            statement=(
                f"Cumulative CFO/PAT stays at or above {threshold:.2f} (it is {cum.value:.2f} today). "
                "If a decade of reported profit stops converting to cash, the thesis is dead regardless "
                "of growth."
            ),
            metric="cum_cfo_pat", operator=">=", threshold=threshold,
            resolve_by=deadline, load_bearing=True,
        ))

    if (cfo_pat := derived.get("cfo_pat_latest")) is not None:
        threshold = _floor_with_headroom(cfo_pat.value, forensic["cfo_pat_min"], headroom)
        out.append(Criterion(
            statement=(
                f"Single-year CFO/PAT stays at or above {threshold:.2f} in the next annual report "
                f"(it is {cfo_pat.value:.2f} today)."
            ),
            metric="cfo_pat_latest", operator=">=", threshold=threshold, resolve_by=deadline,
        ))

    if (roic := derived.get("roic_latest")) is not None:
        threshold = round(roic.value * (1.0 - headroom), 4)
        out.append(Criterion(
            statement=(
                f"ROIC stays at or above {threshold:.1%} (it is {roic.value:.1%} today). A "
                "self-funded compounder cannot survive a collapsing return on incremental capital."
            ),
            metric="roic_latest", operator=">=", threshold=threshold, resolve_by=deadline,
        ))

    if (opm := derived.get("opm_latest")) is not None:
        threshold = round(opm.value * (1.0 - headroom), 4)
        out.append(Criterion(
            statement=(
                f"Operating margin stays at or above {threshold:.1%} (it is {opm.value:.1%} today) — "
                "margin give-back is how a pricing-power claim is falsified."
            ),
            metric="opm_latest", operator=">=", threshold=threshold, resolve_by=deadline,
        ))

    if (accr := derived.get("accrual_ratio_latest")) is not None:
        limit = round(float(forensic["sloan_accrual_flag"]), 4)
        out.append(Criterion(
            statement=(
                f"The accrual ratio stays at or below {limit:.2f} (it is {accr.value:+.3f} today); "
                "above it, reported earnings are increasingly non-cash."
            ),
            metric="accrual_ratio_latest", operator="<=", threshold=limit, resolve_by=deadline,
        ))

    # P2 requires at least one load-bearing kill criterion. Cash conversion is the natural one, but if it
    # was not derivable the *first* criterion that did survive carries the weight — a positive verdict may
    # not ship with every tripwire marked optional.
    if out and not any(c.load_bearing for c in out):
        out[0] = out[0].model_copy(update={"load_bearing": True})
    return out


def rehabilitation_criteria(
    derived: DerivedSet,
    checklist: VerifiedCleanChecklist,
    *,
    forensic: Mapping[str, Any],
    policy: Mapping[str, Any],
    as_of: date,
    feasibility: FeasibilityResult | None = None,
    self_fund_ceiling: float = 1.0,
) -> list[Criterion]:
    """What would reverse a withheld or cautioned verdict — the mirror image of a kill criterion.

    Three sources, all mechanical:

    * every check that **fired** becomes "this metric returns to the policy floor";
    * every check that came back **UNAVAILABLE** becomes "disclose the input" — because for a listed
      company the datum is public by law, so the fix is disclosure, not an analyst's patience
      (owner directive 2). Those are resolvable from the next filing by inspection;
    * a failed **feasibility gate** becomes the re-entry trigger REPORT_ARCHITECTURE §2 asks for on a
      `RETURN_HURDLE_NOT_CLEARED` note: the ROIC at which the target growth becomes self-fundable. Without this,
      a forensically spotless company withheld purely on maths would have nothing to state, and the P2
      symmetry gate would (correctly) refuse to publish it.
    """
    horizon = int(policy["criteria_horizon_years"])
    deadline = resolve_by(as_of, horizon, int(policy["filing_lag_days"]), fy_close=derived.fy_close)
    out: list[Criterion] = []

    floors = {
        "cumulative_cfo_pat": ("cum_cfo_pat", forensic["cumulative_cfo_pat_min"], ">="),
        "cfo_pat": ("cfo_pat_latest", forensic["cfo_pat_min"], ">="),
        "high_accruals": ("accrual_ratio_latest", forensic["sloan_accrual_flag"], "<="),
    }

    for record in checklist.records:
        if record.outcome is CheckOutcome.FLAG:
            metric, floor, operator = floors.get(record.name, (record.name, 0.0, "=="))
            current = derived.value(metric)
            current_txt = f" (currently {current:.2f})" if current is not None else ""
            out.append(Criterion(
                statement=(
                    f"`{record.name}` clears: {metric} {operator} {floor}{current_txt}, evidenced in the "
                    "next annual report. Until then this remains the reason the verdict is withheld."
                ),
                metric=metric, operator=operator, threshold=round(float(floor), 4),
                resolve_by=deadline, load_bearing=True,
            ))

    unavailable = [r for r in checklist.records if r.outcome is CheckOutcome.UNAVAILABLE]
    if unavailable:
        out.append(Criterion(
            statement=(
                "The company discloses the inputs for the checks that could not be run — "
                + ", ".join(f"`{r.name}`" for r in unavailable[:8])
                + (" …" if len(unavailable) > 8 else "")
                + " — in a filing readable as text. For a listed company these are public by law; the "
                "gap, not our patience, is what holds the verdict."
            ),
            metric="checks_unavailable", operator="<=", threshold=0.0,
            resolve_by=deadline, load_bearing=True,
        ))

    if checklist.note_coverage < 1.0:
        out.append(Criterion(
            statement=(
                f"Every note to the accounts is enumerated and dispositioned (coverage is "
                f"{checklist.note_coverage:.0%} today; undispositioned: "
                f"{checklist.notes_undispositioned or 'unlisted'})."
            ),
            metric="note_coverage", operator=">=", threshold=1.0, resolve_by=deadline,
        ))

    if feasibility is not None and not feasibility.self_funds and self_fund_ceiling > 0:
        needed_roic = round(feasibility.g_required / self_fund_ceiling, 4)
        out.append(Criterion(
            statement=(
                f"ROIC reaches {needed_roic:.1%} (it is {feasibility.roic:.1%} today), which is the "
                f"return at which {feasibility.g_required:.1%} growth becomes self-fundable — the "
                "re-entry trigger for this note. Equivalently, the required growth falls because the "
                "entry price does."
            ),
            metric="roic_latest", operator=">=", threshold=needed_roic,
            resolve_by=deadline, load_bearing=True,
        ))

    return out
