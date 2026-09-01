"""Tests for the dual-verdict publication gates (ADR-0016 / REPORT_ARCHITECTURE §4)."""

from datetime import date

from firm.core.config import report_policy
from firm.core.validators.publication import (
    legal_framing,
    line_item_integrity,
    symmetry,
    validate_report,
    verified_clean_completeness,
)
from firm.schemas._base import Confidence, Grade
from firm.schemas.report import (
    AnswerStatus,
    CheckOutcome,
    CheckRecord,
    Criterion,
    GapKind,
    LineItemAnswer,
    LineItemSection,
    ReportClaim,
    ResearchReport,
    Verdict,
    VerifiedCleanChecklist,
)

POLICY = report_policy()

CONF = Confidence(value=0.7, evidence_count=6, lowest_grade_relied_on=Grade.A, rationale="6 grade-A facts")


def _criterion(load_bearing=False, metric="gross_margin"):
    return Criterion(
        statement="margin holds above 30%", metric=metric, operator=">=", threshold=0.30,
        resolve_by=date(2027, 5, 31), load_bearing=load_bearing,
    )


def _clean_checklist(**kw):
    defaults = {
        "business_models": ["MANUFACTURER"],
        "expected_checks": ["cumulative_cfo_pat", "receivables_divergent"],
        "records": [
            CheckRecord(name="cumulative_cfo_pat", outcome=CheckOutcome.PASS, detail="1.15",
                        fact_ids=["f1"]),
            CheckRecord(name="receivables_divergent", outcome=CheckOutcome.PASS, detail="gap 0.02",
                        fact_ids=["f2"]),
        ],
        "note_coverage": 1.0,
    }
    defaults.update(kw)
    return VerifiedCleanChecklist(**defaults)


def _report(**kw):
    defaults = {
        "ticker": "ABC", "company_name": "ABC Ltd", "as_of": date(2026, 7, 30), "run_id": "r1",
        "verdict": Verdict.COMPOUNDER, "confidence": CONF, "checklist": _clean_checklist(),
        "thesis": "Compounds if capacity fills at current margins.",
        "anti_thesis": "A spread collapse breaks the whole case.",
        "kill_criteria": [_criterion(True), _criterion(metric="roic"), _criterion(metric="revenue")],
        "open_questions": ["What is maintenance vs growth capex?"],
    }
    defaults.update(kw)
    return ResearchReport(**defaults)


# ---- P1 verified-clean completeness --------------------------------------------------------------
def test_p1_clean_report_passes():
    assert verified_clean_completeness(_report()) == []


def test_p1_missing_expected_check_blocks_publication():
    cl = _clean_checklist(records=[
        CheckRecord(name="cumulative_cfo_pat", outcome=CheckOutcome.PASS),
    ])
    v = verified_clean_completeness(_report(checklist=cl))
    assert len(v) == 1 and v[0].rule == "P1_incomplete_checklist"
    assert "receivables_divergent" in v[0].detail


def test_p1_unavailable_or_na_requires_reason():
    cl = _clean_checklist(records=[
        CheckRecord(name="cumulative_cfo_pat", outcome=CheckOutcome.UNAVAILABLE),          # no reason
        CheckRecord(name="receivables_divergent", outcome=CheckOutcome.NOT_APPLICABLE,
                    reason="suppressed for lenders (ADR-0002)"),
    ])
    v = verified_clean_completeness(_report(checklist=cl))
    assert len(v) == 1 and "requires a reason" in v[0].detail


def test_p1_note_coverage_below_100_blocks():
    cl = _clean_checklist(note_coverage=0.75, notes_undispositioned=["30"])
    v = verified_clean_completeness(_report(checklist=cl))
    assert any("note coverage" in x.detail for x in v)


def test_p1_insufficient_disclosure_may_publish_the_unreadable_filing_as_its_finding():
    """ADR-0014/0016: opacity is published, not swallowed — otherwise the one verdict the firm exists to
    give on an opaque company could never ship, because the gap is what blocks it."""
    cl = _clean_checklist(note_coverage=0.0, notes_undispositioned=[])
    cl.records[1] = CheckRecord(name="receivables_divergent", outcome=CheckOutcome.UNAVAILABLE,
                                reason="not broken out in any filing readable as text")
    v = verified_clean_completeness(
        _report(verdict=Verdict.INSUFFICIENT_DISCLOSURE, checklist=cl))
    assert v == []


def test_p1_insufficient_disclosure_must_still_be_evidenced():
    """"We could not tell" with nothing missing and every note read is not a finding."""
    v = verified_clean_completeness(
        _report(verdict=Verdict.INSUFFICIENT_DISCLOSURE, checklist=_clean_checklist()))
    assert len(v) == 1 and "not evidenced" in v[0].detail


