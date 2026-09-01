"""The questions-for-management artifact (ADR-0066).

The owner's use for this system is not only a verdict — it is to walk into a meeting with the company
and ask the right things. So these are computed, not narrated: an agent can neither add a question nor
remove one, and the same inputs produce the same list on every run.

The invariant with the sharpest edge is whose gap a question represents. A datum the company did not
disclose is theirs to answer. A datum the firm has not built an extractor for is ours, and putting it
in front of management would spend the one meeting the owner gets on our unfinished parser (ADR-0051).
"""

from __future__ import annotations

from firm.core.compute.models import BusinessModel
from firm.core.compute.quality import ForensicMetrics
from firm.core.config import load_thresholds, report_policy
from firm.core.pipeline import derive as D
from firm.core.pipeline.checks import CheckEvaluation
from firm.core.report.assemble import Narration, NotesReview, VerdictDecision, assemble_report
from firm.core.report.questions import management_questions
from firm.core.report.render import render_markdown
from firm.schemas.evidence import EvidenceGraph
from firm.schemas.report import CheckOutcome, CheckRecord, GapKind, Verdict
from tests.conftest import AS_OF, clean_series, seed_store

POLICY = report_policy()
THRESHOLDS = load_thresholds()
FULL_NOTES = NotesReview(coverage=1.0, substantive_share=0.6, notes_total=10, scanned=True)


def _evaluation(*, flagged: int = 0, unavailable: int = 0, total: int = 6,
                gap: GapKind = GapKind.DISCLOSURE) -> CheckEvaluation:
    records, names = [], [f"check_{i}" for i in range(total)]
    for i, name in enumerate(names):
        if i < flagged:
            records.append(CheckRecord(name=name, outcome=CheckOutcome.FLAG,
                                       detail="ΣCFO/ΣPAT 0.21 < 0.70", fact_ids=[f"fact:{name}"]))
        elif i < flagged + unavailable:
            records.append(CheckRecord(name=name, outcome=CheckOutcome.UNAVAILABLE,
                                       reason="cash and cash equivalents not found", gap=gap))
        else:
            records.append(CheckRecord(name=name, outcome=CheckOutcome.PASS, detail="ok"))
    return CheckEvaluation(tuple(records), ForensicMetrics(), tuple(names))


def test_a_flagged_check_becomes_a_question_management_can_answer():
    questions = management_questions(_evaluation(flagged=1), FULL_NOTES)
    assert len(questions) == 1
    q = questions[0]
    assert "check_0" in q.question and "ΣCFO/ΣPAT 0.21" in q.question
    assert q.severity == "high" and q.source == "check_0"
    assert q.fact_ids == ["fact:check_0"]
    assert q.why                                  # a question with no consequence does not earn a slot


def test_only_the_companys_gaps_are_put_to_the_company():
    """ADR-0051, at the sharpest point: our unfinished extractor is not their question to answer."""
    theirs = management_questions(_evaluation(unavailable=2, gap=GapKind.DISCLOSURE), FULL_NOTES)
    ours = management_questions(_evaluation(unavailable=2, gap=GapKind.CAPABILITY), FULL_NOTES)

    assert len(theirs) == 2 and all("Where is it disclosed" in q.question for q in theirs)
    assert ours == []


def test_a_mandated_disclosure_the_walker_could_not_find_is_asked_about():
    notes = NotesReview(coverage=1.0, substantive_share=0.6, notes_total=10, scanned=True,
                        disclosure_gaps=("Schedule III promoter loans row",))
    questions = management_questions(_evaluation(), notes)
    assert len(questions) == 1
    assert "Schedule III promoter loans row" in questions[0].question
    assert questions[0].source == "notes"


def test_questions_are_high_severity_first_and_never_duplicated():
    questions = management_questions(_evaluation(flagged=2, unavailable=2), FULL_NOTES)
    severities = [q.severity for q in questions]
    assert severities == sorted(severities, key=lambda s: {"high": 0, "medium": 1, "low": 2}[s])
    assert len({q.question for q in questions}) == len(questions)


def test_a_company_that_disclosed_everything_is_asked_nothing():
    """An empty list is an honest answer. It is not the same as having failed to look."""
    assert management_questions(_evaluation(), FULL_NOTES) == []


def test_every_report_carries_them_and_renders_them(store):
    """Not a fallback-path feature: the section is on the report whatever the verdict (ADR-0066)."""
    seed_store(store, "ACME", clean_series())
    facts = D.load_company_facts(store, "ACME", AS_OF)
    derived = D.derive_metrics(facts)
    report = assemble_report(
        ticker="ACME", company_name="ACME Limited", as_of=AS_OF, run_id="2026-07-30-testrun",
        decision=VerdictDecision(Verdict.FORENSIC_CAUTION, "check_0 fired"),
        derived=derived, evaluation=_evaluation(flagged=1, unavailable=1),
        models=[BusinessModel.MANUFACTURER], notes=FULL_NOTES, graph=EvidenceGraph(),
        load_bearing_ids=(), narration=Narration(thesis="t", anti_thesis="a", open_questions=("q",)),
        agent_versions={}, forensic=THRESHOLDS["forensic"], policy=POLICY,
    )

    assert len(report.management_questions) == 2
    markdown = render_markdown(report)
    assert "## Questions for management" in markdown
    assert "Why it matters:" in markdown
    assert "check_0" in markdown
