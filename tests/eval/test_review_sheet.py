"""The sign-off sheet, and the circularity it is shaped to prevent (ADR-0083).

GOLDEN_SET.md §0 opens by naming how the set fails: "by validating itself". Sign-off is where that
either happens or does not, so the sheet is built to make the right question easy and the wrong one
hard — it asks a person to confirm the LABEL and the VERIFIED FACTS, the two things a machine cannot
check, and puts the firm's own screen result last, labelled as context.

If a reviewer signs a case because the screen agreed with them, every threshold calibrated on the set
inherits that circularity. No test can stop a person doing it; what the tests can do is stop the sheet
from inviting it.
"""

from __future__ import annotations

from datetime import date

from firm.core.eval.golden import Expectation, GoldenCase, VerifiedFact, load_cases
from firm.core.eval.review import render_case, render_review


def _fact(**kw) -> VerifiedFact:
    base = {"metric": "pnl:Sales", "period": "FY21", "value": 2669.34, "unit": "INR_cr",
            "locator": "FY21 AR p.67 l.7", "method": "filing_page", "source": "read from the statement"}
    return VerifiedFact(**{**base, **kw})


def _case(**kw) -> GoldenCase:
    base = {
        "case_id": "ACME-FY21", "ticker": "ACME", "as_of": date(2022, 8, 15), "label": "adverse",
        "manifest": "evals/manifests/ACME.json",
        "expectation": Expectation(screen_at_worst="HARD_FAIL", screen_at_best="REVIEW",
                                   must_flag=("other_income_heavy",),
                                   rationale="The firm must not clear this company."),
        "verified_facts": (_fact(),),
        "label_event": {"kind": "auditor_resignation", "date": "2023-08-15",
                        "source": "https://bse/x.pdf", "summary": "Resigned over unpaid dues."},
    }
    return GoldenCase(**{**base, **kw})


def test_the_sheet_asks_for_the_label_and_the_facts():
    sheet = render_review([_case()])
    assert "The label is real" in sheet
    assert "The verified facts are right" in sheet


def test_the_sheet_says_plainly_what_is_NOT_being_signed():
    """The circularity GOLDEN_SET.md §0 names first, headed off in the instructions."""
    sheet = render_review([_case()])
    assert "What you are NOT being asked to confirm" in sheet
    assert "Whether the firm's verdict was correct" in sheet
    assert "measures this system against its own output" in sheet


def test_the_screen_result_is_last_and_labelled_as_context():
    rendered = render_case(_case(), screen="HARD_FAIL")
    assert "Context only, not what you are signing" in rendered
    # The label event and the facts must both precede it — a reviewer reads the claim before the answer.
    assert rendered.index("Label event") < rendered.index("Context only")
    assert rendered.index("Facts verified") < rendered.index("Context only")


def test_the_label_event_carries_its_citation_and_date():
    rendered = render_case(_case())
    assert "auditor_resignation" in rendered and "2023-08-15" in rendered
    assert "https://bse/x.pdf" in rendered
    assert "Resigned over unpaid dues." in rendered


def test_a_clean_case_states_that_the_absence_IS_the_label():
    """For a clean case there is no event, and the reviewer is confirming a negative — which is a
    different and easier-to-fudge judgment, so the sheet names it."""
    rendered = render_case(_case(label="clean", label_event=None))
    assert "the label IS the absence of one" in rendered
    assert "\n\none, and" not in rendered          # no stray hard-wrap mid-sentence


def test_every_verified_fact_shows_where_it_was_read_from():
    rendered = render_case(_case(verified_facts=(_fact(), _fact(metric="pnl:Other Income",
                                                               value=30.67))))
    assert "`pnl:Sales`" in rendered and "`pnl:Other Income`" in rendered
    assert "FY21 AR p.67 l.7" in rendered
    assert "2,669.34 INR_cr" in rendered


def test_a_case_with_no_verified_facts_is_called_out_not_left_blank():
    """Nothing anchors such a case to a filing page, which a reviewer must see before signing."""
    assert "nothing anchors this case" in render_case(_case(verified_facts=()))


def test_a_known_failure_and_its_coverage_note_reach_the_reviewer():
    rendered = render_case(_case(known_failure="CAP-EPC — the walker missed the FY18 balance sheet.",
                                 notes="No business model matches."))
    assert "Recorded as a known failure" in rendered and "CAP-EPC" in rendered
    assert "Recorded coverage gap" in rendered


def test_the_header_counts_signed_and_unsigned():
    sheet = render_review([_case(), _case(case_id="ACME-FY22", human_signed_off=True)])
    assert "2 case(s); 1 signed, 1 awaiting you" in sheet


def test_the_sheet_warns_against_calibrating_before_the_rates_land():
    assert "Sign-off first, calibration after the rates" in render_review([_case()])


def test_it_renders_the_repos_real_eight_cases():
    """Generated from the case files, so the sheet cannot drift from what the harness reads."""
    cases = load_cases("evals/golden_set")
    sheet = render_review(cases)
    assert len(cases) == 8
    for case in cases:
        assert case.case_id in sheet
        assert f"evals/golden_set/{case.case_id}.yaml" in sheet
