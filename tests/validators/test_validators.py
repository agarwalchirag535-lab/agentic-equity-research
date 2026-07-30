"""Tests for the four blocking validators."""

from firm.core.validators import arithmetic, citation, consistency, hedge


# ---- hedge detector ----------------------------------------------------------------------------
def test_hedge_detector():
    assert hedge.has_hedges("margins showed strong growth") is True
    assert set(hedge.find_hedges("strong and robust performance")) == {"strong", "robust"}
    # longer phrases win over their component words
    assert hedge.find_hedges("a significant opportunity") == ["significant opportunity"]
    assert hedge.has_hedges("EBITDA margin went 14.2% to 18.6%") is False


# ---- arithmetic validator ----------------------------------------------------------------------
def test_arithmetic_check():
    ok = arithmetic.check("gross_margin", quoted=0.400, computed=0.4001)
    assert ok.ok is True
    bad = arithmetic.check("gross_margin", quoted=0.44, computed=0.40)
    assert bad.ok is False
    assert arithmetic.all_ok([ok]) is True
    assert arithmetic.all_ok([ok, bad]) is False


# ---- citation validator ------------------------------------------------------------------------
def test_citation_all_sourced():
    text = "Revenue was 1234 [fact:f1] in FY24, up from 1000 [fact:f2]."
    assert citation.validate(text, {"f1", "f2"}) == []


def test_citation_flags_missing_and_unknown():
    missing = citation.validate("Margin reached 34 percent.", {"f1"})
    assert [p.reason for p in missing] == ["no_citation"]

    unknown = citation.validate("EBITDA was 180 [fact:zzz].", {"f1"})
    assert [p.reason for p in unknown] == ["unknown_fact_id"]


# ---- consistency validator ---------------------------------------------------------------------
def test_consistency_finds_contradiction():
    claims = [
        consistency.MetricClaim("financial_statement_analyst", "roic", 0.22),
        consistency.MetricClaim("valuation_modeler", "roic", 0.30),
    ]
    out = consistency.find_contradictions(claims)
    assert len(out) == 1 and out[0].metric == "roic"


def test_consistency_tolerates_small_differences():
    claims = [
        consistency.MetricClaim("a", "roic", 0.220),
        consistency.MetricClaim("b", "roic", 0.223),
    ]
    assert consistency.find_contradictions(claims) == []
