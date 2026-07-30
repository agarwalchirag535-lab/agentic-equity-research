"""The line-by-line interrogation engine (ADR-0022).

The behaviour under test is mostly about *refusing to look thorough*: a question must never disappear, a
meaningless ratio must never be narrated, and a gap in the firm's own extraction must never be charged to
the company. Each test below pins one of those, because every one of them is a way this module could ship
looking impressive and saying nothing.
"""

from __future__ import annotations

from datetime import date

import pytest

from firm.core.facts.store import Fact
from firm.core.pipeline.derive import Derivation, DerivedSet
from firm.core.pipeline.interrogate import (
    AnswerStatus,
    GapKind,
    _format,
    interrogate,
)

AS_OF = date(2026, 7, 30)


def fact(metric: str, value: float, *, grade: str = "B", unit: str = "INR_cr") -> Fact:
    return Fact(
        fact_id=f"src-{metric}:1", doc_id="doc-1", ticker="TESTCO", metric=metric, period="FY26",
        value=value, unit=unit, locator=f"{metric} row", published_at=date(2026, 4, 1), grade=grade,
        extractor_version="test@1.0.0",
    )


def derived(**values: float) -> DerivedSet:
    """A DerivedSet with real `Derivation` objects, so citations and fact ids are exercised too."""
    return DerivedSet(
        ticker="TESTCO", as_of=AS_OF,
        values={
            name: Derivation(name, value, f"formula for {name}", (fact(name, value),))
            for name, value in values.items()
        },
        missing={}, first_period="FY15", last_period="FY26",
    )


def registry(*questions: dict, line_item: str = "revenue") -> dict:
    return {
        "version": "1.0.0",
        "line_items": [
            {"id": line_item, "label": "Revenue", "why": "because it matters",
             "questions": list(questions)},
        ],
    }


def only(interrogation) -> object:
    return interrogation.dossiers[0].answers[0]


# --------------------------------------------------------------------------------------------------
# ANSWERED: the number, its band clause, and its provenance


def test_answered_question_renders_template_band_and_citation():
    """An answered question carries the number, the judgment clause, and the derivation's citation."""
    spec = {
        "id": "revenue_rate", "question": "How fast?", "metric": "revenue_cagr", "unit": "pct",
        "template": "Revenue compounded at {v} across {window}.",
        "bands": [{"at_least": 0.15, "says": "fast enough for a 5x"}, {"says": "too slow"}],
        "severity": "high",
    }
    answer = only(interrogate(derived(revenue_cagr=0.22), ["MANUFACTURER"], registry(spec)))

    assert answer.status is AnswerStatus.ANSWERED
    assert answer.gap is GapKind.NONE
    assert "22.0%" in answer.finding
    assert "FY15-FY26" in answer.finding
    assert answer.finding.endswith("fast enough for a 5x.")
    assert answer.citation is not None and answer.citation.fact_id == "derived:revenue_cagr"
    assert answer.fact_ids == ("src-revenue_cagr:1",)


def test_first_matching_band_wins_and_a_bare_band_is_the_fallback():
    """Bands read top-down like an analyst's own thresholds; the last, conditionless one always matches."""
    spec = {
        "id": "q", "question": "?", "metric": "m", "unit": "pct", "template": "{v}",
        "bands": [
            {"at_least": 0.20, "says": "excellent"},
            {"at_least": 0.10, "says": "adequate"},
            {"says": "poor"},
        ],
    }
    assert "excellent" in only(interrogate(derived(m=0.25), [], registry(spec))).finding
    assert "adequate" in only(interrogate(derived(m=0.12), [], registry(spec))).finding
    assert "poor" in only(interrogate(derived(m=0.01), [], registry(spec))).finding


def test_at_most_band_bounds_from_above():
    spec = {"id": "q", "question": "?", "metric": "m", "unit": "ratio", "template": "{v}",
            "bands": [{"at_most": 0.0, "says": "negative"}, {"says": "positive"}]}
    assert "negative" in only(interrogate(derived(m=-1.0), [], registry(spec))).finding
    assert "positive" in only(interrogate(derived(m=1.0), [], registry(spec))).finding


def test_against_metric_is_rendered_and_degrades_to_unavailable():
    """A 'X versus Y' question still answers when only X exists — it says the comparator is unavailable."""
    spec = {"id": "q", "question": "?", "metric": "expense_cagr", "against": "revenue_cagr",
            "unit": "pct", "template": "Expenses {v} against revenue {a}."}

    both = only(interrogate(derived(expense_cagr=0.11, revenue_cagr=0.09), [], registry(spec)))
    assert both.finding == "Expenses 11.0% against revenue 9.0%."

    one = only(interrogate(derived(expense_cagr=0.11), [], registry(spec)))
    assert "unavailable" in one.finding


# --------------------------------------------------------------------------------------------------
# The gap distinction — the subtlest thing in the module


