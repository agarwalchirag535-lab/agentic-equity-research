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

from pydantic import BaseModel, Field, computed_field

from firm.schemas._base import Citation, Confidence, Grade


class Verdict(str, Enum):
    """Exactly one per report (REPORT_ARCHITECTURE §2). Never 'buy'/'sell' (SPEC §1)."""

    COMPOUNDER = "COMPOUNDER"                          # passed forensics + feasibility + valuation
    #: Forensically clean and adequately disclosed, but the §6.3 gate says it cannot fund the growth
    #: THIS RUN'S TARGET demands. Named for the test it actually performs: it fires on the feasibility
    #: gate, never on a price comparison, and was called QUALITY_WRONG_PRICE from Phase 2 until ADR-0081.
    #: Reads as MIXED at the headline — quality established, hurdle not cleared (ADR-0067).
    RETURN_HURDLE_NOT_CLEARED = "RETURN_HURDLE_NOT_CLEARED"
    WATCH = "WATCH"                                    # promise, thesis not yet provable
    FORENSIC_CAUTION = "FORENSIC_CAUTION"              # red flags with a corroborated evidence chain
    INSUFFICIENT_DISCLOSURE = "INSUFFICIENT_DISCLOSURE"  # THEY did not disclose what the law requires
    #: WE could not look hard enough to judge — too little of the playbook ran, for want of the firm's
    #: own reach rather than the company's silence (ADR-0051). Splitting this out of
    #: INSUFFICIENT_DISCLOSURE matters in both directions: publishing our gap as their opacity is a false
    #: accusation, and publishing a business judgment off a fifth of the playbook is a false thesis.
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class Outcome(str, Enum):
    """The headline conclusion, in the four values the owner reads first (ADR-0067).

    `Verdict` says precisely what the firm concluded and stays the operative value: it drives the
    criteria symmetry, the publication gates and the golden set. `Outcome` is the summary axis above
    it, and it exists because the verdict ladder alone answered a narrower question than the mandate
    now asks (ADR-0063). A forensically clean, fully-disclosed, fairly-priced business that simply
    cannot compound 5x in seven years is not a *failure*; reading `RETURN_HURDLE_NOT_CLEARED` as a flat
    negative was the last place the 5-10x question was still masquerading as the whole point.

    MIXED is therefore a first-class result, not an error state: quality established, return hurdle
    not cleared — or promise visible, thesis not yet provable. None of the four is a preferred answer.
    """

    PASS = "PASS"                                    # clears the bar the run was asked to test
    MIXED = "MIXED"                                  # some pillars hold, others do not
    FAIL = "FAIL"                                    # a corroborated finding against the company
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"  # no honest conclusion is available either way


#: Exactly one outcome per verdict. Exhaustive by test: a new verdict cannot be added without deciding
#: what it means at the headline, which is the decision most likely to be skipped in a hurry.
OUTCOME_BY_VERDICT: dict[Verdict, Outcome] = {
    Verdict.COMPOUNDER: Outcome.PASS,
    # Clean business, feasibility or price fails at the target — quality established, hurdle not cleared.
    Verdict.RETURN_HURDLE_NOT_CLEARED: Outcome.MIXED,
    # Promise visible, thesis not yet provable from what exists.
    Verdict.WATCH: Outcome.MIXED,
    Verdict.FORENSIC_CAUTION: Outcome.FAIL,
    # Both say "no conclusion is available", and they differ in WHOSE gap caused that — a distinction
    # the verdict keeps and the headline deliberately does not, because the reader's next action is the
    # same either way: read the gap, then decide whether to ask the company or wait for the firm.
    Verdict.INSUFFICIENT_DISCLOSURE: Outcome.INSUFFICIENT_EVIDENCE,
    Verdict.INSUFFICIENT_EVIDENCE: Outcome.INSUFFICIENT_EVIDENCE,
}


#: Verdicts that assert a company is investable-quality — these must carry kill criteria.
POSITIVE_VERDICTS = frozenset({Verdict.COMPOUNDER})
#: Verdicts that withhold or warn — these must carry rehabilitation criteria (what would reverse them).
NEGATIVE_VERDICTS = frozenset({
    Verdict.RETURN_HURDLE_NOT_CLEARED, Verdict.WATCH, Verdict.FORENSIC_CAUTION,
    Verdict.INSUFFICIENT_DISCLOSURE, Verdict.INSUFFICIENT_EVIDENCE,
})


