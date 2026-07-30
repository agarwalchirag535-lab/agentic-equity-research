"""Tests for scenario expectancy and sensitivity tables — full coverage."""

import pytest

from firm.core.compute import sensitivity
from firm.core.compute.scenarios import Scenario, expectancy, validate_probabilities


# ---- scenarios ---------------------------------------------------------------------------------
def test_expectancy():
    scenarios = [
        Scenario("bull", 0.25, 4.0),
        Scenario("base", 0.45, 1.8),
        Scenario("bear", 0.20, 0.8),
        Scenario("disaster", 0.10, 0.2),
    ]
    assert expectancy(scenarios) == pytest.approx(0.25 * 4 + 0.45 * 1.8 + 0.20 * 0.8 + 0.10 * 0.2)


def test_validate_empty_raises():
    with pytest.raises(ValueError):
        validate_probabilities([])


def test_validate_sum_not_one_raises():
    with pytest.raises(ValueError):
        validate_probabilities([Scenario("a", 0.5, 2.0), Scenario("b", 0.2, 1.0)])


def test_validate_negative_probability_raises():
    # sums to 1 so it passes the sum check, then fails on the negative probability
    with pytest.raises(ValueError):
        validate_probabilities([Scenario("a", 1.2, 2.0), Scenario("b", -0.2, 1.0)])


# ---- sensitivity -------------------------------------------------------------------------------
def test_one_way():
    out = sensitivity.one_way(lambda x: x * 2, [1, 2, 3])
    assert out == [(1, 2), (2, 4), (3, 6)]


def test_two_way():
    grid = sensitivity.two_way(lambda r, c: r + c, [1, 2], [10, 20])
    assert grid == [[11, 21], [12, 22]]
