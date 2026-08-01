"""The publishable research report contract (ADR-0016, docs/REPORT_ARCHITECTURE.md).

Owner directive: the firm publishes a professional report **whatever the verdict** — a company that
passes gets a positive thesis, not silence. That makes two things structural rather than optional:

1. **A clean verdict must show its work.** "We found nothing" is worthless unless the report enumerates
   what was checked — hence `VerifiedCleanChecklist`, which carries every check that ran *including the
   passes*, each bound to the fact ids it consumed.
2. **Symmetry.** A positive report carries dated `kill_criteria`; a negative one carries
   `rehabilitation_criteria`. Both carry the opposing case. Enforced by
   `core/validators/publication.py`, not by good intentions.

Composes the shared primitives in `_base.py` (Citation/Confidence/Grade) so provenance and the
point-in-time contract travel with every claim (Laws 2 & 3).
"""

from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel, Field

from firm.schemas._base import Citation, Confidence, Grade


class Verdict(str, Enum):
    """Exactly one per report (REPORT_ARCHITECTURE §2). Never 'buy'/'sell' (SPEC §1)."""

    COMPOUNDER = "COMPOUNDER"                          # passed forensics + feasibility + valuation
    QUALITY_WRONG_PRICE = "QUALITY_WRONG_PRICE"        # clean business, price/feasibility fails today
    WATCH = "WATCH"                                    # promise, thesis not yet provable
    FORENSIC_CAUTION = "FORENSIC_CAUTION"              # red flags with a corroborated evidence chain
    INSUFFICIENT_DISCLOSURE = "INSUFFICIENT_DISCLOSURE"  # legally-public data missing/unreadable


#: Verdicts that assert a company is investable-quality — these must carry kill criteria.
POSITIVE_VERDICTS = frozenset({Verdict.COMPOUNDER})
#: Verdicts that withhold or warn — these must carry rehabilitation criteria (what would reverse them).
NEGATIVE_VERDICTS = frozenset({
    Verdict.QUALITY_WRONG_PRICE, Verdict.WATCH, Verdict.FORENSIC_CAUTION,
    Verdict.INSUFFICIENT_DISCLOSURE,
})


class CheckOutcome(str, Enum):
    PASS = "PASS"
    FLAG = "FLAG"
    NOT_APPLICABLE = "NOT_APPLICABLE"   # suppressed by the model playbook (ADR-0017)
    UNAVAILABLE = "UNAVAILABLE"         # inputs not disclosed — a signal, never a silent skip


class CheckRecord(BaseModel):
    """One deterministic check, with its result and the facts it consumed.

    `NOT_APPLICABLE` and `UNAVAILABLE` both require a `reason` — a check that simply vanished from a
    report is indistinguishable from one that was never run, which is what the validator forbids.
    """

    name: str
    outcome: CheckOutcome
    detail: str = ""
    reason: str = ""
    fact_ids: list[str] = Field(default_factory=list)


class VerifiedCleanChecklist(BaseModel):
    """The credibility backbone of a published report: every check in the applicable playbook, with
    passes shown. `expected` comes from the resolved playbook so omissions are detectable."""

    business_models: list[str] = Field(default_factory=list)
    expected_checks: list[str] = Field(default_factory=list)
    records: list[CheckRecord] = Field(default_factory=list)
    note_coverage: float = Field(default=0.0, ge=0.0, le=1.0)
    notes_undispositioned: list[int] = Field(default_factory=list)
    disclosure_gaps: list[str] = Field(default_factory=list)

    def outcome_of(self, name: str) -> CheckOutcome | None:
        for record in self.records:
            if record.name == name:
                return record.outcome
        return None


class AnswerStatus(str, Enum):
    ANSWERED = "ANSWERED"
    UNANSWERED = "UNANSWERED"          # asked, and the sources read cannot answer it — `needs` says what would
    NOT_APPLICABLE = "NOT_APPLICABLE"  # invalid for the detected business model


class GapKind(str, Enum):
    """Whose gap an unanswered question is — the distinction decides what the verdict may conclude.

    DISCLOSURE  the pipeline asked and the sources did not carry the row: evidence about the COMPANY, and
                allowed to degrade the verdict.
    CAPABILITY  no extractor exists yet, so the question was never actually put: evidence about US. It
                lowers confidence and joins the backlog, but must never be charged to the company —
                otherwise the firm rejects every business it cannot yet read and calls that rigour.
    """

    DISCLOSURE = "DISCLOSURE"
    CAPABILITY = "CAPABILITY"
    NONE = "NONE"


