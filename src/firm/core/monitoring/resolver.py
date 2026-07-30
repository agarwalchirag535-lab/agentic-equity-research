"""Resolve a prediction against an actual value from the fact store (SPEC §7.2 step 1)."""

from __future__ import annotations

import operator as _op
from typing import Callable

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