def test_missing_input_is_a_disclosure_gap_and_names_the_absent_row():
    """`DerivedSet.missing` means the pipeline asked and the source did not answer: about the COMPANY."""
    ds = DerivedSet("TESTCO", AS_OF, {}, {"cum_cfo_pat": ("cashflow:CFO FY26",)}, "FY15", "FY26")
    spec = {"id": "q", "question": "?", "metric": "cum_cfo_pat", "severity": "high",
            "needs": ["the audited cash-flow statement"]}
    answer = only(interrogate(ds, [], registry(spec)))

    assert answer.status is AnswerStatus.UNANSWERED
    assert answer.gap is GapKind.DISCLOSURE
    assert "cashflow:CFO FY26" in answer.reason


def test_never_attempted_metric_is_a_capability_gap_not_the_companys_fault():
    """A metric absent from BOTH values and missing was never computed — that gap is ours, not theirs.

    This is the distinction that stops the firm marking a company down for its own unfinished extractor.
    """
    spec = {"id": "q", "question": "?", "metric": "receivable_days", "severity": "high",
            "needs": ["balance_sheet:Trade Receivables"]}
    answer = only(interrogate(derived(revenue_cagr=0.1), [], registry(spec)))

    assert answer.status is AnswerStatus.UNANSWERED
    assert answer.gap is GapKind.CAPABILITY
    assert "not in the filing" in answer.reason or "extraction" in answer.reason


def test_question_with_no_metric_is_a_capability_gap_and_still_gets_printed():
    """The questions that matter most (buyer concentration, related-party flows) have no metric at all.

    They must still appear, with `needs` naming the row — that is the whole point of asking them.
    """
    spec = {"id": "concentration", "question": "Who are the buyers?", "severity": "high",
            "needs": ["Ind AS 108 segment note", "credit-risk note"]}
    answer = only(interrogate(derived(), [], registry(spec)))

    assert answer.status is AnswerStatus.UNANSWERED
    assert answer.gap is GapKind.CAPABILITY
    assert answer.needs == ("Ind AS 108 segment note", "credit-risk note")
    assert answer.question == "Who are the buyers?"


def test_only_disclosure_gaps_are_verdict_bearing():
    """`undisclosed_high` is what the verdict ladder consults; capability gaps must not appear in it."""
    ds = DerivedSet("TESTCO", AS_OF, {}, {"attempted": ("some row",)}, "FY15", "FY26")
    it = interrogate(ds, [], registry(
        {"id": "disclosed", "question": "?", "metric": "attempted", "severity": "high", "needs": ["x"]},
        {"id": "ours", "question": "?", "metric": "never_built", "severity": "high", "needs": ["y"]},
        {"id": "nometric", "question": "?", "severity": "high", "needs": ["z"]},
    ))

    assert len(it.unanswered_high) == 3
    assert [a.question_id for a in it.undisclosed_high] == ["disclosed"]
    assert {a.question_id for a in it.capability_gaps} == {"ours", "nometric"}


# --------------------------------------------------------------------------------------------------
# Refusing to narrate a meaningless number


def test_implausible_value_is_unanswered_rather_than_narrated():
    """ALKYLAMINE's cost of debt computes to 100% on a near-zero year-end balance.

    Printing that with a confident band clause would lend authority to a degenerate denominator, so the
    question is UNANSWERED and the reason carries the offending value.
    """
    spec = {
        "id": "debt_cost", "question": "?", "metric": "cost_of_debt_latest", "unit": "pct",
        "template": "Cost of debt is {v}.",
        "plausible": {"min": 0.02, "max": 0.30, "because": "interest is a flow, borrowings a snapshot"},
        "bands": [{"says": "consistent with bank funding"}],
        "needs": ["borrowings note — average balance"],
    }
    answer = only(interrogate(derived(cost_of_debt_latest=1.0), [], registry(spec)))

    assert answer.status is AnswerStatus.UNANSWERED
    assert answer.gap is GapKind.DISCLOSURE
    assert "100.0%" in answer.reason
    assert "interest is a flow" in answer.reason
    assert answer.value == 1.0            # the number is retained for audit, just not narrated
    assert "consistent with bank funding" not in answer.reason


def test_value_inside_the_plausible_range_is_narrated_normally():
    spec = {"id": "q", "question": "?", "metric": "cost_of_debt_latest", "unit": "pct",
            "template": "Cost of debt is {v}.", "plausible": {"min": 0.02, "max": 0.30},
            "bands": [{"says": "consistent with bank funding"}]}
    answer = only(interrogate(derived(cost_of_debt_latest=0.09), [], registry(spec)))

    assert answer.status is AnswerStatus.ANSWERED
    assert "9.0%" in answer.finding


# --------------------------------------------------------------------------------------------------
# Model scoping — a suppressed question is answered correctly, not skipped


