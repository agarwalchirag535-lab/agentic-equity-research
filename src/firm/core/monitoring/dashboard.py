"""The calibration dashboard's compute half (SPEC §7.5, ADR-0084).

Four panels: the Brier trend per agent version, the over/under-confidence curve, hit rate by claim
type, and attribution — which agent's output actually changed a decision. Everything here is a pure
function over the prediction ledger and the published reports; the renderer projects it to
`memory/calibration.md`, the git-tracked record, so the firm's calibration history is diffable like
everything else it stands behind (Law 6).

THE REFUSAL DISCIPLINE IS THE DESIGN. With three resolved predictions, an over/under-confidence curve
is three dots wearing an axis, and a hit rate "by claim type" is a coin toss per row. Every panel
carries a floor from config and states, when under it, exactly what it is waiting for — the same rule
as `cumulative_cfo_pat_min_periods` and `min_resolved_for_comparison`, because a dashboard that draws
a confident-looking curve from thin data is worse than none: it looks like measurement.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from firm.core.evolution.calibration import VersionScore, brier_by_agent_version
from firm.core.monitoring.predictions import Prediction, read_jsonl


@dataclass(frozen=True)
class CurveBucket:
    """One stated-probability band: what the firm said vs what happened."""

    low: float
    high: float
    stated_mean: float
    realised_rate: float
    resolved: int


@dataclass(frozen=True)
class ClaimTypeRate:
    metric: str
    hits: int
    resolved: int

    @property
    def rate(self) -> float:
        return self.hits / self.resolved if self.resolved else 0.0


@dataclass(frozen=True)
class Dashboard:
    """Everything computed, with each panel's refusal (if any) stated beside it."""

    resolved: int
    unresolved: int
    version_scores: tuple[VersionScore, ...]
    curve: tuple[CurveBucket, ...]
    curve_refusal: str
    claim_rates: tuple[ClaimTypeRate, ...]
    claim_refusals: tuple[str, ...]
    #: attribution lines harvested from published reports, with a count per distinct line
    attribution: Mapping[str, int] = field(default_factory=dict)
    reports_read: int = 0


def _resolved(preds: Sequence[Prediction]) -> list[Prediction]:
    return [p for p in preds if p.resolved and p.outcome is not None]


def confidence_curve(
    preds: Sequence[Prediction], *, min_total: int, min_bucket: int,
) -> tuple[tuple[CurveBucket, ...], str]:
    """Stated probability vs realised frequency, in fixed 20%-wide bands.

    Fixed bands rather than quantiles on purpose: quantile buckets move every time a prediction
    resolves, so two dashboard runs would draw curves that cannot be compared. The record has to be
    diffable to be a record.
    """
    done = _resolved(preds)
    if len(done) < min_total:
        return (), (
            f"not drawn — {len(done)} resolved prediction(s) against a floor of {min_total}. A curve "
            f"from this little data would look like measurement and be noise; resolve more predictions "
            f"(`firm resolve`) and it draws itself.")
    bands = [(i / 5, (i + 1) / 5) for i in range(5)]
    out: list[CurveBucket] = []
    for low, high in bands:
        inside = [p for p in done if low <= p.probability < high or (high == 1.0 and p.probability == 1.0)]
        if len(inside) < min_bucket:
            continue                      # an empty-ish band is omitted, not faked
        out.append(CurveBucket(
            low=low, high=high,
            stated_mean=sum(p.probability for p in inside) / len(inside),
            realised_rate=sum(1 for p in inside if p.outcome) / len(inside),
            resolved=len(inside)))
    return tuple(out), ""


def claim_type_rates(
    preds: Sequence[Prediction], *, min_each: int,
) -> tuple[tuple[ClaimTypeRate, ...], tuple[str, ...]]:
    """Hit rate per metric. A metric under its floor is REPORTED as waiting, never silently dropped."""
    grouped: dict[str, list[Prediction]] = defaultdict(list)
    for p in _resolved(preds):
        grouped[p.metric].append(p)
    rates: list[ClaimTypeRate] = []
    refusals: list[str] = []
    for metric, group in sorted(grouped.items()):
        if len(group) < min_each:
            refusals.append(f"`{metric}`: {len(group)} resolved, floor {min_each} — not yet stated")
            continue
        rates.append(ClaimTypeRate(metric=metric, hits=sum(1 for p in group if p.outcome),
                                   resolved=len(group)))
    return tuple(rates), tuple(refusals)


