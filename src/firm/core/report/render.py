"""Render a validated `ResearchReport` to publishable markdown + auditable JSON (ADR-0016).

Section order is fixed by REPORT_ARCHITECTURE §3 — the order *is* the argument: the verdict and its
load-bearing points come first (so a reader cannot miss what is being claimed), the forensic section
including its **passes** carries the credibility, and thesis/anti-thesis appear together so the opposing
case can never be quietly dropped.

Refuses to render an invalid report by default: publication is gated on the P1/P2/P3 validators, so a
report that would mislead cannot be written to disk by accident.
"""

from __future__ import annotations

import json
from pathlib import Path

from firm.core.validators.publication import validate_report
from firm.schemas.report import AnswerStatus, CheckOutcome, ResearchReport

_OUTCOME_MARK = {
    CheckOutcome.PASS: "✅ pass",
    CheckOutcome.FLAG: "🚩 flag",
    CheckOutcome.NOT_APPLICABLE: "— n/a",
    CheckOutcome.UNAVAILABLE: "⚠️ unavailable",
}

_VERDICT_HEADLINE = {
    "COMPOUNDER": "Passes the compounding test",
    "QUALITY_WRONG_PRICE": "Quality business, wrong price today",
    "WATCH": "Watch — thesis not yet provable",
    "FORENSIC_CAUTION": "Forensic caution — red flags evidenced below",
    "INSUFFICIENT_DISCLOSURE": "Insufficient disclosure — opacity is the finding",
}


class ReportNotPublishable(RuntimeError):
    """Raised when a report fails a publication gate. Carries the violations for the caller to log."""

    def __init__(self, violations) -> None:  # noqa: ANN001 - list[PublicationViolation]
        self.violations = violations
        detail = "; ".join(f"{v.rule}:{v.field}" for v in violations)
        super().__init__(f"report failed {len(violations)} publication gate(s): {detail}")


def _criteria_table(title: str, criteria) -> list[str]:  # noqa: ANN001
    if not criteria:
        return []
    lines = [f"### {title}", "", "| criterion | metric | test | resolve by | load-bearing |",
             "|---|---|---|---|---|"]
    for c in criteria:
        lines.append(
            f"| {c.statement} | `{c.metric}` | `{c.operator} {c.threshold}` | "
            f"{c.resolve_by.isoformat()} | {'**yes**' if c.load_bearing else 'no'} |"
        )
    lines.append("")
    return lines


