"""Did the new prompt actually beat the old one? (SPEC §7.3, §7.5)

Every prediction records the agent version that made it, and that field existed from Phase 0 with
nothing reading it. Without this comparison, prompt evolution is a belief: a card gets edited, the edits
feel like improvements, and no one can say whether the firm got better at forecasting or merely
different. With it, a version bump is a claim that can be checked.

Brier is the right scale here because it punishes CONFIDENT wrongness specifically — which is the
failure prompt evolution exists to fix. Lower is better; 0.25 is what a coin flip stated at 50% earns.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise

from firm.core.monitoring.brier import brier_score
from firm.core.monitoring.predictions import Prediction


@dataclass(frozen=True)
class VersionScore:
    agent: str
    version: str
    brier: float
    resolved: int


@dataclass(frozen=True)
class VersionComparison:
    """Two versions of one agent's card, and whether the newer one earned its bump."""

    agent: str
    older: VersionScore
    newer: VersionScore
    #: None when neither side has enough resolved predictions to say anything honest.
    improved: bool | None
    verdict: str


def brier_by_agent_version(predictions: Sequence[Prediction]) -> list[VersionScore]:
    """Brier per (agent, agent_version), over resolved predictions only. Ascending by agent, version."""
    grouped: dict[tuple[str, str], list[tuple[float, bool]]] = defaultdict(list)
    for p in predictions:
        if p.resolved and p.outcome is not None:
            grouped[(p.agent, p.agent_version)].append((p.probability, bool(p.outcome)))
    return [
        VersionScore(agent=agent, version=version, brier=brier_score(pairs), resolved=len(pairs))
        for (agent, version), pairs in sorted(grouped.items())
    ]


def compare_versions(
    scores: Sequence[VersionScore], *, min_resolved: int
) -> list[VersionComparison]:
    """Consecutive version pairs per agent, with a refusal when the sample is too thin.

    `min_resolved` is not decoration. Brier over two predictions is noise wearing a decimal point, and
    declaring a prompt improved on that basis is how a firm talks itself into a change that did nothing
    — the same reasoning as `cumulative_cfo_pat_min_periods` refusing a cycle claim without a cycle.
    """
    by_agent: dict[str, list[VersionScore]] = defaultdict(list)
    for score in scores:
        by_agent[score.agent].append(score)

    out: list[VersionComparison] = []
    for agent, versions in sorted(by_agent.items()):
        ordered = sorted(versions, key=lambda s: s.version)
        for older, newer in pairwise(ordered):
            if older.resolved < min_resolved or newer.resolved < min_resolved:
                out.append(VersionComparison(
                    agent=agent, older=older, newer=newer, improved=None,
                    verdict=(f"not comparable — {older.version} has {older.resolved} and "
                             f"{newer.version} has {newer.resolved} resolved prediction(s); "
                             f"{min_resolved} each is the floor for saying anything")))
                continue
            improved = newer.brier < older.brier
            out.append(VersionComparison(
                agent=agent, older=older, newer=newer, improved=improved,
                verdict=(f"{newer.version} scores {newer.brier:.4f} against {older.version}'s "
                         f"{older.brier:.4f} — "
                         f"{'the bump earned itself' if improved else 'the older card forecast better'}")))
    return out
