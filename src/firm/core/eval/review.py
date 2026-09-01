"""The sign-off sheet: what a person is being asked to confirm, and what they are not (ADR-0083).

GOLDEN_SET.md §0 says the set "fails by validating itself", and the sign-off is where that either
happens or does not. So this sheet is built to make the right question easy and the wrong one hard.

**What sign-off IS.** A judgment on two things a machine cannot check: that the **label** is a real,
dated, externally-cited event rather than something the firm inferred, and that the **verified facts**
were read correctly off the filing page they cite.

**What sign-off is NOT.** Agreement with the firm's verdict. If a reviewer signs a case because the
screen returned what they expected, the set measures the firm against its own output and every
threshold calibrated on it inherits that circularity. The screen result is therefore shown LAST on each
case and labelled as context, not as the thing being approved.

Generated from the case files rather than written by hand, so it cannot drift from what `firm eval`
actually reads.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from firm.core.eval.golden import GoldenCase


def _event_line(case: GoldenCase) -> list[str]:
    event = dict(case.label_event or {})
    if not event:
        return [("- **Label event:** none recorded — for a `clean` case the label IS the absence of "
                 "one, and that absence is what you are confirming.")]
    out = [f"- **Label event:** `{event.get('kind', '?')}` on **{event.get('date', '?')}**"]
    if event.get("source"):
        out.append(f"  - Source: {event['source']}")
    if event.get("summary"):
        out.append(f"  - {str(event['summary']).strip()}")
    return out


def render_case(case: GoldenCase, screen: str = "", extraction_failures: Sequence[str] = ()) -> str:
    """One case, in the order a reviewer should read it: claim, evidence, then the firm's output."""
    out = [
        f"### {case.case_id} — {case.ticker}, as-of {case.as_of.isoformat()}",
        "",
        f"- **Label:** `{case.label}`"
        + (f" · class `{case.negative_class}`" if case.negative_class else ""),
    ]
    out += _event_line(case)

    if case.verified_facts:
        methods = sorted({f.method for f in case.verified_facts if getattr(f, "method", "")})
        out += ["", f"- **Facts verified by hand: {len(case.verified_facts)}**"
                    + (f" (methods: {', '.join(methods)})" if methods else ""), ""]
        out += ["| metric | period | value | read from |", "|---|---|---|---|"]
        for fact in case.verified_facts:
            out.append(f"| `{fact.metric}` | {fact.period} | {fact.value:,.2f} {fact.unit} "
                       f"| {getattr(fact, 'locator', '') or '—'} |")
    else:
        out += ["", "- **Facts verified by hand: none** — nothing anchors this case to a filing page."]

    if case.expectation.rationale:
        out += ["", f"- **The claim this case makes:** {case.expectation.rationale.strip()}"]
    if case.known_failure:
        out += ["", f"- **Recorded as a known failure:** {case.known_failure.strip()}"]
    if case.notes:
        out += ["", f"- **Recorded coverage gap / note:** {case.notes.strip()}"]

    # LAST, and labelled: a reviewer who signs because the screen agreed with them has made the set
    # circular. The screen is context for the reader, never the thing being approved.
    out += ["", f"- _Context only, not what you are signing — the firm returned: `{screen or 'n/a'}`_"]
    for problem in extraction_failures:
        out.append(f"  - _extraction gap:_ {problem}")
    out += ["", f"- **Sign off:** set `human_signed_off: true` in `evals/golden_set/{case.case_id}.yaml`",
            "", "---", ""]
    return "\n".join(out)


def render_review(cases: Sequence[GoldenCase], results: Sequence[Any] = ()) -> str:
    """The whole sheet. `results` are `CaseResult`s from a run, used only for context lines."""
    by_id = {getattr(r, "case_id", ""): r for r in results}
    signed = [c for c in cases if c.human_signed_off]

    out = [
        "# Golden set — review for sign-off",
        "",
        (f"**{len(cases)} case(s); {len(signed)} signed, {len(cases) - len(signed)} awaiting you.** "
         f"Generated from the case files by `firm eval --review`, so it cannot drift from what the "
         f"harness reads."),
        "",
        "## What you are being asked to confirm",
        "",
        "For each case, two things a machine cannot check:",
        "",
        ("1. **The label is real.** An external, dated, cited event — an auditor resignation, a SEBI "
         "order, an NCLT admission — and not something this firm inferred. For a `clean` case, that "
         "the *absence* of such an event is genuinely true as of the date."),
        ("2. **The verified facts are right.** Each figure was read correctly off the filing page it "
         "cites. These separate an extraction failure from a judgment failure, so a wrong one here "
         "misattributes every error built on top of it."),
        "",
        "## What you are NOT being asked to confirm",
        "",
        ("**Whether the firm's verdict was correct.** If a case is signed because the screen returned "
         "what you expected, the set measures this system against its own output, and every threshold "
         "calibrated on it inherits that circularity — the exact failure GOLDEN_SET.md §0 names "
         "first. The screen result appears last on each case, as context."),
        "",
        "## Before calibrating anything",
        "",
        ("`firm rates` reports six fiscal years with no dated risk-free rate (FY18, FY19, FY21, "
         "FY22, FY23, FY26), so every cash-yield floor currently rests on an undated 6.5% fallback. "
         "Calibrating before those land would fit a parameter to the firm's own dating error "
         "(ADR-0078/0082, GOLDEN_SET.md §1). **Sign-off first, calibration after the rates.**"),
        "",
        "---",
        "",
    ]
    for case in sorted(cases, key=lambda c: c.case_id):
        result = by_id.get(case.case_id)
        out.append(render_case(
            case,
            screen=getattr(result, "screen", "") if result else "",
            extraction_failures=getattr(result, "extraction_failures", ()) if result else (),
        ))
    return "\n".join(out).rstrip() + "\n"
