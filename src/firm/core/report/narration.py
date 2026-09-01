"""Code-authored narration: the report the firm can still write when no agent's prose may ship.

Law 1 hands the prose to the LLM and the numbers to code. The completeness invariant (ADR-0064 — an
owner-chosen company always gets a report) forces the corollary this module implements: when the prose
layer cannot ship, because an agent broke discipline or a publication gate refused its narrative, the
report must still exist and must still engage both sides of the argument.

Every sentence here is a projection of a record that already carries its own fact ids — the check
evaluation, the forensic screen, the notes review, the line-by-line interrogation. Nothing is
summarised from agent prose and nothing is invented, which is why this narration needs no citation
validator behind it: it cannot cite a fact that does not exist because it never authors one.

The open questions it produces are deliberately split by whose gap they are (ADR-0051): a DISCLOSURE
gap becomes a question addressed to management, a CAPABILITY gap is labelled as the firm's own
backlog. Publishing our unfinished extractor as the company's opacity is a false accusation, and it is
the exact error this split exists to prevent.
"""

from __future__ import annotations

from collections.abc import Sequence

from firm.core.compute.multibagger import FeasibilityResult
from firm.core.compute.quality import ForensicScreenResult
from firm.core.pipeline.checks import CheckEvaluation
from firm.core.pipeline.interrogate import Interrogation
from firm.core.report.assemble import Narration, NotesReview
from firm.schemas.report import CheckOutcome, CheckRecord, GapKind


def _named(records: Sequence[CheckRecord]) -> str:
    return ", ".join(f"`{r.name}`" for r in records)


def _thesis(
    evaluation: CheckEvaluation,
    feasibility: FeasibilityResult | None,
) -> str:
    """The deterministic case FOR the company: what actually survived testing, and nothing more."""
    applicable = evaluation.applicable
    passed = [r for r in applicable if r.outcome is CheckOutcome.PASS]
    if passed:
        head = (
            f"The deterministic case for this company is what survived testing: {len(passed)} of "
            f"{len(applicable)} applicable checks passed — {_named(passed)}. Every one is listed in "
            f"the verified-clean checklist below with the facts it consumed, so each pass can be "
            f"re-derived rather than taken on trust."
        )
    else:
        head = (
            f"No check in the applicable playbook passed on the evidence available "
            f"({len(applicable)} applicable, {evaluation.ran} evaluated), so there is no deterministic "
            f"case for this company to state. That is a statement about what could be tested here, not "
            f"a finding that the business is unsound."
        )
    if feasibility is not None:
        head += (
            f" Against the report's return target the §6.3 feasibility gate returned "
            f"`{feasibility.verdict.value}`: {feasibility.rationale}"
        )
    return head


def _anti_thesis(
    evaluation: CheckEvaluation,
    notes: NotesReview,
    interrogation: Interrogation | None,
) -> str:
    """The deterministic case AGAINST — flags first, then everything that could not be tested."""
    applicable = evaluation.applicable
    flagged = [r for r in applicable if r.outcome is CheckOutcome.FLAG]
    undisclosed = [
        r for r in applicable
        if r.outcome is CheckOutcome.UNAVAILABLE and r.gap is GapKind.DISCLOSURE
    ]
    ours = [
        r for r in applicable
        if r.outcome is CheckOutcome.UNAVAILABLE and r.gap is not GapKind.DISCLOSURE
    ]

    parts: list[str] = []
    if flagged:
        detail = "; ".join(f"`{r.name}` — {r.detail or r.reason or 'flagged'}" for r in flagged)
        parts.append(
            f"{len(flagged)} of {len(applicable)} applicable checks flagged: {detail}. Each flag is a "
            f"pattern that warrants an explanation, and the explanation may well be innocent."
        )
    if undisclosed:
        parts.append(
            f"{len(undisclosed)} check(s) could not run because the filings did not carry the input — "
            f"{_named(undisclosed)}. For a listed company the datum is public by law, so its absence is "
            f"itself a question rather than a neutral result."
        )
    if ours:
        parts.append(
            f"{len(ours)} further check(s) could not run for want of the firm's own reach — "
            f"{_named(ours)}. That limits this report's confidence; it says nothing about the company."
        )
    if notes.coverage < 1.0:
        parts.append(
            f"Only {notes.coverage:.0%} of the notes to the accounts were dispositioned, so the "
            f"line-by-line pass is incomplete."
        )
    if interrogation is not None and interrogation.coverage < 1.0:
        parts.append(
            f"The analyst interrogation answered {interrogation.coverage:.0%} of its questions from the "
            f"sources available."
        )
    # A report that engages no opposing case does not ship (P2), and an empty anti-thesis would be the
    # dishonest kind of clean: the standing limitation is true even when every check passed.
    parts.append(
        "The standing case against any conclusion here: this pass tests what the filings disclose "
        "against a fixed playbook. It does not interview management, visit a site, or price the "
        "shares, and a company can pass every check in it and still be a poor investment."
    )
    return " ".join(parts)


