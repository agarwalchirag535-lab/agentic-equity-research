"""The golden-set scoring, which is pure and therefore testable without opening a filing (ADR-0061).

Several of these pin mistakes the set made on its own first run. That is deliberate: the harness is the
instrument, and an instrument that is wrong in a way nobody wrote down will be wrong again.
"""

from __future__ import annotations

import json

import pytest
import yaml

from firm.core.eval.golden import (
    EvalReport,
    Expectation,
    GoldenCase,
    GoldenCaseError,
    VerifiedFact,
    load_cases,
    parse_case,
    score_case,
    within_band,
)

_RAW = {
    "case_id": "X-FY26", "ticker": "X", "as_of": "2026-08-30", "label": "clean",
    "negative_class": "easy", "manifest": "evals/manifests/X.json",
    "expectation": {"screen_at_worst": "REVIEW", "screen_at_best": "PASS"},
}


def _case(**over) -> GoldenCase:
    return parse_case({**_RAW, **over})


# ---- what a case may not be ---------------------------------------------------------------------

def test_a_fraud_case_needs_an_event_that_happened_after_the_as_of():
    """THE WHOLE POINT OF A CASE. If the event was already public at `as_of`, the run is not being asked
    whether it saw it coming — it is being asked whether it can read the news."""
    with pytest.raises(GoldenCaseError, match="hindsight"):
        parse_case({**_RAW, "label": "fraud", "negative_class": "",
                    "label_event": {"kind": "sebi_order", "date": "2026-01-01",
                                    "source": "https://example.test/order"}})


def test_a_fraud_case_needs_a_citable_source():
    with pytest.raises(GoldenCaseError, match="citable source"):
        parse_case({**_RAW, "label": "fraud", "negative_class": "",
                    "label_event": {"kind": "sebi_order", "date": "2027-01-01", "source": "  "}})


def test_a_clean_case_may_not_carry_a_label_event():
    with pytest.raises(GoldenCaseError, match="must not carry"):
        parse_case({**_RAW, "label_event": {"kind": "sebi_order", "date": "2027-01-01",
                                            "source": "https://example.test/x"}})


def test_a_clean_case_needs_a_negative_class():
    """An unclassified negative averages into the aggregate and hides which HARD case broke."""
    with pytest.raises(GoldenCaseError, match="negative_class"):
        parse_case({**_RAW, "negative_class": ""})


def test_a_fact_the_pipeline_produced_cannot_be_the_baseline():
    """The circularity guard, refused at load rather than caught in review."""
    with pytest.raises(GoldenCaseError, match="cannot be the baseline"):
        _case(verified_facts=[{"metric": "pnl:Sales", "period": "FY26", "value": 1.0,
                               "method": "pipeline"}])


def test_an_unknown_label_is_refused():
    with pytest.raises(GoldenCaseError, match="label must be"):
        parse_case({**_RAW, "label": "probably_fine"})


# ---- a verified fact is recorded in the unit the filing prints ----------------------------------

def test_a_fact_recorded_in_lakh_is_compared_in_crore():
    """The set's first run failed four facts reading "verified 446.10, pipeline read 446.10". A person
    records what the page prints; the harness converts."""
    fact = VerifiedFact(metric="m", period="FY26", value=62482.67, unit="INR_lakh",
                        locator="p.57 l.7", method="filing_page")
    assert fact.canonical == pytest.approx(624.8267)
    assert fact.matches(624.8267)
    assert not fact.matches(624.83), "rounding the human's figure is not the same as reading it"


def test_float_representation_error_is_not_an_extraction_failure():
    """A lakh figure reaches crore through a multiplication; exact equality rejects its own arithmetic."""
    fact = VerifiedFact(metric="m", period="FY26", value=1322794.13, unit="INR_lakh",
                        locator="p.231", method="arithmetic_identity")
    assert fact.matches(13227.941300000001)


def test_an_absent_fact_is_a_failure_not_a_pass():
    fact = VerifiedFact(metric="m", period="FY26", value=1.0, unit="INR_cr", locator="",
                        method="filing_page")
    assert not fact.matches(None)


def test_a_stated_tolerance_still_works():
    fact = VerifiedFact(metric="m", period="FY26", value=100.0, unit="INR_cr", locator="",
                        method="filing_page", tolerance=0.5)
    assert fact.matches(100.4) and not fact.matches(101.0)


# ---- the two assertions stay apart ---------------------------------------------------------------

def test_extraction_and_judgment_failures_are_reported_separately():
    """Collapsing them is what makes improving an extractor look like improving calibration."""
    case = _case(verified_facts=[{"metric": "pnl:Sales", "period": "FY26", "value": 100.0,
                                  "unit": "INR_cr", "method": "filing_page"}],
                 expectation={"screen_at_worst": "PASS", "screen_at_best": "PASS"})
    result = score_case(case, screen="HARD_FAIL", flags=[], facts={("pnl:Sales", "FY26"): 90.0})
    assert len(result.extraction_failures) == 1 and len(result.judgment_failures) == 1
    assert not result.extraction_ok and not result.judgment_ok
    assert "verified 100.00" in result.extraction_failures[0]
    assert "pipeline read 90.00" in result.extraction_failures[0]


def test_a_correct_extraction_with_a_wrong_verdict_fails_only_judgment():
    case = _case(verified_facts=[{"metric": "pnl:Sales", "period": "FY26", "value": 100.0,
                                  "unit": "INR_cr", "method": "filing_page"}],
                 expectation={"screen_at_worst": "PASS", "screen_at_best": "PASS"})
    result = score_case(case, screen="REVIEW", flags=[], facts={("pnl:Sales", "FY26"): 100.0})
    assert result.extraction_ok and not result.judgment_ok


