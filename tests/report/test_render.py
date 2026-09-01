"""Tests for the dual-verdict report renderer (ADR-0016)."""

import json
from datetime import date

import pytest

from firm.core.report.render import (
    ReportNotPublishable,
    render_json,
    render_markdown,
    write_report,
)
from firm.schemas._base import Citation, Confidence, Grade
from firm.schemas.report import (
    CheckOutcome,
    CheckRecord,
    Criterion,
    ReportClaim,
    ResearchReport,
    Verdict,
    VerifiedCleanChecklist,
)

CONF = Confidence(value=0.72, evidence_count=8, lowest_grade_relied_on=Grade.A, rationale="8 grade-A facts")
CITE = Citation(fact_id="f-roic", doc_id="bse:ar:2026", locator="p.88 l.12",
                published_at=date(2026, 5, 28), extractor_version="tables@1", grade=Grade.A)


def _crit(lb=False, metric="gross_margin"):
    return Criterion(statement=f"{metric} holds", metric=metric, operator=">=", threshold=0.3,
                     resolve_by=date(2027, 5, 31), load_bearing=lb)


def _positive_report(**kw):
    defaults = dict(
        ticker="ABC", company_name="ABC Chemicals Ltd", as_of=date(2026, 7, 30), run_id="run-1",
        verdict=Verdict.COMPOUNDER, confidence=CONF,
        agent_versions={"forensic_accountant": "1.0.0"},
        executive_summary="Self-funds the growth its price implies.",
        load_bearing_points=[ReportClaim(text="Incremental ROIC 24%", kind="observation",
                                         lowest_grade=Grade.A, citations=[CITE])],
        business_model_plain="Sells amines to pharma customers.",
        computed_facts={"roic": 0.24, "cumulative_cfo_pat": 1.15},
        fact_citations={"roic": CITE},
        checklist=VerifiedCleanChecklist(
            business_models=["MANUFACTURER"],
            expected_checks=["cumulative_cfo_pat", "receivables_divergent", "gnpa_drift"],
            records=[
                CheckRecord(name="cumulative_cfo_pat", outcome=CheckOutcome.PASS, detail="1.15",
                            fact_ids=["f-cfo"]),
                CheckRecord(name="receivables_divergent", outcome=CheckOutcome.PASS, detail="gap 0.02"),
                CheckRecord(name="gnpa_drift", outcome=CheckOutcome.NOT_APPLICABLE,
                            reason="not a lender (playbook suppressed)"),
            ],
            note_coverage=1.0,
            disclosure_gaps=["title_deeds"],
        ),
        forensic_narrative="Cash converts; the audited notes agree with the numbers.",
        management_narrative="Promise-vs-delivery 8/10.",
        valuation_narrative="Reverse DCF implies 18% FCF CAGR.",
        thesis="Compounds if capacity fills at current spreads.",
        anti_thesis="A spread collapse breaks it.",
        kill_criteria=[_crit(True), _crit(metric="roic"), _crit(metric="revenue")],
        open_questions=["Maintenance vs growth capex split?"],
        unavailable_items=["Segment-level capex (not disclosed)"],
        replication_notes=["Pull the FY26 AR from BSE and re-read note 29."],
    )
    defaults.update(kw)
    return ResearchReport(**defaults)


# ---- markdown ------------------------------------------------------------------------------------
def test_markdown_leads_with_outcome_verdict_and_confidence():
    """The headline carries both axes (ADR-0067): the four-value outcome and the specific verdict."""
    md = render_markdown(_positive_report())
    assert md.startswith("# ABC Chemicals Ltd (ABC) — research note")
    assert "**Outcome: `PASS` · Verdict: `COMPOUNDER` — Passes the compounding test**" in md
    assert "confidence 0.72" in md and "lowest grade A" in md
    assert "Research artifact only" in md            # disclaimer always present


def test_markdown_shows_passes_not_just_flags():
    md = render_markdown(_positive_report())
    assert "Verified-clean checklist" in md
    assert "a clean verdict with an invisible process is worth nothing" in md
    assert "`cumulative_cfo_pat` | ✅ pass" in md
    # a suppressed check renders with its reason, never silently vanishing
    assert "`gnpa_drift` | — n/a | not a lender (playbook suppressed)" in md


def test_markdown_numbers_carry_citation_tokens():
    md = render_markdown(_positive_report())
    assert "`[fact:f-roic]` bse:ar:2026 p.88 l.12 (grade A)" in md
    # a fact with no citation is loudly marked rather than rendered as if sourced
    assert "**UNCITED**" in md                       # cumulative_cfo_pat has no citation entry


def test_markdown_always_renders_both_thesis_and_antithesis():
    md = render_markdown(_positive_report())
    assert "## Thesis" in md and "## Anti-thesis (the strongest case against)" in md
    md2 = render_markdown(_positive_report(thesis="", anti_thesis=""))
    assert md2.count("_none stated_") == 2           # never silently omitted


def test_markdown_renders_criteria_tables_and_gaps():
    md = render_markdown(_positive_report())
    assert "Kill criteria — what would break this thesis" in md
    assert "`>= 0.3`" in md and "2027-05-31" in md and "**yes**" in md
    assert "Disclosure gaps" in md and "title_deeds" in md
    assert "Not available from primary sources" in md
    assert "Replication" in md


def test_markdown_negative_verdict_renders_rehabilitation():
    rep = _positive_report(
        verdict=Verdict.QUALITY_WRONG_PRICE, kill_criteria=[],
        rehabilitation_criteria=[_crit(metric="pe_ratio")],
    )
    md = render_markdown(rep)
    assert "Quality business, wrong price today" in md
    assert "Rehabilitation criteria — what would reverse this verdict" in md
    assert "Kill criteria" not in md


def test_markdown_omits_empty_optional_sections():
    lean = ResearchReport(
        ticker="X", company_name="X Ltd", as_of=date(2026, 1, 1), run_id="r",
        verdict=Verdict.WATCH, confidence=CONF,
    )
    md = render_markdown(lean)
    for absent in ("## Executive summary", "## Valuation", "## Open questions", "## Replication",
                   "The numbers"):
        assert absent not in md


# ---- json ----------------------------------------------------------------------------------------
def test_render_json_is_the_validated_object():
    payload = json.loads(render_json(_positive_report()))
    assert payload["verdict"] == "COMPOUNDER"
    assert payload["checklist"]["note_coverage"] == 1.0
    assert payload["computed_facts"]["roic"] == 0.24


# ---- write_report is gated on the publication validators -----------------------------------------
def test_write_report_writes_both_artifacts(tmp_path):
    md_path, json_path = write_report(_positive_report(), tmp_path)
    assert md_path == tmp_path / "ABC" / "run-1" / "report.md"
    assert "COMPOUNDER" in md_path.read_text()
    assert json.loads(json_path.read_text())["ticker"] == "ABC"


def test_write_report_refuses_invalid_report(tmp_path):
    invalid = _positive_report(kill_criteria=[], open_questions=[])   # fails P2 symmetry
    with pytest.raises(ReportNotPublishable) as exc:
        write_report(invalid, tmp_path)
    assert any(v.rule == "P2_asymmetric" for v in exc.value.violations)
    assert not (tmp_path / "ABC").exists()           # nothing written on refusal


def test_write_report_force_persists_failing_draft(tmp_path):
    invalid = _positive_report(kill_criteria=[], open_questions=[])
    md_path, _ = write_report(invalid, tmp_path, force=True)
    assert md_path.exists()
