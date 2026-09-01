"""Persistent per-company memory: what this firm already knew (SPEC §7.4, ADR-0079).

`memory/company_notes/{ticker}.md` is an append-only record of every run the firm published on one
company — the verdict it reached, the checks that flagged, the criteria it staked itself on, and the
questions it left for management. On a re-run it is loaded first, so the system does not re-derive a
conclusion it already reached and, more usefully, can be confronted with the fact that it once said
something different.

THE POINT-IN-TIME RULE IS THE WHOLE DESIGN. A note written from a 2026 run must be INVISIBLE to a
replay at 2019, and this is not a nicety: the golden set replays historical dates, and a memory file
that leaked the firm's later conclusions backwards would hand every replay the answer. The eval would
then measure the firm's ability to read its own notes and report it as foresight. So every entry
carries the `as_of` it was written from, and `read_notes` takes an `as_of` and returns only entries at
or before it — the same filter the fact store applies to documents, for the same reason.

WHAT A NOTE IS NOT. It is the firm's own prior output, never evidence. Agents receive it labelled as
such and cannot cite it: a note carries no fact id, so the citation validator rejects any claim that
leans on one. Prior conclusions inform the questions asked; they never support a finding.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from firm.schemas.report import CheckOutcome, ResearchReport

_ENTRY = "## run "
_AS_OF = "as-of "


@dataclass(frozen=True)
class NoteEntry:
    """One published run, as the notes file records it."""

    as_of: date
    run_id: str
    text: str


def notes_path(ticker: str, root: str | Path) -> Path:
    return Path(root) / "company_notes" / f"{ticker}.md"


def render_entry(report: ResearchReport) -> str:
    """One run's entry. Deterministic — composed from the published report, never narrated."""
    flagged = [r.name for r in report.checklist.records if r.outcome is CheckOutcome.FLAG]
    unavailable = [r.name for r in report.checklist.records
                   if r.outcome is CheckOutcome.UNAVAILABLE]
    lines = [
        f"{_ENTRY}{report.run_id} ({_AS_OF}{report.as_of.isoformat()})",
        "",
        (f"- **Outcome** `{report.outcome.value}` · **verdict** `{report.verdict.value}` · "
         f"confidence {report.confidence.value:.2f}"),
        f"- **Flagged:** {', '.join(f'`{n}`' for n in flagged) if flagged else 'nothing'}",
        f"- **Could not evaluate:** {len(unavailable)} check(s)"
        + (f" — {', '.join(f'`{n}`' for n in unavailable[:6])}" if unavailable else ""),
    ]
    if report.kill_criteria:
        lines.append("- **Staked on** (kill criteria, resolvable from a later filing):")
        lines += [f"    - {c.statement}" for c in report.kill_criteria]
    if report.management_questions:
        lines.append(f"- **Asked of management:** {len(report.management_questions)} question(s)")
        lines += [f"    - {q.question}" for q in report.management_questions[:5]]
    if report.return_potential is not None:
        rp = report.return_potential
        lines.append(
            f"- **Return potential:** judged at {rp.target_multiple:g}x/{rp.target_years}y "
            + (rp.unavailable_reason or f"gate `{rp.gate_verdict}`"))
    return "\n".join(lines) + "\n"


def append_run(report: ResearchReport, root: str | Path) -> Path:
    """Append this run to the company's notes, creating the file on first sight. Idempotent by run_id.

    Idempotence matters because a re-run with identical inputs produces an identical `run_id` (Law 5),
    and a memory that duplicates itself on every replay stops being readable and starts being noise.
    """
    path = notes_path(report.ticker, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text() if path.exists() else ""
    if f"{_ENTRY}{report.run_id} " in existing:
        return path
    header = "" if existing else (
        f"# {report.company_name} ({report.ticker}) — what this firm has concluded before\n\n"
        "_Append-only. The firm's own prior output, not evidence: nothing here carries a fact id, and "
        "no claim in a report may rest on it. Entries are filtered by `as_of` on read, so a replay of "
        "an earlier date cannot see what later runs concluded._\n\n")
    path.write_text(f"{existing}{header}{render_entry(report)}\n")
    return path


def read_notes(ticker: str, root: str | Path, as_of: date) -> list[NoteEntry]:
    """Entries written at or before `as_of`, oldest first. Law 3, applied to the firm's own memory."""
    path = notes_path(ticker, root)
    if not path.exists():
        return []
    out: list[NoteEntry] = []
    for block in path.read_text().split(_ENTRY)[1:]:
        head, _, body = block.partition("\n")
        run_id, _, rest = head.partition(f" ({_AS_OF}")
        stamp = rest.rstrip(")").strip()
        try:
            written = date.fromisoformat(stamp)
        except ValueError:                      # an entry we cannot date cannot be filtered safely,
            continue                            # and an undateable memory is the leak this guards
        if written <= as_of:
            out.append(NoteEntry(as_of=written, run_id=run_id.strip(), text=body.strip()))
    return sorted(out, key=lambda e: (e.as_of, e.run_id))
