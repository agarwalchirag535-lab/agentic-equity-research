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


def test_citation_accepts_the_namespaced_fact_ids_the_system_actually_produces():
    """Real ids carry colons. An id grammar that excluded them made the validator satisfiable only by
    writing no numbers at all — passing by vacuum instead of by provenance."""
    known = {"derived:cum_cfo_pat", "screener-ABC-2026-07-23:pnl:Sales:FY26"}
    assert citation.validate("cash conversion is 1.11 [fact:derived:cum_cfo_pat]", known) == []
    assert citation.validate(
        "sales were 1,050 [fact:screener-ABC-2026-07-23:pnl:Sales:FY26]", known) == []


def test_citation_catches_a_number_glued_to_a_preceding_word():
    """'Rs9999 crore' is ordinary Indian financial prose and was how a fabricated figure slipped past."""
    problems = citation.validate("Revenue grew to Rs9999 crore last year.", {"f1"})
    assert [p.reason for p in problems] == ["no_citation"]
    assert citation.validate("level9999", {"f1"})[0].number == "9999"
    # a decimal is still matched once, not split into two claims
    assert [p.number for p in citation.validate("margin of 18.55 held", {"f1"})] == ["18.55"]


def test_citation_verifies_the_quoted_value_against_the_fact():
    known = {"derived:cum_cfo_pat"}
    values = {"derived:cum_cfo_pat": 1.2714}

    # rounding is fine
    assert citation.validate("conversion 1.27 [fact:derived:cum_cfo_pat]", known, values=values) == []
    # so is stating a ratio as a percentage
    assert citation.validate(
        "conversion 127% [fact:derived:cum_cfo_pat]", known, values=values) == []
    # keeping the citation and changing the digits is not
    wrong = citation.validate("conversion 0.42 [fact:derived:cum_cfo_pat]", known, values=values)
    assert [p.reason for p in wrong] == ["value_mismatch"]
    # without values supplied the check is token-presence only (backwards compatible)
    assert citation.validate("conversion 0.42 [fact:derived:cum_cfo_pat]", known) == []


def test_citation_reads_a_typographic_minus_as_a_minus():
    """A polished-prose minus (U+2212) parsed as a positive number: a sign corruption passed the value
    check and a correctly-written negative failed it. Both directions are tested here."""
    known = {"derived:accrual_ratio_latest"}

    # a correct negative, written the way a typesetter would, must pass
    assert citation.validate(
        "the accrual ratio is \u22120.032 [fact:derived:accrual_ratio_latest]",
        known, values={"derived:accrual_ratio_latest": -0.0320}) == []

    # flipping the sign must NOT pass just because the minus is typographic
    flipped = citation.validate(
        "the accrual ratio is \u22120.032 [fact:derived:accrual_ratio_latest]",
        known, values={"derived:accrual_ratio_latest": 0.0320})
    assert [p.reason for p in flipped] == ["value_mismatch"]


def test_citation_ignores_period_labels_and_digits_inside_a_fact_token():
    known = {"screener-X:pnl:Sales:FY26"}
    assert citation.validate(
        "revenue in FY26 and Q1FY27 was 1,050 [fact:screener-X:pnl:Sales:FY26]", known) == []


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
