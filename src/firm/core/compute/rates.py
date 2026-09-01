"""Point-in-time reference rates: the right rate for the year being judged (ADR-0078).

A forensic check that asks "is this yield plausible?" is asking a question about a rate environment,
and the answer moved by more than 4 percentage points across the golden set's window. Using one
constant for every vintage does not make the check approximate — it makes it wrong in a direction that
depends on the year, which is the shape of error a calibration run would learn to compensate for and
then carry forever (GOLDEN_SET.md §1).

Law 1: pure lookup, no network, no inference. When no dated rate covers the period this returns the
fallback AND says so, because a check silently resting on the wrong vintage is the defect this module
exists to end, not a state to hide.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ReferenceRate:
    """A rate and the account of where it came from. `dated` is False for the flat fallback."""

    value: float
    basis: str
    dated: bool


def risk_free_for(period: str | None, rates: Mapping[str, Any]) -> ReferenceRate:
    """The risk-free rate to judge `period` against, from `config/reference_rates.yaml`.

    `period` is a fiscal-year label as the fact store writes it ("FY21"). An unknown or missing period
    gets the fallback: guessing which year an unlabelled figure belongs to is precisely the mis-dating
    this module prevents.
    """
    block = dict(rates.get("risk_free_rate", {}))
    by_year = dict(block.get("by_fiscal_year") or {})
    entry = by_year.get(period) if period else None
    if isinstance(entry, Mapping) and entry.get("rate") is not None:
        source = str(entry.get("source", "")).strip() or "source not stated"
        return ReferenceRate(
            value=float(entry["rate"]), dated=True,
            basis=f"{period} risk-free {float(entry['rate']):.2%}, from {source}")
    fallback = float(block.get("fallback", 0.0))
    note = str(block.get("fallback_basis", "")).strip() or "undated fallback"
    return ReferenceRate(
        value=fallback, dated=False,
        basis=(f"undated fallback {fallback:.2%} — no dated rate for {period or 'this period'}; "
               f"{note}"))