class CheckOutcome(str, Enum):
    PASS = "PASS"
    FLAG = "FLAG"
    NOT_APPLICABLE = "NOT_APPLICABLE"   # suppressed by the model playbook (ADR-0017)
    UNAVAILABLE = "UNAVAILABLE"         # inputs not disclosed — a signal, never a silent skip


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
    #: WHOSE gap an UNAVAILABLE is (ADR-0051). The verdict may only be degraded by a DISCLOSURE gap —
    #: the pipeline looked in the right place and the company had not put the figure there. A CAPABILITY
    #: gap is about us and lowers confidence instead. Applied to line-item questions since ADR-0022 and
    #: to CHECKS only since ADR-0051, which is why CreditAccess Grameen — a lender that discloses its
    #: asset quality in full — was headed for publication as INSUFFICIENT_DISCLOSURE over notes the firm
    #: does not read. Defaults to CAPABILITY: the safe direction is to blame ourselves.
    gap: GapKind = GapKind.NONE


class VerifiedCleanChecklist(BaseModel):
    """The credibility backbone of a published report: every check in the applicable playbook, with
    passes shown. `expected` comes from the resolved playbook so omissions are detectable."""

    business_models: list[str] = Field(default_factory=list)
    expected_checks: list[str] = Field(default_factory=list)
    records: list[CheckRecord] = Field(default_factory=list)
    note_coverage: float = Field(default=0.0, ge=0.0, le=1.0)
    notes_undispositioned: list[str] = Field(default_factory=list)
    #: Note numbers absent from the filed sequence — notes that exist and the parser could not see.
    #: Printed beside coverage because 100% coverage of the notes we FOUND is not 100% of the notes.
    notes_unenumerated: list[int] = Field(default_factory=list)
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


class ReturnPotential(BaseModel):
    """The §6 return-potential finding, as a report section rather than a hidden gate (ADR-0068).

    The feasibility gate is what SPEC §6 calls the intellectual centre of the system, and until now it
    reached the reader only obliquely — through a verdict rationale and a rehabilitation criterion. So a
    report could be judged against "5x over 7 years" without ever printing that target, which made the
    single most consequential assumption in the analysis the one thing a reader could not check.

    It is a *section* and not the spine (ADR-0063): a business that cannot self-fund the target growth
    is reported as exactly that, not reclassified as a failure. `required_earnings_cagr` is computable
    from the target alone, so the section says something useful even when ROIC is not derivable — in
    which case `unavailable_reason` names what is missing rather than the gate quietly not appearing.
    """

    target_multiple: float
    target_years: int
    #: Earnings CAGR the target demands with no re-rating and no dilution — the §6.2 identity.
    required_earnings_cagr: float
    roic: float | None = None
    #: g_required / ROIC. Above 1.0 the company cannot fund that growth from its own returns.
    required_reinvestment: float | None = None
    gate_verdict: str = ""
    rationale: str = ""
    #: Set when the gate could not run at all. Missing is reported as missing, never as a zero.
    unavailable_reason: str = ""


class GateLine(BaseModel):
    """One SPEC §8 funnel gate, applied to this company and REPORTED rather than enforced (ADR-0071).

    In a deep dive these decide nothing: research eligibility and investment verdict are separate
    (ADR-0064), so a company the owner named is never dropped for failing an investment gate. The same
    findings drive the sweep, where they do decide who is looked at — a different question, asked by a
    different caller.

    `status` is PASS / FAIL / UNAVAILABLE, and the third is not the first: a gate whose inputs were
    missing has not been passed, and saying so is the same discipline the check records follow.
    """

    gate: str
    status: str
    reason: str


class ValuationScenario(BaseModel):
    """One priced scenario. Deterministic — the agent's `ScenarioLine` is a separate, narrated thing."""

    name: str
    growth: float
    value_per_share: float
    #: Intrinsic value under this scenario divided by the price actually quoted. NOT a target price and
    #: NOT a re-rating: no multiple expansion is assumed anywhere in this number.
    return_multiple: float


class ValuationSection(BaseModel):
    """What the price already assumes, and what the business would have to do to justify it (ADR-0069).

    Reverse DCF first, deliberately (SPEC §5): a forward DCF's answer is hostage to the discount rate
    and to which year is called "base", so it partly restates its own assumptions. Inverting it — hold
    the price, solve for the growth it demands — produces a sentence a reader can check against a base
    rate, which is what the house standard asks for.

    `status == 'unavailable'` is a real result with its inputs NAMED, never an empty section: a
    valuation that quietly substitutes a zero for a missing net debt is worse than none, because it
    looks like one.
    """

    status: str = "unavailable"
    missing: list[str] = Field(default_factory=list)
    price: float | None = None
    price_on: date | None = None
    shares_cr: float | None = None
    market_cap_cr: float | None = None
    net_debt_cr: float | None = None
    enterprise_value_cr: float | None = None
    base_fcf_cr: float | None = None
    #: How that base was arrived at — a median over a window, or one year with that fact stated. A
    #: reader who cannot tell which is which cannot judge the bear case (ADR-0072).
    base_fcf_basis: str = ""
    #: What the business has actually compounded — the grid is centred here, never on a house guess.
    realised_growth: float | None = None
    #: The growth the quoted price already demands. None when it falls outside the configured bracket,
    #: which is a finding about the price and is reported in `implied_growth_note`.
    implied_growth: float | None = None
    implied_growth_note: str = ""
    scenarios: list[ValuationScenario] = Field(default_factory=list)
    #: The policy block this valuation used. A discount rate is a return this firm DEMANDS, not a
    #: measurement, so it is printed in every report that rests on it rather than buried in config.
    assumptions: dict[str, float] = Field(default_factory=dict)