class LineItemAnswer(BaseModel):
    """One analyst question about one statement line, and what the sources could say (ADR-0022).

    The published question is the unit of work, not the published answer. A report that prints only what
    it could answer is indistinguishable from one where nothing else needed asking — so an `UNANSWERED`
    question ships with the exact primary-source row that would close it, and a `NOT_APPLICABLE` one
    ships with the reason it was suppressed.
    """

    question_id: str
    question: str
    status: AnswerStatus
    severity: str = Field(default="medium", description="high | medium | low")
    gap: GapKind = Field(default=GapKind.NONE, description="UNANSWERED only — whose gap it is")
    finding: str = ""                                     # deterministic sentence, ANSWERED only
    metric: str | None = None
    value: float | None = None
    citation: Citation | None = None
    fact_ids: list[str] = Field(default_factory=list)
    needs: list[str] = Field(default_factory=list)        # what would answer it, UNANSWERED only
    reason: str = ""


class LineItemSection(BaseModel):
    """Every question asked of one statement line (revenue, debt, working capital...)."""

    line_item: str
    label: str
    why: str = ""
    coverage: float = Field(default=0.0, ge=0.0, le=1.0)
    answers: list[LineItemAnswer] = Field(default_factory=list)


class Criterion(BaseModel):
    """A dated, observable, filing-resolvable event. Kill (for positives) or rehabilitation (negatives).

    'Resolvable from a future filing without human judgment' is the bar (SPEC §7.1) — a criterion that
    can never trigger is the failure mode `red_team` is warned about.
    """

    statement: str
    metric: str
    operator: str = Field(description="one of: >=, <=, >, <, ==")
    threshold: float
    resolve_by: date
    load_bearing: bool = False


class ReportClaim(BaseModel):
    """A claim in the report body, carrying its grade inline (house style §8: grade in the body, not a
    footnote)."""

    text: str
    kind: str = Field(description="observation | inference | speculation")
    lowest_grade: Grade
    citations: list[Citation] = Field(default_factory=list)


class ResearchReport(BaseModel):
    """The full publishable artifact (REPORT_ARCHITECTURE §3). Rendered to markdown + JSON."""

    # 1. header
    ticker: str
    company_name: str
    as_of: date
    run_id: str
    verdict: Verdict
    confidence: Confidence
    agent_versions: dict[str, str] = Field(default_factory=dict)
    disclaimer: str = (
        "Research artifact only. Not investment advice, not a recommendation to transact, and not an "
        "offer to buy or sell any security. Figures are computed deterministically from cited primary "
        "sources; anything not disclosed is reported as UNAVAILABLE."
    )

    # 2-3. summary + business
    executive_summary: str = ""
    load_bearing_points: list[ReportClaim] = Field(default_factory=list)
    business_model_plain: str = ""

    # 4. numbers
    computed_facts: dict[str, float] = Field(default_factory=dict)
    fact_citations: dict[str, Citation] = Field(default_factory=dict)

    # 4b. line-by-line interrogation (ADR-0022) — why each line moved, not just what it is
    line_items: list[LineItemSection] = Field(default_factory=list)
    line_item_coverage: float = Field(default=0.0, ge=0.0, le=1.0)
    #: Distinct primary-source rows that would close an unanswered question — the extraction backlog.
    disclosure_backlog: list[str] = Field(default_factory=list)

    # 5. forensic — including the passes
    checklist: VerifiedCleanChecklist = Field(default_factory=VerifiedCleanChecklist)
    forensic_narrative: str = ""

    # 4b. sector and business context — the agents whose work is comparative rather than company-only.
    # Added because `sector_analyst`, `macro_strategist` and `unit_economics_analyst` were validating,
    # entering `agent_versions` and then having their narratives dropped: the report named them as
    # contributors and printed nothing they wrote. An agent that runs and is not rendered is the
    # ADR-0034 failure in the other direction — the reader cannot tell it from one that never ran.
    sector_narrative: str = ""

    # 6-7. management + valuation
    management_narrative: str = ""
    valuation_narrative: str = ""

    # 8. thesis and anti-thesis — both, always
    thesis: str = ""
    anti_thesis: str = ""

    # 9. symmetric falsifiability
    kill_criteria: list[Criterion] = Field(default_factory=list)
    rehabilitation_criteria: list[Criterion] = Field(default_factory=list)

    # 10-11. predictions + appendix
    open_questions: list[str] = Field(default_factory=list)
    replication_notes: list[str] = Field(default_factory=list)
    unavailable_items: list[str] = Field(default_factory=list)

    @property
    def is_positive(self) -> bool:
        return self.verdict in POSITIVE_VERDICTS

    @property
    def is_negative(self) -> bool:
        return self.verdict in NEGATIVE_VERDICTS
