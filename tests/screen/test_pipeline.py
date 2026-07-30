"""Tests for history-based routing (ADR-0008) — young companies are routed, never dropped."""

import pytest

from firm.core.screen.pipeline import Pipeline, graduates_to_main, route_by_history

CFG = dict(min_history_years=5, emerging_min_years=1)


def test_long_history_routes_to_main():
    assert route_by_history(10, **CFG).pipeline is Pipeline.MAIN


def test_short_history_routes_to_emerging_not_dropped():
    r = route_by_history(3, **CFG)
    assert r.pipeline is Pipeline.EMERGING
    assert "DRHP" in r.reason and "short history" in r.reason


def test_too_little_history_quarantined():
    assert route_by_history(0.5, **CFG).pipeline is Pipeline.QUARANTINE


def test_boundaries_are_inclusive_at_the_floor():
    assert route_by_history(5, **CFG).pipeline is Pipeline.MAIN        # exactly min -> MAIN
    assert route_by_history(1, **CFG).pipeline is Pipeline.EMERGING    # exactly emerging_min -> EMERGING


def test_negative_history_raises():
    with pytest.raises(ValueError):
        route_by_history(-1, **CFG)


def test_graduation():
    assert graduates_to_main(5, 5) is True
    assert graduates_to_main(3, 5) is False
