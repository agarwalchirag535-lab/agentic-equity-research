"""Publication gates for the dual-verdict report (ADR-0016, REPORT_ARCHITECTURE §4). Blocking.

Three invariants the report architecture makes structural. All deterministic (Law 1) — no LLM decides
whether a report may ship:

  P1 verified-clean completeness — every check the playbook expected must appear in the checklist, and
     NOT_APPLICABLE/UNAVAILABLE must carry a reason. A check that silently vanished is indistinguishable
     from one that never ran, so a clean verdict would be unfalsifiable.
  P2 symmetry — positive verdicts carry dated kill criteria; negative verdicts carry rehabilitation
     criteria; both carry the opposing case. Optimism gets no easier standard than pessimism.
  P3 legal framing — a forensic finding renders as evidence-indicates language with a replication path,
     never as an unhedged accusation of fraud, and never resting only on grade C/D.

Empty result = the report may publish.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from firm.schemas._base import Grade
from firm.schemas.report import (
    CheckOutcome,
    ResearchReport,
    Verdict,
)

# Unhedged accusation language: stating fraud as established fact rather than as what evidence indicates.
_ACCUSATION = re.compile(
    r"\b(?:is|are|was|were|has|have)\s+(?:a\s+)?(?:fraud|fraudulent|fake|forged|criminal)\b"
    r"|\b(?:committed|perpetrated)\s+(?:fraud|forgery)\b"
    r"|\bis\s+(?:a\s+)?(?:fraudster|criminal|liar)\b",
    re.IGNORECASE,
)
# Hedges that correctly frame an inference as an inference.
_HEDGES = (
    "appears", "appear", "suspected", "we believe", "indicates", "indicate", "suggests", "suggest",
    "consistent with", "raises the question", "evidence indicates", "may ", "might ", "could ",
    "should clarify", "warrants",
)
_MIN_KILL_CRITERIA = 3
_MIN_REHAB_CRITERIA = 1


@dataclass(frozen=True)
class PublicationViolation:
    rule: str      # 'P1_incomplete_checklist' | 'P2_asymmetric' | 'P3_legal_framing'
    field: str
    detail: str


def verified_clean_completeness(report: ResearchReport) -> list[PublicationViolation]:
    """P1: the checklist must account for every expected check, and justify every non-result."""
    out: list[PublicationViolation] = []
    cl = report.checklist
    recorded = {r.name for r in cl.records}

    for expected in cl.expected_checks:
        if expected not in recorded:
            out.append(PublicationViolation(
                "P1_incomplete_checklist", "checklist.records",
                f"playbook expected check '{expected}' but the report does not report it",
            ))

    for record in cl.records:
        if record.outcome in (CheckOutcome.NOT_APPLICABLE, CheckOutcome.UNAVAILABLE) \
                and not record.reason.strip():
            out.append(PublicationViolation(
                "P1_incomplete_checklist", f"checklist.records[{record.name}]",
                f"outcome {record.outcome.value} requires a reason (a silent skip is not acceptable)",
            ))

    # Line-by-line discipline (ADR-0017): a report cannot publish below full note coverage.
    if cl.note_coverage < 1.0:
        out.append(PublicationViolation(
            "P1_incomplete_checklist", "checklist.note_coverage",
            f"note coverage {cl.note_coverage:.0%} < 100%; undispositioned notes: "
            f"{cl.notes_undispositioned or 'unlisted'}",
        ))
    return out


def symmetry(report: ResearchReport) -> list[PublicationViolation]:
    """P2: falsifiability and the opposing case are required in BOTH directions."""
    out: list[PublicationViolation] = []

    if report.is_positive:
        if len(report.kill_criteria) < _MIN_KILL_CRITERIA:
            out.append(PublicationViolation(
                "P2_asymmetric", "kill_criteria",
                f"a positive verdict needs >= {_MIN_KILL_CRITERIA} dated kill criteria, "
                f"got {len(report.kill_criteria)}",
            ))
        if not any(c.load_bearing for c in report.kill_criteria):
            out.append(PublicationViolation(
                "P2_asymmetric", "kill_criteria",
                "at least one kill criterion must be load_bearing",
            ))
    if report.is_negative and len(report.rehabilitation_criteria) < _MIN_REHAB_CRITERIA:
        out.append(PublicationViolation(
            "P2_asymmetric", "rehabilitation_criteria",
            "a negative/withholding verdict must state what would reverse it "
            f"(>= {_MIN_REHAB_CRITERIA} rehabilitation criteria)",
        ))

    # Both directions must engage the other side of the argument.
    if not report.thesis.strip():
        out.append(PublicationViolation("P2_asymmetric", "thesis", "thesis is empty"))
    if not report.anti_thesis.strip():
        out.append(PublicationViolation(
            "P2_asymmetric", "anti_thesis",
            "the opposing case is mandatory — a report that hides it does not ship",
        ))

    # An empty open_questions array is treated as a quality failure (house style §3).
    if not report.open_questions:
        out.append(PublicationViolation(
            "P2_asymmetric", "open_questions",
            "empty open_questions is suspicious — state what you do not know",
        ))
    return out


def legal_framing(report: ResearchReport) -> list[PublicationViolation]:
    """P3: forensic conclusions are hedged, replicable, and never rest on grade C/D alone."""
    out: list[PublicationViolation] = []
    text = report.forensic_narrative

    for match in _ACCUSATION.finditer(text):
        window = text[max(0, match.start() - 160):match.end() + 160].lower()
        if not any(h in window for h in _HEDGES):
            out.append(PublicationViolation(
                "P3_legal_framing", "forensic_narrative",
                f"unhedged accusation {match.group(0)!r} — state what the evidence indicates, "
                "not fraud as established fact",
            ))

    if report.verdict is Verdict.FORENSIC_CAUTION:
        if not report.replication_notes:
            out.append(PublicationViolation(
                "P3_legal_framing", "replication_notes",
                "a forensic caution must say how a third party reproduces each finding",
            ))
        flagged = [r for r in report.checklist.records if r.outcome is CheckOutcome.FLAG]
        if not flagged:
            out.append(PublicationViolation(
                "P3_legal_framing", "checklist.records",
                "FORENSIC_CAUTION with no FLAG check — the verdict is not evidenced",
            ))
        weak = [
            c.text for c in report.load_bearing_points
            if c.lowest_grade in (Grade.C, Grade.D)
        ]
        if weak and len(weak) == len(report.load_bearing_points):
            out.append(PublicationViolation(
                "P3_legal_framing", "load_bearing_points",
                "every load-bearing point rests on grade C/D evidence — a pillar may not rest on "
                "company claims or media alone",
            ))
    return out


def validate_report(report: ResearchReport) -> list[PublicationViolation]:
    """Run every publication gate. Empty list = the report may ship."""
    return [
        *verified_clean_completeness(report),
        *symmetry(report),
        *legal_framing(report),
    ]