def render_markdown(report: ResearchReport) -> str:
    """The publishable artifact. Every number in §4 renders with its `[fact:...]` citation token."""
    r = report
    headline = _VERDICT_HEADLINE.get(r.verdict.value, r.verdict.value)
    out: list[str] = []

    # 1. header
    out += [
        f"# {r.company_name} ({r.ticker}) — research note",
        "",
        f"**Outcome: `{r.outcome.value}` · Verdict: `{r.verdict.value}` — {headline}**",
        "",
        f"_As-of {r.as_of.isoformat()} · run `{r.run_id}` · confidence "
        f"{r.confidence.value:.2f} (from {r.confidence.evidence_count} facts, lowest grade "
        f"{r.confidence.lowest_grade_relied_on.value}) · {r.confidence.rationale}_",
        "",
        f"> {r.disclaimer}",
        "",
    ]
    if r.agent_versions:
        versions = ", ".join(f"{k}@{v}" for k, v in sorted(r.agent_versions.items()))
        out += [f"_Agents: {versions}_", ""]

    # 2. executive summary + load-bearing points (grades inline — house style §8)
    if r.executive_summary:
        out += ["## Executive summary", "", r.executive_summary, ""]
    if r.load_bearing_points:
        out += ["### The load-bearing points", ""]
        for claim in r.load_bearing_points:
            out.append(f"- **[{claim.kind}, grade {claim.lowest_grade.value}]** {claim.text}")
        out.append("")

    # 3. business model in plain language
    if r.business_model_plain:
        out += ["## What this business actually does", "", r.business_model_plain, ""]

    # 4. the numbers, each citation-locked
    if r.computed_facts:
        out += ["## The numbers (deterministic — Law 1)", "", "| metric | value | source |", "|---|---|---|"]
        for metric, value in r.computed_facts.items():
            cite = r.fact_citations.get(metric)
            src = (f"`[fact:{cite.fact_id}]` {cite.doc_id} {cite.locator} (grade {cite.grade.value})"
                   if cite else "**UNCITED**")
            out.append(f"| {metric} | {value:,.2f} | {src} |")
        out.append("")

    # 4b. line-by-line (ADR-0022). Placed before the forensic checklist on purpose: a reader should meet
    # the business — where revenue comes from, what the debt bought — before meeting the fraud tests.
    if r.line_items:
        out += [
            "## Line by line — why each number moved",
            "",
            (
                f"_Every question a competent analyst must ask of each statement line. "
                f"**{r.line_item_coverage:.0%}** of the applicable questions could be answered from "
                f"the sources read as-of {r.as_of.isoformat()}; the rest are printed unanswered with "
                f"the exact filing row that would close them, because a question dropped is a question "
                f"that looks answered._"
            ),
            "",
        ]
        for section in r.line_items:
            answered = [a for a in section.answers if a.status is AnswerStatus.ANSWERED]
            unanswered = [a for a in section.answers if a.status is AnswerStatus.UNANSWERED]
            not_applicable = [a for a in section.answers if a.status is AnswerStatus.NOT_APPLICABLE]
            out += [f"### {section.label}", ""]
            if section.why:
                out += [f"_{section.why}_", ""]
            out += [
                (f"**Answered: {len(answered)} of {len(answered) + len(unanswered)}** "
                 f"({section.coverage:.0%})"),
                "",
            ]
            for a in answered:
                cite = f" `[fact:{a.citation.fact_id}]`" if a.citation else ""
                out += [f"- **{a.question}**", f"  → {a.finding}{cite}"]
            for a in unanswered:
                out += [f"- **{a.question}** — ⚠️ **unanswered** ({a.severity})",
                        f"  → {a.reason}"]
                out += [f"     - needs: {need}" for need in a.needs]
            for a in not_applicable:
                out += [f"- ~~{a.question}~~ — n/a: {a.reason}"]
            out.append("")
        if r.disclosure_backlog:
            out += [
                "### What would close the gaps",
                "",
                ("_Deduplicated from every unanswered question above — this is the extraction "
                 "backlog, in the order the questions were asked, not a wish list._"),
                "",
            ]
            out += [f"{i}. {need}" for i, need in enumerate(r.disclosure_backlog, 1)] + [""]

    # 5. forensic — passes included; this is the credibility backbone
    out += ["## Forensic review", ""]
    cl = r.checklist
    if cl.business_models:
        out += [f"_Business model(s) detected: **{', '.join(cl.business_models)}** — checks selected by "
                f"playbook (ADR-0017)._", ""]
    out += [f"**Note coverage: {cl.note_coverage:.0%}**"
            + (f" · undispositioned: {cl.notes_undispositioned}" if cl.notes_undispositioned else ""),
            ""]
    if cl.notes_unenumerated:
        # Coverage is a share of the notes we FOUND. A hole in the filed numbering means a note exists
        # that the parser never saw, and saying 100% without saying this would overstate the reading.
        out += [f"**Notes the parser could not locate: {cl.notes_unenumerated}** — numbered by the "
                f"company and absent from our enumeration, so the coverage figure above is a share of "
                f"the notes we found, not of the notes that exist. This is a gap in our reading, not in "
                f"the company's disclosure.", ""]
    if cl.records:
        out += ["### Verified-clean checklist", "",
                "_Every check that ran, passes included — a clean verdict with an invisible process is "
                "worth nothing._", "",
                "| check | outcome | detail | facts |", "|---|---|---|---|"]
        for rec in cl.records:
            facts = ", ".join(f"`[fact:{f}]`" for f in rec.fact_ids) or "—"
            detail = rec.detail or rec.reason or ""
            out.append(f"| `{rec.name}` | {_OUTCOME_MARK[rec.outcome]} | {detail} | {facts} |")
        out.append("")
    if cl.disclosure_gaps:
        out += [f"**Disclosure gaps** (mandated but not found — a signal, not a blank): "
                f"{', '.join(cl.disclosure_gaps)}", ""]
    if r.forensic_narrative:
        out += [r.forensic_narrative, ""]

    if r.restatements:
        out += ["### Restatement log — what later filings changed", "",
                "_Every figure a later filing revised, from the same deterministic overlap classifier "
                "that quarantines misreads. A restatement is a fact to explain, not an accusation — an "
                "accounting-standard transition legitimately rewrites a year — but a company revising "
                "its history is something a reader sees here in one place, or never._", "",
                "| metric | period | earlier filing said | later filing says | revised by |",
                "|---|---|---|---|---|"]
        for line in r.restatements:
            out += [f"| `{line.metric}` | {line.period} | {line.earlier_value:,.2f} | "
                    f"{line.later_value:,.2f} | `{line.later_doc}` |"]
        out += [""]

    # 4b. sector, macro and unit economics — comparative work, printed before the company-only sections
    if r.sector_narrative:
        out += ["## Sector and competitive position", "", r.sector_narrative, ""]

    # 6-7. management + valuation
    if r.management_narrative:
        out += ["## Management and governance", "", r.management_narrative, ""]
    if r.valuation_narrative:
        out += ["## Valuation", "", r.valuation_narrative, ""]

    # 8. thesis AND anti-thesis — always both
    out += ["## Thesis", "", r.thesis or "_none stated_", "",
            "## Anti-thesis (the strongest case against)", "", r.anti_thesis or "_none stated_", ""]

    # 9. symmetric falsifiability
    out += ["## Falsifiability", ""]
    out += _criteria_table("Kill criteria — what would break this thesis", r.kill_criteria)
    out += _criteria_table("Rehabilitation criteria — what would reverse this verdict",
                           r.rehabilitation_criteria)

    # 10-11. open questions + appendix
    if r.open_questions:
        out += ["## Open questions", ""] + [f"- {q}" for q in r.open_questions] + [""]
    if r.management_questions:
        out += [
            "## Questions for management",
            "",
            ("_Deterministic, from the checks that flagged, the checks the filings could not feed, and "
             "the line-by-line questions the sources did not answer. Every one is the company's to "
             "answer — gaps in the firm's own extraction are listed separately under the disclosure "
             "backlog, not asked of management._"),
            "",
        ]
        for i, q in enumerate(r.management_questions, 1):
            out += [f"{i}. **[{q.severity}]** {q.question}", f"   - _Why it matters:_ {q.why}"]
            if q.answerable_from:
                out += [f"   - _Answerable from:_ {'; '.join(q.answerable_from)}"]
            if q.source:
                out += [f"   - _Raised by:_ `{q.source}`"]
        out += [""]
    if r.unavailable_items:
        out += ["## Not available from primary sources", "",
                "_Reported as unavailable rather than estimated._", ""]
        out += [f"- {item}" for item in r.unavailable_items] + [""]
    if r.replication_notes:
        out += ["## Replication", "", "_How a third party reproduces these findings._", ""]
        out += [f"{i}. {note}" for i, note in enumerate(r.replication_notes, 1)] + [""]

    return "\n".join(out).rstrip() + "\n"


def render_json(report: ResearchReport) -> str:
    """The auditable artifact — the exact object the validators checked."""
    return json.dumps(json.loads(report.model_dump_json()), indent=2, sort_keys=True) + "\n"


def write_report(
    report: ResearchReport, root: str | Path, *, force: bool = False
) -> tuple[Path, Path]:
    """Write `report.md` + `report.json` under ``root/{TICKER}/{run_id}/``.

    Runs the publication gates first and refuses to write an invalid report unless ``force=True``
    (which exists only so a caller can deliberately persist a failing draft for debugging).
    Returns (markdown_path, json_path).
    """
    violations = validate_report(report)
    if violations and not force:
        raise ReportNotPublishable(violations)

    out_dir = Path(root) / report.ticker / report.run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / "report.md"
    json_path = out_dir / "report.json"
    md_path.write_text(render_markdown(report))
    json_path.write_text(render_json(report))
    return md_path, json_path