# ---- P2 symmetry ---------------------------------------------------------------------------------
def test_p2_positive_report_needs_kill_criteria():
    v = symmetry(_report(kill_criteria=[_criterion(True)]))
    assert any("kill criteria" in x.detail for x in v)


def test_p2_positive_report_needs_a_load_bearing_kill_criterion():
    v = symmetry(_report(kill_criteria=[_criterion(), _criterion(metric="a"), _criterion(metric="b")]))
    assert any("load_bearing" in x.detail for x in v)


def test_p2_negative_report_needs_rehabilitation_criteria():
    rep = _report(verdict=Verdict.RETURN_HURDLE_NOT_CLEARED, kill_criteria=[])
    v = symmetry(rep)
    assert any(x.field == "rehabilitation_criteria" for x in v)
    # with them, symmetry is satisfied (no kill criteria needed for a withholding verdict)
    ok = _report(verdict=Verdict.RETURN_HURDLE_NOT_CLEARED, kill_criteria=[],
                 rehabilitation_criteria=[_criterion()])
    assert symmetry(ok) == []


def test_p2_opposing_case_is_mandatory_both_ways():
    assert any(x.field == "anti_thesis" for x in symmetry(_report(anti_thesis="  ")))
    assert any(x.field == "thesis" for x in symmetry(_report(thesis="")))


def test_p2_empty_open_questions_is_a_failure():
    assert any(x.field == "open_questions" for x in symmetry(_report(open_questions=[])))


# ---- P3 legal framing ----------------------------------------------------------------------------
def test_p3_hedged_forensic_language_passes():
    rep = _report(
        verdict=Verdict.FORENSIC_CAUTION,
        forensic_narrative=(
            "The evidence indicates the counterparty appears to be a related party; the company "
            "should clarify. We believe this is fraudulent in effect, though unproven."
        ),
        checklist=_clean_checklist(records=[
            CheckRecord(name="cumulative_cfo_pat", outcome=CheckOutcome.FLAG, detail="0.42"),
            CheckRecord(name="receivables_divergent", outcome=CheckOutcome.FLAG, detail="gap 3.1"),
        ]),
        replication_notes=["Search the MCA registry for the counterparty's directors."],
        load_bearing_points=[ReportClaim(text="CFO/PAT 0.42", kind="observation", lowest_grade=Grade.A)],
        rehabilitation_criteria=[_criterion()],
    )
    assert legal_framing(rep) == []


def test_p3_unhedged_accusation_blocks_publication():
    rep = _report(forensic_narrative="The company is a fraud and the promoter committed fraud.")
    v = legal_framing(rep)
    assert v and all(x.rule == "P3_legal_framing" for x in v)


def test_p3_forensic_caution_needs_replication_and_a_flag():
    rep = _report(verdict=Verdict.FORENSIC_CAUTION, rehabilitation_criteria=[_criterion()],
                  forensic_narrative="Findings appear material.")
    fields = {x.field for x in legal_framing(rep)}
    assert "replication_notes" in fields          # must be reproducible by a third party
    assert "checklist.records" in fields          # a caution with no FLAG is unevidenced


def test_p3_caution_cannot_rest_only_on_grade_c_d():
    rep = _report(
        verdict=Verdict.FORENSIC_CAUTION,
        forensic_narrative="Evidence indicates a gap.",
        replication_notes=["repeat the search"],
        rehabilitation_criteria=[_criterion()],
        checklist=_clean_checklist(records=[
            CheckRecord(name="cumulative_cfo_pat", outcome=CheckOutcome.FLAG),
            CheckRecord(name="receivables_divergent", outcome=CheckOutcome.PASS),
        ]),
        load_bearing_points=[
            ReportClaim(text="a former employee said so", kind="inference", lowest_grade=Grade.C),
            ReportClaim(text="a news article implied it", kind="inference", lowest_grade=Grade.D),
        ],
    )
    assert any(x.field == "load_bearing_points" for x in legal_framing(rep))


# ---- aggregate ------------------------------------------------------------------------------------
def test_validate_report_clean_positive_ships():
    assert validate_report(_report()) == []


def test_validate_report_aggregates_all_rules():
    broken = _report(
        verdict=Verdict.COMPOUNDER, kill_criteria=[], open_questions=[], anti_thesis="",
        forensic_narrative="The promoter is a fraudster.",
        checklist=_clean_checklist(note_coverage=0.5, records=[]),
    )
    rules = {v.rule for v in validate_report(broken)}
    assert rules == {"P1_incomplete_checklist", "P2_asymmetric", "P3_legal_framing"}