def test_excluded_model_suppresses_with_a_reason_and_leaves_coverage_intact():
    """Receivable days on a bank is an invalid question (ADR-0002), so suppressing it is CORRECT.

    It must therefore leave the denominator alone: a bank must not look opaque for questions that never
    applied to it.
    """
    it = interrogate(derived(revenue_cagr=0.1), ["LENDER"], registry(
        {"id": "answered", "question": "?", "metric": "revenue_cagr", "unit": "pct", "template": "{v}"},
        {"id": "wc_days", "question": "?", "severity": "high", "needs": ["x"],
         "exclude_models": ["LENDER", "BANK"]},
    ))
    suppressed = it.dossiers[0].answers[1]

    assert suppressed.status is AnswerStatus.NOT_APPLICABLE
    assert "LENDER" in suppressed.reason
    assert not suppressed.counts_against_coverage
    assert it.coverage == 1.0            # one applicable question, answered


def test_models_allowlist_suppresses_when_the_company_is_a_different_shape():
    spec = {"id": "gnpa", "question": "?", "severity": "high", "needs": ["x"], "models": ["LENDER"]}
    answer = only(interrogate(derived(), ["MANUFACTURER"], registry(spec)))

    assert answer.status is AnswerStatus.NOT_APPLICABLE
    assert "LENDER" in answer.reason and "MANUFACTURER" in answer.reason


def test_allowlist_reason_is_explicit_when_no_model_was_detected():
    spec = {"id": "gnpa", "question": "?", "needs": ["x"], "models": ["LENDER"]}
    answer = only(interrogate(derived(), [], registry(spec)))
    assert "no specific model" in answer.reason


# --------------------------------------------------------------------------------------------------
# Aggregates


def test_coverage_is_answered_over_applicable():
    it = interrogate(derived(a=1.0, b=2.0), [], registry(
        {"id": "q1", "question": "?", "metric": "a", "template": "{v}"},
        {"id": "q2", "question": "?", "metric": "b", "template": "{v}"},
        {"id": "q3", "question": "?", "needs": ["x"]},
        {"id": "q4", "question": "?", "needs": ["x"], "exclude_models": ["LENDER"]},
    ))
    # q4 applies (not a lender), so 2 answered of 4 applicable.
    assert it.coverage == pytest.approx(0.5)
    assert it.dossiers[0].coverage == pytest.approx(0.5)


def test_coverage_of_a_line_item_with_nothing_applicable_is_one_not_zero():
    """A line item whose every question was correctly suppressed is fully handled, not 0% covered."""
    it = interrogate(derived(), ["BANK"], registry(
        {"id": "q", "question": "?", "needs": ["x"], "exclude_models": ["BANK"]},
    ))
    assert it.dossiers[0].coverage == 1.0
    assert it.coverage == 1.0


def test_needs_index_deduplicates_and_preserves_question_order():
    """The backlog is ordered by the questions that raised it, so the first entry is the first gap."""
    it = interrogate(derived(), [], registry(
        {"id": "q1", "question": "?", "needs": ["cash balance", "interest income"]},
        {"id": "q2", "question": "?", "needs": ["cash balance", "borrowings note"]},
    ))
    assert it.needs_index() == ("cash balance", "interest income", "borrowings note")


def test_answered_questions_contribute_nothing_to_the_backlog():
    it = interrogate(derived(m=0.1), [], registry(
        {"id": "q", "question": "?", "metric": "m", "template": "{v}", "needs": ["should not appear"]},
    ))
    assert it.needs_index() == ()


def test_window_falls_back_when_the_period_span_is_unknown():
    ds = DerivedSet("TESTCO", AS_OF, {}, {}, None, None)
    spec = {"id": "q", "question": "?", "needs": ["x"], "template": "across {window}"}
    it = interrogate(ds, [], registry(spec))
    assert it.dossiers[0].answers[0].status is AnswerStatus.UNANSWERED


def test_question_text_is_whitespace_normalised():
    """Registry questions are written as folded YAML block scalars; the report needs one clean line."""
    spec = {"id": "q", "question": "a question\n  that wrapped\n  over lines\n", "needs": ["x"]}
    assert only(interrogate(derived(), [], registry(spec))).question == (
        "a question that wrapped over lines"
    )


# --------------------------------------------------------------------------------------------------
# Formatting


@pytest.mark.parametrize(("value", "unit", "expected"), [
    (0.1124, "pct", "11.2%"),
    (0.0028, "pp", "+0.3pp"),
    (-0.024, "pp", "-2.4pp"),
    (1521.0, "inr_cr", "₹1,521 crore"),
    (-134.0, "inr_cr", "-₹134 crore"),
    (1.4813, "x", "1.48x"),
    (1.27, "ratio", "1.27"),
])
def test_format_renders_each_unit_the_way_an_analyst_writes_it(value, unit, expected):
    assert _format(value, unit) == expected


def test_implausible_reason_is_a_single_line():
    """`because:` is a folded YAML scalar and arrives with newlines.

    Left alone, the trailing break splits the markdown `needs:` list that renders directly beneath it.
    """
    spec = {"id": "q", "question": "?", "metric": "m", "unit": "pct", "template": "{v}",
            "plausible": {"max": 0.3, "because": "interest is a flow\nborrowings a snapshot\n"},
            "needs": ["x"]}
    answer = only(interrogate(derived(m=1.0), [], registry(spec)))
    assert "\n" not in answer.reason
    assert "interest is a flow borrowings a snapshot" in answer.reason