@pytest.mark.parametrize(
    ("verdict", "expected"),
    [("PASS", True), ("REVIEW", True), ("FORENSIC_CAUTION", False), ("HARD_FAIL", False),
     ("SOMETHING_ELSE", False)],
)
def test_the_band_is_inclusive_and_ordered_worst_to_best(verdict, expected):
    assert within_band(verdict, Expectation(screen_at_worst="REVIEW", screen_at_best="PASS")) is expected


def test_must_flag_and_must_not_flag_are_both_enforced():
    case = _case(expectation={"screen_at_worst": "HARD_FAIL", "screen_at_best": "PASS",
                              "must_flag": ["gnpa_drift"], "must_not_flag": ["provision_coverage_low"]})
    result = score_case(case, screen="REVIEW", flags=["provision_coverage_low"], facts={})
    assert any("gnpa_drift was expected to flag" in p for p in result.judgment_failures)
    assert any("provision_coverage_low flagged and must not" in p for p in result.judgment_failures)


# ---- a recorded failure is visible, and going green is louder than staying red -------------------

def test_a_recorded_failure_does_not_count_as_a_regression():
    case = _case(known_failure="CAL-1", expectation={"screen_at_worst": "PASS", "screen_at_best": "PASS"})
    result = score_case(case, screen="HARD_FAIL", flags=[], facts={})
    assert not result.passed and not result.regression


def test_a_recorded_failure_that_starts_passing_IS_a_regression():
    """A red case nobody notices turning green is how a calibration debt gets forgotten."""
    case = _case(known_failure="CAL-1", expectation={"screen_at_worst": "PASS", "screen_at_best": "PASS"})
    result = score_case(case, screen="PASS", flags=[], facts={})
    assert result.passed and result.unexpectedly_passing and result.regression


def test_an_unrecorded_failure_is_a_regression():
    case = _case(expectation={"screen_at_worst": "PASS", "screen_at_best": "PASS"})
    assert score_case(case, screen="HARD_FAIL", flags=[], facts={}).regression


# ---- the report keeps the hard negatives visible --------------------------------------------------

def test_the_negative_classes_are_reported_separately_not_averaged():
    """"5 of 6 passed" hides which one, and the hard classes are the only ones that measure anything."""
    good = score_case(_case(negative_class="easy"), screen="PASS", flags=[], facts={})
    bad = score_case(_case(negative_class="hard_cyclical",
                           expectation={"screen_at_worst": "PASS", "screen_at_best": "PASS"}),
                     screen="HARD_FAIL", flags=[], facts={})
    report = EvalReport((good, bad))
    assert report.by_negative_class() == {"easy": (1, 1), "hard_cyclical": (0, 1)}
    rendered = report.render()
    assert "hard_cyclical" in rendered and "0/1 judged correctly" in rendered
    assert "1/1 judged correctly" in rendered


def test_unsigned_cases_are_named_rather_than_assumed_verified():
    report = EvalReport((score_case(_case(), screen="PASS", flags=[], facts={}),))
    assert "NOT YET HUMAN-SIGNED" in report.render()
    assert len(report.unsigned) == 1


def test_a_signed_case_is_not_listed_as_unsigned():
    report = EvalReport((score_case(_case(human_signed_off=True), screen="PASS", flags=[], facts={}),))
    assert report.unsigned == ()


# --- A positive's citation must be traceable to the register it was selected from (ADR-0064) -----
#
# The first positive case was written with an INVENTED attachment URL: plausible in shape, wrong in every
# character, pointing at nothing. A citation is the one field whose whole job is to let a reader check the
# claim, so a fabricated one is worse than none — it makes a case look auditable while being unauditable.

_EVENT = {"kind": "auditor_resignation", "date": "2027-01-01",
          "source": "https://www.bseindia.com/xml-data/corpfiling/AttachHis/real.pdf"}


def _register(tmp_path, *sources):
    (tmp_path / "_register.jsonl").write_text(
        "\n".join(json.dumps({"kind": "auditor_resignation", "date": "2027-01-01",
                              "scrip_code": "1", "company": "X", "headline": "h", "source": s})
                  for s in sources) + "\n")


def _write(tmp_path, **over):
    raw = {**_RAW, "label": "adverse", "negative_class": "", "label_event": _EVENT, **over}
    (tmp_path / "X-FY26.yaml").write_text(yaml.safe_dump(raw))


def test_a_citation_the_register_never_produced_is_refused(tmp_path):
    _write(tmp_path)
    _register(tmp_path, "https://www.bseindia.com/xml-data/corpfiling/AttachHis/other.pdf")
    with pytest.raises(GoldenCaseError, match="not in _register.jsonl"):
        load_cases(tmp_path)


def test_a_citation_present_in_the_register_loads(tmp_path):
    _write(tmp_path)
    _register(tmp_path, _EVENT["source"])
    assert [c.case_id for c in load_cases(tmp_path)] == ["X-FY26"]


def test_with_no_register_file_the_check_is_silent(tmp_path):
    """A case may legitimately come from another source — but then its provenance rests entirely on
    `human_signed_off`, which the report names every run."""
    _write(tmp_path)
    assert len(load_cases(tmp_path)) == 1


def test_a_clean_case_is_not_checked_against_the_register(tmp_path):
    raw = {**_RAW, "negative_class": "easy"}
    (tmp_path / "C-FY26.yaml").write_text(yaml.safe_dump(raw))
    _register(tmp_path, "https://example.test/unrelated.pdf")
    assert len(load_cases(tmp_path)) == 1
