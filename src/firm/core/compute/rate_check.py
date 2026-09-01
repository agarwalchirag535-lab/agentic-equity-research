"""Validation for the dated reference-rate file (ADR-0082).

`reference_rates.yaml` is the one config file in this repo that holds a MEASUREMENT of the world rather
than a policy this firm chose, and it is entered by hand from a published series. Hand entry has two
failure modes, and both are silent:

* **A missing citation.** A rate without a source is a number somebody typed. Nothing downstream can
  tell it from a sourced one, and it would miscalibrate every cash-reality verdict that used it.
* **A decimal slip.** `6.5` where `0.065` was meant sets the cash-yield floor to 260% and flags every
  company on earth — or `0.0065` clears everyone. The check is trivial and the consequence is that the
  golden set would then calibrate thresholds against a broken rate, which is precisely the
  "bug uniform across the calibration set" GOLDEN_SET.md §1 warns is indistinguishable from a
  property of the world.

So the file is validated rather than trusted, and the validator names the fiscal years the golden set
actually needs — five, not a decade — so the manual task is small and specific.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

#: A short-term Indian risk-free rate outside this band is a data-entry error, not a rate. The band's
#: job is catching a misplaced decimal point, not second-guessing the source, so it is set BETWEEN the
#: two: Indian short rates have ranged roughly 3%-9%, and a 10x slip from the lowest of those lands at
#: 0.32%. A 1% floor is comfortably below any real value and comfortably above any slipped one. (Set to
#: 0.5% first, which let `0.0065` — a 10x slip from 6.5% — pass; a test caught it.)
_MIN_PLAUSIBLE, _MAX_PLAUSIBLE = 0.01, 0.20


@dataclass(frozen=True)
class RateProblem:
    fiscal_year: str
    problem: str


def validate_reference_rates(rates: Mapping[str, Any]) -> list[RateProblem]:
    """Every defect in the file, or an empty list. Never raises — the caller decides what is fatal."""
    out: list[RateProblem] = []
    block = dict(rates.get("risk_free_rate", {}))

    fallback = block.get("fallback")
    if fallback is None:
        out.append(RateProblem("fallback", "no fallback rate — a run with no dated row has nothing"))
    elif not _MIN_PLAUSIBLE <= float(fallback) <= _MAX_PLAUSIBLE:
        out.append(RateProblem("fallback", (
            f"fallback {fallback} is outside {_MIN_PLAUSIBLE:.1%}-{_MAX_PLAUSIBLE:.0%} — rates are "
            f"decimals here (0.065 is 6.5%), so this looks like a misplaced decimal point")))

    for year, entry in sorted(dict(block.get("by_fiscal_year") or {}).items()):
        if not isinstance(entry, Mapping):
            out.append(RateProblem(year, "entry is not a mapping of rate/source/as_of"))
            continue
        rate = entry.get("rate")
        if rate is None:
            out.append(RateProblem(year, "no `rate`"))
        elif not _MIN_PLAUSIBLE <= float(rate) <= _MAX_PLAUSIBLE:
            out.append(RateProblem(year, (
                f"rate {rate} is outside {_MIN_PLAUSIBLE:.1%}-{_MAX_PLAUSIBLE:.0%} — rates are decimals "
                f"here (0.065 is 6.5%), so this looks like a misplaced decimal point")))
        if not str(entry.get("source", "")).strip():
            out.append(RateProblem(year, (
                "no `source` — a rate without one is a number somebody typed, and nothing downstream "
                "can tell it from a sourced one")))
        stamp = str(entry.get("as_of", "")).strip()
        if not stamp:
            out.append(RateProblem(year, "no `as_of` — the date the rate refers to"))
        else:
            try:
                date.fromisoformat(stamp)
            except ValueError:
                out.append(RateProblem(year, f"`as_of` {stamp!r} is not an ISO date"))
    return out


def fiscal_years_needed(as_of_dates: Sequence[date]) -> list[str]:
    """The Indian fiscal years the given run dates fall in, as the fact store labels them ("FY21").

    The Indian FY ends 31 March, so a run dated June 2019 is reading FY19's annual report and must be
    judged against FY19's rate environment — not the one in force on the day the report was written.
    """
    years: set[str] = set()
    for stamp in as_of_dates:
        fy = stamp.year if stamp.month > 3 else stamp.year - 1
        years.add(f"FY{fy % 100:02d}")
    return sorted(years)
