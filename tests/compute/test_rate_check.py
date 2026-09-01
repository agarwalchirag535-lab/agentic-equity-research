"""Validating the one config file that holds a measurement rather than a policy (ADR-0082).

`reference_rates.yaml` is entered by hand from a published series, and hand entry fails in two ways
that are both silent:

* an **uncited** rate is indistinguishable downstream from a sourced one, and
* a **decimal slip** — `6.5` where `0.065` was meant — sets the cash-yield floor to 260% and flags
  every company on earth, or `0.0065` clears everyone.

Either would then be calibrated against by the golden set, which is the "bug uniform across the
calibration set" GOLDEN_SET.md §1 says is indistinguishable from a property of the world. So the file
is validated rather than trusted.
"""

from __future__ import annotations

from datetime import date

from firm.core.compute.rate_check import (
    fiscal_years_needed,
    validate_reference_rates,
)
from firm.core.config import reference_rates


def _rates(**entries):
    return {"risk_free_rate": {"fallback": 0.065, "by_fiscal_year": entries}}


def _good(**kw):
    return {"rate": 0.035, "source": "RBI Handbook Table 59", "as_of": "2021-03-31", **kw}


def test_a_well_formed_row_passes():
    assert validate_reference_rates(_rates(FY21=_good())) == []


def test_a_misplaced_decimal_point_is_caught():
    """6.5 instead of 0.065 sets the floor to 260% — every company flagged, silently."""
    problems = validate_reference_rates(_rates(FY21=_good(rate=6.5)))
    assert problems and "misplaced decimal" in problems[0].problem


def test_a_rate_too_small_is_caught_too():
    """The mirror slip: 0.0065 (a 10x slip from 6.5%) clears everyone, reading as a clean bill of
    health. The band sits between the lowest real Indian rate (~3.2%) and a 10x slip from it (0.32%)."""
    assert validate_reference_rates(_rates(FY21=_good(rate=0.0065)))
    assert validate_reference_rates(_rates(FY21=_good(rate=0.032))) == []   # a real FY21-era rate


def test_an_uncited_rate_is_rejected():
    problems = validate_reference_rates(_rates(FY21=_good(source="")))
    assert any("somebody typed" in p.problem for p in problems)


def test_a_row_without_a_date_is_rejected():
    """The date is what makes the rate point-in-time; without it the row cannot be matched to a year."""
    assert validate_reference_rates(_rates(FY21=_good(as_of="")))
    assert validate_reference_rates(_rates(FY21=_good(as_of="March 2021")))


def test_a_broken_fallback_is_caught():
    assert validate_reference_rates({"risk_free_rate": {"fallback": 6.5}})
    assert validate_reference_rates({"risk_free_rate": {}})


def test_every_problem_is_reported_not_just_the_first():
    """A reader fixing the file by hand should see the whole list, not one error per run."""
    problems = validate_reference_rates(_rates(FY21={"rate": 99.0}))
    assert len(problems) >= 3          # implausible rate, no source, no as_of


def test_the_shipped_file_is_valid_and_deliberately_empty():
    """It ships with no dated rows because RBI's historical series could not be fetched and typing
    rates from memory would fabricate a primary input — the one error nothing downstream can detect."""
    rates = reference_rates()
    assert validate_reference_rates(rates) == []
    assert (rates["risk_free_rate"]["by_fiscal_year"] or {}) == {}


def test_the_indian_fiscal_year_is_derived_from_the_run_date():
    """The FY ends 31 March, so a June-2019 run reads FY19's filing and needs FY19's rate environment
    — not the one in force on the day the report happened to be written."""
    assert fiscal_years_needed([date(2019, 6, 30)]) == ["FY19"]
    assert fiscal_years_needed([date(2019, 1, 31)]) == ["FY18"]     # January is still FY18
    assert fiscal_years_needed([date(2019, 3, 31)]) == ["FY18"]     # the last day of FY18
    assert fiscal_years_needed([date(2019, 4, 1)]) == ["FY19"]      # the first day of FY19


def test_the_years_are_deduplicated_and_ordered():
    got = fiscal_years_needed([date(2026, 8, 30), date(2019, 6, 30), date(2026, 8, 30)])
    assert got == ["FY19", "FY26"]


def test_a_malformed_entry_is_reported_rather_than_crashing_the_run():
    """A hand-edited YAML file can hold anything. `FY21: 0.035` — the shorthand somebody will
    reasonably reach for — is not the row shape, and saying so beats an AttributeError."""
    problems = validate_reference_rates(_rates(FY21=0.035))
    assert len(problems) == 1
    assert "not a mapping" in problems[0].problem


def test_a_row_with_no_rate_at_all_is_reported():
    """The scaffold in the shipped config is commented out with `rate: 0.0__` placeholders; a
    half-finished paste lands here."""
    problems = validate_reference_rates(_rates(FY21={"source": "RBI Table 59", "as_of": "2021-03-31"}))
    assert [p.problem for p in problems] == ["no `rate`"]
