"""Report rendering: the validated `ResearchReport` → publishable markdown + auditable JSON."""

from firm.core.report.render import render_json, render_markdown, write_report

__all__ = ["render_json", "render_markdown", "write_report"]