class ManagementQuestion(BaseModel):
    """One specific question to put to the company, with the reason it matters and what would settle it.

    Distinct from `open_questions`, which is the analysts' own statement of what they do not know
    (house style §3). This list is deterministic, built from the checks that flagged, the checks the
    filings could not feed, and the line-by-line questions the sources were asked and did not answer —
    so it is the same list whoever runs the report, and every entry names its origin.

    Only the COMPANY's gaps belong here (ADR-0051). A question blocked on an extractor the firm has not
    built is the firm's backlog and appears in `disclosure_backlog`; asking management to answer for our
    unfinished parser wastes the one meeting the owner gets.
    """

    question: str
    #: What conclusion the answer unblocks — a question with no consequence does not earn a slot.
    why: str
    #: Where the answer would come from: a filing row, a note, a disclosure the law already mandates.
    answerable_from: list[str] = Field(default_factory=list)
    severity: str = "medium"
    #: The check name or line item that generated it, so a reader can trace the question to its origin.
    source: str = ""
    fact_ids: list[str] = Field(default_factory=list)


class ReportClaim(BaseModel):
    """A claim in the report body, carrying its grade inline (house style §8: grade in the body, not a
    footnote)."""

    text: str
    kind: str = Field(description="observation | inference | speculation")
    lowest_grade: Grade
    citations: list[Citation] = Field(default_factory=list)


class RestatementLine(BaseModel):
    """A figure a later filing revised (quiet-change material, FORENSIC_METHODOLOGY P5). A restatement
    is a fact to explain, not an accusation — the Ind AS transition legitimately rewrites a whole year —
    but the reader sees every revision in one place instead of never."""

    metric: str
    period: str
    earlier_doc: str
    earlier_value: float
    later_doc: str
    later_value: float


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
    #: Every figure a later visible filing revised (point-in-time: revisions published after `as_of`
    #: do not exist yet). Deterministic, from the same overlap classifier that quarantines misreads.
    restatements: list[RestatementLine] = Field(default_factory=list)

    # 4b. sector and business context — the agents whose work is comparative rather than company-only.
    # Added because `sector_analyst`, `macro_strategist` and `unit_economics_analyst` were validating,
    # entering `agent_versions` and then having their narratives dropped: the report named them as
    # contributors and printed nothing they wrote. An agent that runs and is not rendered is the
    # ADR-0034 failure in the other direction — the reader cannot tell it from one that never ran.
    sector_narrative: str = ""

    #: SPEC §8's funnel, applied to this company. Findings, never filters (ADR-0064/0071).
    gates: list[GateLine] = Field(default_factory=list)

    #: Which agent input, if any, changed the deterministic verdict — computed by replaying the ladder
    #: with the channel toggled off (ADR-0084). Code-authored; the dashboard aggregates it, because an
    #: agent whose output never changes a decision is dead weight (SPEC §7.5).
    decision_attribution: list[str] = Field(default_factory=list)

    #: What the quoted price already assumes (ADR-0069). None when the run had no valuation policy to
    #: apply; an `unavailable` status inside it means the policy ran and named what it lacked.
    valuation: ValuationSection | None = None

    #: The §6 return-potential finding — target, required growth, and whether the company can fund it
    #: from its own returns. A section, not the verdict's spine (ADR-0063/0068).
    return_potential: ReturnPotential | None = None

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
    #: The deterministic list to take to a management meeting (ADR-0066). Present on EVERY report,
    #: whatever the verdict: a report the owner cannot act on is half a report.
    management_questions: list[ManagementQuestion] = Field(default_factory=list)
    replication_notes: list[str] = Field(default_factory=list)
    unavailable_items: list[str] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def outcome(self) -> Outcome:
        """The headline, derived from the verdict so the two can never disagree (ADR-0067)."""
        return OUTCOME_BY_VERDICT[self.verdict]

    @property
    def is_positive(self) -> bool:
        return self.verdict in POSITIVE_VERDICTS

    @property
    def is_negative(self) -> bool:
        return self.verdict in NEGATIVE_VERDICTS
