"""Periods as first-class objects (ADR-0049): the date arithmetic that stops FY-label arithmetic
being used as time arithmetic. 100% coverage — this is `core/compute`."""

from __future__ import annotations

from datetime import date

import pytest

from firm.core.compute import periods as P

# Symphony's real calendar: FY15 closed 30 June 2015; the nine-month transition stub closed
# 31 March 2016; every year since closes 31 March.
JUNE_FY15 = date(2015, 6, 30)
MARCH_FY18 = date(2018, 3, 31)


# ---- Period ---------------------------------------------------------------------------------------

def test_a_twelve_month_period_knows_its_own_start():
    fy17 = P.Period("FY17", date(2017, 3, 31), months=12)
    assert fy17.start == date(2016, 4, 1)


def test_a_transition_stub_starts_where_the_june_year_ended():
    stub = P.Period("FY16", date(2016, 3, 31), months=9)
    assert stub.start == date(2015, 7, 1)


def test_a_stock_observation_states_an_instant_not_a_window():
    as_at = P.Period("FY17", date(2017, 3, 31))
    assert as_at.months is None and as_at.start is None


def test_a_non_positive_length_is_refused():
    with pytest.raises(ValueError, match="cannot cover"):
        P.Period("FY17", date(2017, 3, 31), months=0)


def test_shift_months_clamps_to_the_target_months_length():
    # 31 May shifted back a month lands on 30 April, not an invalid 31 April
    assert P.shift_months(date(2017, 5, 31), -1) == date(2017, 4, 30)
    # a leap-day anchor carried to a non-leap year clamps to 28 February
    assert P.shift_months(date(2020, 2, 29), 12) == date(2021, 2, 28)


# ---- years_between / span_years -------------------------------------------------------------------

def test_years_between_measures_true_elapsed_time():
    assert P.years_between(JUNE_FY15, MARCH_FY18) == pytest.approx(2.75, abs=0.01)


def test_years_between_refuses_a_backwards_window():
    with pytest.raises(ValueError, match="out of order"):
        P.years_between(MARCH_FY18, JUNE_FY15)


def test_march_to_march_keeps_the_exact_integer_exponent():
    # 2013→2018 spans two leap days; within tolerance the label count stands EXACTLY, so ordinary
    # windows do not drift to 4.9994 the moment their dates become known
    span = P.span_years(5, date(2013, 3, 31), date(2018, 3, 31), tolerance_days=45.0)
    assert span == 5.0 and isinstance(span, float)


def test_a_june_to_march_discontinuity_is_corrected_by_the_stated_closes():
    # the ADR-0049 case: FY15-FY18 labels count 3 years; the company lived 2.75
    span = P.span_years(3, JUNE_FY15, MARCH_FY18, tolerance_days=45.0)
    assert span == pytest.approx(2.75, abs=0.01)


def test_unknown_closes_fall_back_to_label_arithmetic():
    assert P.span_years(3, None, MARCH_FY18, tolerance_days=45.0) == 3.0
    assert P.span_years(3, JUNE_FY15, None, tolerance_days=45.0) == 3.0


def test_span_years_refuses_a_degenerate_window():
    with pytest.raises(ValueError, match="label_span"):
        P.span_years(0, JUNE_FY15, MARCH_FY18, tolerance_days=45.0)


# ---- next_close -----------------------------------------------------------------------------------

def test_next_close_carries_a_june_year_end_forward():
    assert P.next_close(date(2015, 12, 31), JUNE_FY15) == date(2016, 6, 30)


def test_next_close_before_the_anniversary_stays_in_the_same_year():
    assert P.next_close(date(2016, 2, 1), JUNE_FY15) == date(2016, 6, 30)


def test_next_close_on_the_close_date_itself_is_that_close():
    # "on or after" preserves the long-standing resolve_by boundary behaviour
    assert P.next_close(date(2016, 3, 31), date(2015, 3, 31)) == date(2016, 3, 31)


def test_next_close_clamps_a_leap_day_close_in_a_non_leap_year():
    assert P.next_close(date(2021, 3, 1), date(2020, 2, 29)) == date(2022, 2, 28)
