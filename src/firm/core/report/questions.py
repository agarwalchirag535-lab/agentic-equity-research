"""Questions to put to management — a standing deliverable of every report (ADR-0066).

The owner's stated use for this system is not only a verdict: it is to be able to walk into a meeting
with the company and ask the right things. That artifact was previously implicit — scattered across
`open_questions`, the disclosure backlog and the unanswered line items — so it existed only in pieces
and only sometimes. This module assembles it deterministically, on every report, whatever the verdict.

Four sources, each of which is already a question in disguise:

* a **check that flagged** — the pattern is observable and the explanation is management's to give;
* a **check the filings could not feed** — for a listed company the datum is public by law, so its
  absence is a question rather than a neutral result (owner directive 2);
* a **line-by-line question the sources were asked and did not answer**, high severity only;
* a **mandated disclosure the notes walker looked for and did not find**.

What is deliberately NOT here: anything blocked on an extractor the firm has not built. That is our
backlog (`disclosure_backlog`), and putting it in front of management would spend the one meeting the
owner gets on our unfinished parser (ADR-0051).
"""

from __future__ import annotations

from firm.core.pipeline.checks import CheckEvaluation
from firm.core.pipeline.interrogate import Interrogation
from firm.core.report.assemble import NotesReview
from firm.schemas.report import CheckOutcome, GapKind, ManagementQuestion

#: High first. A flagged check and an absent legally-mandated disclosure both outrank a routine gap,
#: because both change what the report is allowed to conclude.
_RANK = {"high": 0, "medium": 1, "low": 2}


def management_questions(
    evaluation: CheckEvaluation,
    notes: NotesReview,
    interrogation: Interrogation | None = None,
) -> list[ManagementQuestion]:
    """Build the list. Pure function of computed records — same inputs, same questions, every run."""
    out: list[ManagementQuestion] = []

    for record in evaluation.applicable:
        if record.outcome is CheckOutcome.FLAG:
            out.append(ManagementQuestion(
                question=(
                    f"The check `{record.name}` flagged: {record.detail or record.reason or 'fired'}. "
                    f"What explains it, and which line of the next filing would show that explanation "
                    f"holding?"
                ),
                why=("A flag is the difference between a clean report and a cautioned one; an "
                     "explanation that the next filing can confirm settles it either way."),
                answerable_from=[("management explanation, then the corresponding row of the next "
                                  "annual report")],
                severity="high", source=record.name, fact_ids=list(record.fact_ids),
            ))

    for record in evaluation.applicable:
        if record.outcome is CheckOutcome.UNAVAILABLE and record.gap is GapKind.DISCLOSURE:
            out.append(ManagementQuestion(
                question=(
                    f"The filings we read do not carry the input for `{record.name}` "
                    f"({record.reason or 'input not found'}). Where is it disclosed, and if it is not, "
                    f"why not?"
                ),
                why=("Without the input the check cannot run, so the report must record it as "
                     "UNAVAILABLE — a gap in the evidence, not a pass."),
                severity="high", source=record.name,
            ))

    if interrogation is not None:
        for answer in interrogation.undisclosed_high:
            out.append(ManagementQuestion(
                question=answer.question,
                why=(f"Asked of the filings for the {answer.line_item} line and not answered there; "
                     f"until it is, that line is a number without a cause."),
                answerable_from=list(answer.needs),
                severity=answer.severity, source=answer.line_item,
            ))

    for gap in notes.disclosure_gaps:
        out.append(ManagementQuestion(
            question=f"{gap} — where is this disclosed?",
            why=("A disclosure the notes walker looked for under the applicable schedule and did not "
                 "find. For a listed company the datum is public by law."),
            severity="high", source="notes",
        ))

    # Stable: severity first, insertion order within it, and never two identical questions.
    seen: set[str] = set()
    unique = [q for q in out if not (q.question in seen or seen.add(q.question))]
    return sorted(unique, key=lambda q: _RANK.get(q.severity, 1))