def _forensic(screen: ForensicScreenResult, evaluation: CheckEvaluation) -> str:
    """P3-safe by construction: evidence-indicates language, no accusation, replication stated."""
    flagged = [r for r in evaluation.applicable if r.outcome is CheckOutcome.FLAG]
    text = (
        f"The deterministic forensic screen returned `{screen.verdict.value}` after evaluating "
        f"{evaluation.ran} of {len(evaluation.applicable)} applicable checks. "
    )
    if flagged:
        text += (
            f"The evidence indicates {len(flagged)} pattern(s) that warrant explanation: "
            + "; ".join(f"`{r.name}` — {r.detail or r.reason or 'flagged'}" for r in flagged)
            + ". Each rests on the computed metric named in the checklist, and each may have an "
            "ordinary explanation the filings do not give."
        )
    else:
        text += "No applicable check flagged on the evidence that could be evaluated."
    return text


def _replication(evaluation: CheckEvaluation) -> tuple[str, ...]:
    """How a third party reproduces each flag — P3's requirement, answered mechanically."""
    return tuple(
        f"`{r.name}`: recompute from facts {', '.join(r.fact_ids) or '(none recorded)'} and compare "
        f"against the threshold in `config/thresholds.yaml`. Result on this run: "
        f"{r.detail or r.reason or 'FLAG'}"
        for r in evaluation.applicable if r.outcome is CheckOutcome.FLAG
    )


def _open_questions(
    evaluation: CheckEvaluation,
    notes: NotesReview,
    interrogation: Interrogation | None,
) -> tuple[str, ...]:
    """What the firm does not know — its OWN gaps, plus a pointer to the company's.

    Since ADR-0066 the company-side gaps have their own structured section (`management_questions`),
    built from the same records. Repeating them verbatim here would print the same sentence twice in
    one document, so this field keeps what that section deliberately excludes: the questions blocked on
    an extractor the firm has not built, which are ours to close and no use to ask management about.
    Nothing is truncated — a question dropped for tidiness is a question that never gets asked.
    """
    out: list[str] = []
    for record in evaluation.applicable:
        if record.outcome is CheckOutcome.UNAVAILABLE and record.gap is not GapKind.DISCLOSURE:
            out.append(
                f"Firm backlog (our gap, not the company's): `{record.name}` could not run — "
                f"{record.reason or 'no extractor'}."
            )
    if interrogation is not None:
        for need in interrogation.needs_index():
            out.append(f"Firm backlog (our gap, not the company's): read {need}.")

    company_side = (
        any(r.outcome is CheckOutcome.UNAVAILABLE and r.gap is GapKind.DISCLOSURE
            for r in evaluation.applicable)
        or bool(notes.disclosure_gaps)
        or (interrogation is not None and bool(interrogation.undisclosed_high))
    )
    if company_side:
        out.append(
            "What the filings themselves do not answer is listed, question by question, under "
            "'Questions for management' — those are the company's to close, not ours."
        )
    if not out:
        out.append(
            "Every applicable check ran and every question the playbook asks was answered from the "
            "filings. What remains unknown is what the filings never address: pricing power under "
            "competition, succession, and what management would do with a bad year."
        )
    return tuple(dict.fromkeys(out))


def deterministic_narration(
    *,
    evaluation: CheckEvaluation,
    screen: ForensicScreenResult,
    notes: NotesReview,
    interrogation: Interrogation | None = None,
    feasibility: FeasibilityResult | None = None,
) -> Narration:
    """The narration the firm can publish with no agent at all. Pure function of computed records."""
    return Narration(
        executive_summary=(
            f"Deterministic pass: {evaluation.ran} of {len(evaluation.applicable)} applicable checks "
            f"evaluated, forensic screen `{screen.verdict.value}`, notes dispositioned "
            f"{notes.coverage:.0%}"
            + (f", analyst questions answered {interrogation.coverage:.0%}"
               if interrogation is not None else "")
            + "."
        ),
        forensic_narrative=_forensic(screen, evaluation),
        thesis=_thesis(evaluation, feasibility),
        anti_thesis=_anti_thesis(evaluation, notes, interrogation),
        open_questions=_open_questions(evaluation, notes, interrogation),
        replication_notes=_replication(evaluation),
    )


def merge_narration(primary: Narration, fallback: Narration) -> Narration:
    """Field-wise merge: the agents' prose wins wherever they wrote any, the code fills the rest.

    Used when a publication gate refused the assembled report for something the deterministic layer
    can supply — a missing anti-thesis, absent replication notes — so the analysts' work survives a
    gate failure instead of being thrown away with it.
    """
    merged: dict[str, object] = {}
    for field in Narration.__dataclass_fields__:
        chosen = getattr(primary, field)
        if not chosen:
            chosen = getattr(fallback, field)
        merged[field] = chosen
    return Narration(**merged)  # type: ignore[arg-type]
