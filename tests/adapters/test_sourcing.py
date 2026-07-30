"""Tests for the primary-first source policy (adapters/base/sourcing.py)."""

from dataclasses import dataclass

import pytest

from firm.adapters.base.sourcing import (
    assess_sourcing,
    is_primary,
    resolve_primary_first,
)


@dataclass(frozen=True)
class Src:
    grade: str
    name: str = "s"


def test_is_primary():
    assert is_primary("A") and is_primary("B")
    assert not is_primary("C") and not is_primary("D")
    with pytest.raises(ValueError):
        is_primary("Z")


def test_resolve_primary_first_prefers_audited_over_aggregator():
    # screener (B) vs audited AR (A) for the same fact -> pick A, never the aggregator
    chosen = resolve_primary_first([Src("B", "screener"), Src("A", "audited_ar"), Src("D", "media")])
    assert chosen.name == "audited_ar"


def test_resolve_primary_first_stable_on_ties():
    chosen = resolve_primary_first([Src("B", "first_b"), Src("B", "second_b")])
    assert chosen.name == "first_b"


def test_resolve_primary_first_empty_raises():
    with pytest.raises(ValueError):
        resolve_primary_first([])


def test_assess_sourcing_has_primary():
    v = assess_sourcing([Src("A", "ar"), Src("B", "screener")], required_grade="A")
    assert v.chosen_grade == "A" and v.had_primary and not v.secondary_only


def test_assess_sourcing_secondary_only_is_flagged():
    # only screener/media available for a fact that should have an audited primary -> flag
    v = assess_sourcing([Src("C", "concall"), Src("D", "news")], required_grade="A")
    assert v.secondary_only is True and v.had_primary is False


def test_assess_sourcing_b_meets_when_required_is_b():
    v = assess_sourcing([Src("B", "screener")], required_grade="B")
    assert not v.secondary_only and v.had_primary


def test_assess_sourcing_no_candidates():
    v = assess_sourcing([], required_grade="A")
    assert v.secondary_only is True and v.chosen_grade == ""
