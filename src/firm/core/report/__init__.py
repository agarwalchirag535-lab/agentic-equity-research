"""Report layer: verdict selection, deterministic criteria, and the publishable markdown/JSON artifacts."""

from firm.core.report.assemble import (
    Narration,
    NotesReview,
    VerdictDecision,
    assemble_report,
    build_checklist,
    choose_verdict,
    load_bearing_points,
    report_confidence,
)
from firm.core.report.criteria import kill_criteria, rehabilitation_criteria, resolve_by
from firm.core.report.render import ReportNotPublishable, render_json, render_markdown, write_report

__all__ = [
    "Narration",
    "NotesReview",
    "ReportNotPublishable",
    "VerdictDecision",
    "assemble_report",
    "build_checklist",
    "choose_verdict",
    "kill_criteria",
    "load_bearing_points",
    "rehabilitation_criteria",
    "render_json",
    "render_markdown",
    "report_confidence",
    "resolve_by",
    "write_report",
]
