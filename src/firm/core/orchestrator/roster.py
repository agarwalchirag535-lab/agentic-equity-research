"""Who runs, in what order, and what happens when their inputs do not exist (Phase 3, ADR-0030).

WHAT THIS REPLACES
`PHASE2_AGENTS` was a tuple in `deep_dive.py`. That was right for three agents and wrong for fourteen:
sequencing is policy, and policy in Python is the least reviewable place for it. The roster now lives in
`config/roster.yaml` with each agent's stage, its gate, the build phase that introduces it, and its data
prerequisites.

THE DECISION THAT MATTERS: A SKIPPED AGENT IS A PUBLISHED FACT
Six of the eleven agents this phase adds need data the firm does not ingest — concall transcripts,
shareholding patterns, promoter pledge, a peer set. The tempting design is to run whoever can run and let
the rest fall away. That produces a report with no governance section and no visible reason for it, which
is the false-clean failure again (ADR-0027): a reader cannot tell "management looked fine" from "nobody
looked at management".

So `plan_run` returns skips as first-class results carrying the missing inputs by name, and the caller is
expected to surface them. An agent that could not run is a disclosure gap in the firm's own coverage, and it
is reported the same way a company's disclosure gap is.

BUILD ORDER IS ENFORCED HERE, NOT REMEMBERED
`CLAUDE.md` forbids skipping phases. `plan_run(..., max_phase=N)` refuses every agent above phase N, so a
Phase-3 run cannot quietly recruit the Phase-4 judgment tier because someone passed the wrong list.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

import yaml

from firm.core.orchestrator.stages import Gate, Stage


@dataclass(frozen=True)
class RosterEntry:
    """One agent's placement in the pipeline."""

    name: str
    stage: Stage
    gate: Gate
    phase: int
    requires: tuple[str, ...]

    def missing(self, available: Sequence[str]) -> tuple[str, ...]:
        """Prerequisites this agent needs that the run does not have."""
        have = set(available)
        return tuple(r for r in self.requires if r not in have)


@dataclass(frozen=True)
class Skip:
    """An agent that did not run, and why — destined for the report, not for a log line."""

    agent: str
    reason: str
    missing_inputs: tuple[str, ...] = ()


@dataclass(frozen=True)
class RunPlan:
    """The agents to run, in order, plus every agent that was left out and the reason."""

    to_run: tuple[RosterEntry, ...]
    skipped: tuple[Skip, ...]

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(e.name for e in self.to_run)

    @property
    def coverage(self) -> float:
        """Share of in-phase agents that could actually run. 1.0 means the roster was fully staffed."""
        total = len(self.to_run) + len([s for s in self.skipped if s.missing_inputs])
        return (len(self.to_run) / total) if total else 1.0

    def disclosure_gaps(self) -> tuple[str, ...]:
        """The firm's OWN coverage gaps, phrased for a reader of the report.

        Deliberately worded to make the distinction ADR-0019 insists on: this is the firm failing to look,
        not the company failing to disclose, and a verdict must never be moved against a company for it.
        """
        return tuple(
            f"{s.agent} did not run — the firm has not ingested: {', '.join(s.missing_inputs)}. "
            f"This is a gap in our coverage, not in the company's disclosure."
            for s in self.skipped if s.missing_inputs
        )


def load_roster(path: str | Path | None = None) -> tuple[RosterEntry, ...]:
    """Read `config/roster.yaml`, ordered by pipeline stage then by listed order within a stage."""
    location = Path(path) if path else Path(__file__).resolve().parents[4] / "config" / "roster.yaml"
    raw = yaml.safe_load(location.read_text())
    entries = [
        RosterEntry(
            name=str(a["name"]), stage=Stage[str(a["stage"])], gate=Gate[str(a["gate"])],
            phase=int(a["phase"]), requires=tuple(a.get("requires") or ()),
        )
        for a in raw["agents"]
    ]
    # Stable sort: stage order is the pipeline order; within a stage the file's order is intentional.
    return tuple(sorted(entries, key=lambda e: e.stage.value))