def test_report_verdict_polarity_helpers():
    assert _report(verdict=Verdict.COMPOUNDER).is_positive
    for v in (Verdict.RETURN_HURDLE_NOT_CLEARED, Verdict.WATCH, Verdict.FORENSIC_CAUTION,
              Verdict.INSUFFICIENT_DISCLOSURE):
        rep = _report(verdict=v, rehabilitation_criteria=[_criterion()])
        assert rep.is_negative and not rep.is_positive


def test_checklist_outcome_lookup():
    cl = _clean_checklist()
    assert cl.outcome_of("cumulative_cfo_pat") is CheckOutcome.PASS
    assert cl.outcome_of("nope") is None


# ------------------------------------------------------------------------------------------------
# P4 line-item integrity (ADR-0022)


def _answer(**kw):
    defaults = {
        "question_id": "q1", "question": "Where does revenue come from?",
        "status": AnswerStatus.UNANSWERED, "severity": "high", "gap": GapKind.DISCLOSURE,
        "needs": ["Ind AS 108 segment note"], "reason": "the sources read do not disclose it",
    }
    defaults.update(kw)
    return LineItemAnswer(**defaults)


def _section(*answers, line_item="revenue"):
    return LineItemSection(line_item=line_item, label="Revenue", coverage=0.0, answers=list(answers))


def test_p4_unanswered_question_must_say_what_would_answer_it():
    """A question printed with a blank answer is worse than an omitted one — it implies someone looked."""
    report = _report(line_items=[_section(_answer(needs=[], reason=""))])
    rules = {v.rule for v in line_item_integrity(report, policy=POLICY)}
    assert "P4_line_item_integrity" in rules


def test_p4_accepts_a_reason_without_needs_and_needs_without_a_reason():
    """Either one discharges the duty: name the fix, or say why there isn't one."""
    only_needs = _report(verdict=Verdict.WATCH, rehabilitation_criteria=[_criterion()],
                         line_items=[_section(_answer(reason=""))])
    only_reason = _report(verdict=Verdict.WATCH, rehabilitation_criteria=[_criterion()],
                          line_items=[_section(_answer(needs=[]))])
    assert not line_item_integrity(only_needs, policy=POLICY)
    assert not line_item_integrity(only_reason, policy=POLICY)


def test_p4_not_applicable_must_carry_the_reason_it_was_suppressed():
    """Otherwise 'n/a' becomes the way to drop an inconvenient question — the P1 rule, one layer up."""
    report = _report(verdict=Verdict.WATCH, rehabilitation_criteria=[_criterion()], line_items=[
        _section(_answer(status=AnswerStatus.NOT_APPLICABLE, gap=GapKind.NONE, needs=[], reason=""))])
    assert [v.rule for v in line_item_integrity(report, policy=POLICY)] == ["P4_line_item_integrity"]


def test_p4_blocks_a_compounder_whose_business_could_not_be_read():
    """A compounding claim may not rest on lines the filings were asked about and could not answer."""
    report = _report(line_items=[_section(_answer())])
    violations = line_item_integrity(report, policy=POLICY)
    assert any("compounding claim cannot rest" in v.detail for v in violations)


def test_p4_does_not_charge_a_company_for_the_firms_own_missing_extractor():
    """The distinction the module exists to protect: a CAPABILITY gap is ours, and must not block.

    If it did, the firm would reject every good business it has not yet built a parser for, and call that
    rigour. Confidence carries this instead.
    """
    report = _report(line_items=[_section(_answer(gap=GapKind.CAPABILITY))])
    assert not line_item_integrity(report, policy=POLICY)


def test_p4_lets_a_withheld_verdict_publish_its_own_gaps():
    """INSUFFICIENT_DISCLOSURE exists to report exactly this, so the gate must not block it."""
    report = _report(
        verdict=Verdict.INSUFFICIENT_DISCLOSURE,
        checklist=_clean_checklist(records=[
            CheckRecord(name="cumulative_cfo_pat", outcome=CheckOutcome.PASS, detail="1.15"),
            CheckRecord(name="receivables_divergent", outcome=CheckOutcome.UNAVAILABLE,
                        reason="receivables not disclosed"),
        ]),
        rehabilitation_criteria=[_criterion()],
        line_items=[_section(_answer())],
    )
    assert not line_item_integrity(report, policy=POLICY)


def test_p4_is_wired_into_validate_report():
    """The gate has to be in the aggregate, not merely defined — an unwired gate is decoration."""
    report = _report(line_items=[_section(_answer())])
    assert "P4_line_item_integrity" in {v.rule for v in validate_report(report, policy=POLICY)}