def harvest_attribution(reports_root: str | Path) -> tuple[Mapping[str, int], int]:
    """Read `decision_attribution` off every published report.json (ADR-0084).

    Reports published before the field existed simply lack it; they are counted as read and contribute
    nothing, which is the honest treatment of a record written before the question was being asked.
    """
    counts: dict[str, int] = defaultdict(int)
    seen = 0
    for path in sorted(Path(reports_root).glob("*/*/report.json")):
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue                      # an unreadable report is the eval's problem, not the tally's
        seen += 1
        for line in data.get("decision_attribution", []):
            counts[str(line)] += 1
    return dict(counts), seen


def build_dashboard(
    ledger_path: str | Path, reports_root: str | Path, *, policy: Mapping[str, Any],
) -> Dashboard:
    preds = read_jsonl(Path(ledger_path))
    done = _resolved(preds)
    curve, curve_refusal = confidence_curve(
        preds, min_total=int(policy["min_resolved_for_curve"]),
        min_bucket=int(policy["min_per_bucket"]))
    rates, claim_refusals = claim_type_rates(preds, min_each=int(policy["min_per_claim_type"]))
    attribution, reports_read = harvest_attribution(reports_root)
    return Dashboard(
        resolved=len(done), unresolved=len(preds) - len(done),
        version_scores=tuple(brier_by_agent_version(preds)),
        curve=curve, curve_refusal=curve_refusal,
        claim_rates=rates, claim_refusals=claim_refusals,
        attribution=attribution, reports_read=reports_read)


def render_dashboard(d: Dashboard) -> str:
    """The git-tracked record. Markdown, so `git diff memory/calibration.md` IS the trend."""
    out = [
        "# Calibration — the firm's own scoreboard",
        "",
        (f"_{d.resolved} resolved prediction(s), {d.unresolved} outstanding; "
         f"{d.reports_read} published report(s) read. Generated by `firm dashboard`; every panel "
         f"refuses below its floor rather than drawing noise (thresholds in `config/thresholds.yaml`, "
         f"`dashboard:`)._"),
        "",
        "## Brier by agent version",
        "",
        ("_Lower is better; 0.25 is a coin flip stated at 50%. The version split is what makes a "
         "prompt revision a checkable claim (ADR-0077)._"),
        "",
    ]
    if d.version_scores:
        out += ["| agent | version | brier | resolved |", "|---|---|---|---|"]
        out += [f"| {s.agent} | `{s.version}` | {s.brier:.4f} | {s.resolved} |"
                for s in d.version_scores]
    else:
        out.append("Nothing resolved yet — `firm resolve` is what feeds this.")
    out += ["", "## Over/under-confidence", ""]
    if d.curve:
        out += ["| stated | realised | n |", "|---|---|---|"]
        out += [f"| {b.stated_mean:.0%} (band {b.low:.0%}–{b.high:.0%}) | {b.realised_rate:.0%} "
                f"| {b.resolved} |" for b in d.curve]
        out += ["", "_Realised above stated = underconfident; below = overconfident._"]
    else:
        out.append(d.curve_refusal)
    out += ["", "## Hit rate by claim type", ""]
    if d.claim_rates:
        out += ["| metric | hit rate | resolved |", "|---|---|---|"]
        out += [f"| `{r.metric}` | {r.rate:.0%} | {r.resolved} |" for r in d.claim_rates]
    if d.claim_refusals:
        out += [""] + [f"- {r}" for r in d.claim_refusals]
    if not d.claim_rates and not d.claim_refusals:
        out.append("Nothing resolved yet.")
    out += ["", "## Attribution — did any agent change a decision?", "",
            ("_Computed by replaying the deterministic verdict ladder with the agent channel toggled "
             "off (ADR-0084) — exact, not estimated. An agent whose output never changes a decision "
             "is dead weight (SPEC §7.5)._"), ""]
    if d.attribution:
        for line, n in sorted(d.attribution.items(), key=lambda kv: -kv[1]):
            out.append(f"- ({n}×) {line}")
    else:
        out.append(f"No published report carries attribution yet — the field exists from ADR-0084 "
                   f"onwards, and {d.reports_read} older report(s) predate it.")
    return "\n".join(out) + "\n"