#: Document class in the documents manifest -> the roster prerequisites it satisfies. A shareholding
#: pattern satisfies BOTH `shareholding` and `pledge`, because the SEBI format carries pledge as a column
#: ("Whether any shares held by promoters are pledge or otherwise encumbered?") rather than as a separate
#: filing. Concall transcripts satisfy `guidance` too: management's forward statements are what a
#: promise-vs-delivery scorecard is built from.
SATISFIES: Mapping[str, tuple[str, ...]] = {
    "annual_report": ("financials", "filing", "segments"),
    "shareholding": ("shareholding", "pledge"),
    "transcript": ("transcripts", "guidance"),
    "quarterly_result": ("financials",),
    "credit_rating": ("credit_rating",),
    "voting_result": ("voting",),
}


def available_inputs_from(manifest: Mapping[str, object]) -> tuple[str, ...]:
    """Roster prerequisites satisfied by a documents manifest — derived, never asserted by hand.

    The alternative was a caller passing a literal list, and that is exactly how four agents came to be
    described as "blocked on data that does not exist" when 28 shareholding patterns and 15 concall
    transcripts were sitting on the company's own website. Deriving availability from what is actually on
    disk means the roster cannot claim more coverage than the ingest supports, and cannot claim less.
    """
    classes = {str(d.get("doc_class")) for d in manifest.get("documents", [])}  # type: ignore[union-attr]
    satisfied: set[str] = set()
    for name in classes:
        satisfied.update(SATISFIES.get(name, ()))
    return tuple(sorted(satisfied))


def plan_run(
    roster: Sequence[RosterEntry],
    *,
    available_inputs: Sequence[str],
    gates_passed: Mapping[Gate, bool] | None = None,
    max_phase: int = 3,
) -> RunPlan:
    """Decide which agents run for this company, and record why each of the others did not.

    Three reasons an agent is skipped, kept distinct because they mean different things to a reader:

    * **out of phase** — the build has not reached it. Not a data problem, and excluded from `coverage`
      so an early-phase run does not look under-staffed for following its own build order.
    * **gate not passed** — the company failed an upstream gate, so spending tokens here is waste. This is
      the funnel doing its job (SPEC §8) and is also excluded from coverage.
    * **missing inputs** — the agent could have run and we could not feed it. THIS is a coverage gap and
      the only kind that reaches `disclosure_gaps`.
    """
    gates = dict(gates_passed or {})
    # GATES ARE ORDERED (A→E) AND A FAILURE STOPS EVERYTHING BELOW IT. Checking only `gates[entry.gate]`
    # was wrong: with Gate B failed and Gate C simply unevaluated, the Gate-C management agents fell
    # through to the input check and were reported as COVERAGE gaps — the firm blaming itself for not
    # looking at a company the funnel had already rejected. A run that never reaches Gate C cannot have a
    # coverage gap at Gate C.
    failed = sorted((g for g, ok in gates.items() if ok is False), key=lambda g: g.value)
    first_failed = failed[0] if failed else None

    to_run: list[RosterEntry] = []
    skipped: list[Skip] = []

    for entry in roster:
        if entry.phase > max_phase:
            skipped.append(Skip(entry.name, f"introduced in phase {entry.phase}; this run is phase "
                                            f"{max_phase} (CLAUDE.md forbids skipping phases)"))
            continue
        if first_failed is not None and entry.gate.value >= first_failed.value:
            reached = "did not pass" if entry.gate is first_failed else "was never reached"
            skipped.append(Skip(entry.name, f"gate {first_failed.value} did not pass, so gate "
                                            f"{entry.gate.value} {reached}"))
            continue
        missing = entry.missing(available_inputs)
        if missing:
            skipped.append(Skip(entry.name, "required inputs are not ingested", missing))
            continue
        to_run.append(entry)

    return RunPlan(tuple(to_run), tuple(skipped))
