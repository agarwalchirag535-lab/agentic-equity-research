"""Resolve a prediction against an actual value from the fact store (SPEC §7.2 step 1)."""

from __future__ import annotations

import operator as _op
from collections.abc import Callable
from dataclasses import dataclass

from firm.core.monitoring.predictions import Operator, Prediction

_OPS: dict[str, Callable[[float, float], bool]] = {
    ">=": _op.ge,
    ">": _op.gt,
    "<=": _op.le,
    "<": _op.lt,
    "==": _op.eq,
}


def evaluate(op: Operator, actual: float, threshold: float) -> bool:
    return _OPS[op](actual, threshold)


def resolve(pred: Prediction, actual: float) -> Prediction:
    """Return a copy of ``pred`` marked resolved with its boolean outcome."""
    outcome = evaluate(pred.operator, actual, pred.threshold)
    return pred.model_copy(update={"resolved": True, "outcome": outcome})


@dataclass(frozen=True)
class Resolution:
    """One prediction's resolution attempt. `actual` is None when the metric could not be recomputed —
    reported, never silently skipped (a prediction that can't be scored is itself a finding about the
    firm's data reach at resolution time)."""

    prediction: Prediction
    actual: float | None
    outcome: bool | None
    reason: str = ""


def resolve_due(
    store,
    ledger_path,
    ticker: str,
    as_of,
    *,
    start_year: int = 2015,
) -> list[Resolution]:
    """Close the memory loop (SPEC §7.2): score every due, unresolved prediction for `ticker` against
    the metric AS THE FIRM COMPUTES IT from the point-in-time fact store at `as_of`, and rewrite the
    ledger with the outcomes.

    First invoked for real on PC Jeweller: the FORENSIC_CAUTION report of as-of 2017-12-31 logged three
    dated criteria resolving 2018-10-27, and the FY18 annual report answers them.

    Point-in-time discipline applies to resolution exactly as to research: the actual is derived from
    facts with `published_at <= as_of`, so replaying history cannot leak the future into the score.
    `start_year` must match the window policy the criteria were computed under — a cumulative metric
    resolved over a different window is a different claim (stated here rather than hidden; the window
    belongs on the Prediction schema eventually).

    Rewrites the WHOLE ledger file (idempotent by prediction_id; unresolved and foreign rows pass
    through untouched). Returns every attempted resolution, scoreable or not.
    """
    from pathlib import Path

    from firm.core.monitoring.predictions import read_jsonl
    from firm.core.pipeline import derive as D

    ledger = read_jsonl(Path(ledger_path))
    due = [p for p in ledger
           if p.ticker == ticker and not p.resolved and p.resolve_by <= as_of]
    if not due:
        return []

    facts = D.load_company_facts(store, ticker, as_of, start_year=start_year)
    derived = D.derive_metrics(facts)

    resolutions: list[Resolution] = []
    updated: dict[str, Prediction] = {}
    for pred in due:
        derivation = derived.values.get(pred.metric)
        if derivation is None:
            why = "; ".join(sorted(derived.missing.get(pred.metric, ("metric not derivable",))))
            resolutions.append(Resolution(pred, None, None,
                                          f"not derivable as-of {as_of}: {why}"))
            continue
        resolved = resolve(pred, derivation.value)
        updated[pred.prediction_id] = resolved
        resolutions.append(Resolution(resolved, derivation.value, resolved.outcome))

    if updated:
        out = [updated.get(p.prediction_id, p) for p in ledger]
        Path(ledger_path).write_text("".join(p.model_dump_json() + "\n" for p in out))
    return resolutions
