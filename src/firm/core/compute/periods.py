"""Periods as first-class objects: `(start, end, months)`, not a label (ADR-0049).

ADR-0048 established that a period *label* is not a period — Symphony's nine-month transition stub
carried the label FY16 and corrupted every flow comparison around it. That ADR delivered the `months`
half. This module delivers the *date* half: `FY{yy}` silently assumes a 31-March close for every
company, and Symphony's FY13–FY15 close on 30 June. Within one company the labels stay
self-consistent, but the moment label arithmetic is used as TIME arithmetic it lies:

* a CAGR spanning a June→March year-end change compounds over fewer years than the labels count;
* `resolve_by` computes the wrong filing date for a non-March closer;
* a peer comparison across differing year-ends compares different twelve-month windows under one label.

Everything here is pure date arithmetic on stdlib `datetime` — no estimation, no financial numbers.
The tolerance that decides when label arithmetic is *wrong enough* to correct is policy and lives in
`config/thresholds.yaml:periods`, injected by callers (SPEC §3: no magic numbers in code).
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta

#: Mean Gregorian year in days — calendar arithmetic, not an estimate of a financial figure.
DAYS_PER_YEAR = 365.2425


def _clamped(year: int, month: int, day: int) -> date:
    """`date(year, month, day)` with the day clamped to the month's length (31-Jun -> 30-Jun,
    29-Feb -> 28-Feb outside leap years). Needed whenever a (month, day) pair is carried to another
    year or month, where the pair may not exist."""
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def shift_months(anchor: date, months: int) -> date:
    """``anchor`` moved by ``months`` calendar months, day clamped to the target month."""
    total = anchor.year * 12 + (anchor.month - 1) + months
    return _clamped(total // 12, total % 12 + 1, anchor.day)


@dataclass(frozen=True)
class Period:
    """One reporting period as the filing states it: its label, its closing date, and its length.

    `end` is the close the filing prints ("year ended 30th June, 2015" -> 2015-06-30) — never inferred
    from the label. `months` is None for a stock observation (a balance-sheet column states an instant,
    not a length), and for those `start` is undefined.
    """

    label: str          # 'FY15' — display/storage key, NOT a source of dates
    end: date           # the stated close
    months: int | None = None

    def __post_init__(self) -> None:
        if self.months is not None and self.months <= 0:
            raise ValueError(f"{self.label}: a period cannot cover {self.months} months")

    @property
    def start(self) -> date | None:
        """First day of the period (the day after the previous close), None for a stock observation."""
        if self.months is None:
            return None
        return shift_months(self.end, -self.months) + timedelta(days=1)


def years_between(first_end: date, last_end: date) -> float:
    """Elapsed years between two period closes — the true compounding time between two annual flows.

    Raises rather than returning a degenerate value when the closes are not in order: a zero or
    negative span means the caller's window is wrong, and a CAGR over it would be noise.
    """
    if last_end <= first_end:
        raise ValueError(f"period closes out of order: {first_end} .. {last_end}")
    return (last_end - first_end).days / DAYS_PER_YEAR


def span_years(
    label_span: int,
    first_end: date | None,
    last_end: date | None,
    *,
    tolerance_days: float,
) -> float:
    """The exponent a CAGR over this window should use: label years, unless the stated closes prove
    the labels wrong.

    When both closes are known and the actual elapsed time disagrees with the label count by more than
    ``tolerance_days``, the dates win — that is the June→March discontinuity, where `FY15-FY18` spans
    2.75 years, not 3. Within tolerance the *integer* label span is returned unchanged, so ordinary
    March-to-March windows (whose closes differ from N years by at most a leap day or two) keep the
    exact exponent they always had rather than drifting to 4.9994. When either close is unknown the
    label span stands — that is the status quo, not a new assumption, and the caller's grade already
    reflects the weaker sourcing.
    """
    if label_span <= 0:
        raise ValueError("label_span must be positive")
    if first_end is None or last_end is None:
        return float(label_span)
    actual = years_between(first_end, last_end)
    if abs(actual - label_span) * DAYS_PER_YEAR <= tolerance_days:
        return float(label_span)
    return actual


def next_close(as_of: date, close: date) -> date:
    """The first fiscal-year close ON OR AFTER ``as_of``, given any known close of the same company.

    Carries the (month, day) of the known close forward — 31 March for the Indian statutory default,
    30 June for a June closer — clamping 29 February in non-leap years. "On or after" (not strictly
    after) preserves the long-standing `resolve_by` behaviour at the boundary: a criterion set on the
    close date itself resolves against that close's own filing.
    """
    candidate = _clamped(as_of.year, close.month, close.day)
    if candidate < as_of:
        candidate = _clamped(as_of.year + 1, close.month, close.day)
    return candidate
