"""Prompt evolution — proposals a human approves, never edits a card applies to itself (SPEC §7.3).

THE RULE THAT SHAPES THIS MODULE. A system that rewrites its own instructions from its own failure log,
unattended, optimises for a quiet log rather than for being right. SPEC §7.3 puts a person in the loop
and this code keeps them there: it emits a PROPOSAL — the agent card to change, the cluster of lessons
that justify it, and the exact block to insert — and it neither writes to `agents/*.md` nor touches
git. The human is the actor; this is the thing that puts a well-argued option in front of them.

WHY THREE. A single miss is a sample of one, and a prompt patched after every bad quarter is a prompt
overfitted to the last bad quarter. SPEC's `>= 3 lessons in the same root cause` is the cheapest
available defence against learning noise, and it lives in config so it can be argued with.

WHAT IS NOT INVENTED. The proposed block is assembled from the `action` lines the lesson authors wrote,
quoted verbatim with attribution. Nothing here composes new guidance: if no person has written what to
do about a cluster, the honest output is a proposal that says the cluster is ready and its actions are
empty — not a paragraph this module made up.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from firm.core.evolution.lessons import Lesson


@dataclass(frozen=True)
class Proposal:
    """One prompt change, ready for a person to accept or reject."""

    agent: str
    category: str
    lessons: tuple[Lesson, ...]
    #: True when the cluster meets the SPEC §7.3 floor. Below it the cluster is still REPORTED — a
    #: near-miss cluster is how you see a pattern forming before it is worth acting on.
    ready: bool
    patch: str

    @property
    def size(self) -> int:
        return len(self.lessons)


@dataclass(frozen=True)
class EvolutionReport:
    """Everything the job found: what is ready, what is forming, and what cannot be used at all."""

    proposals: tuple[Proposal, ...]
    #: Lessons that cannot enter a cluster, each with the reason. The ledger's own backlog.
    unclassified: tuple[tuple[Lesson, str], ...]

    @property
    def ready(self) -> tuple[Proposal, ...]:
        return tuple(p for p in self.proposals if p.ready)


def _patch_block(agent: str, category: str, lessons: Sequence[Lesson]) -> str:
    """The block to insert into the agent's card, built only from what people wrote."""
    actions = [(le, le.action.strip()) for le in lessons if le.action.strip()]
    lines = [
        f"## Learned from resolved predictions — {category}",
        "",
        (f"_{len(lessons)} resolved prediction(s) failed for this root cause. Added by prompt "
         f"evolution (SPEC §7.3) and approved by a human; each line is a lesson author's own wording._"),
        "",
    ]
    if not actions:
        lines.append(
            "_The cluster is real but no lesson states an action. Nothing is proposed for the card "
            "until someone writes what should change — a generated instruction here would be this "
            "system telling itself what to think._"
        )
    else:
        lines += [f"- {action}  \n  _({le.ticker or 'unknown'}, {le.date}, run `{le.run_id}`)_"
                  for le, action in actions]
    return "\n".join(lines)


def propose_changes(lessons: Sequence[Lesson], *, min_cluster: int) -> EvolutionReport:
    """Cluster classified lessons by (agent, root cause) and propose a change for each cluster."""
    unclassified = tuple((le, le.blocking_reason) for le in lessons if not le.classified)

    clusters: dict[tuple[str, str], list[Lesson]] = defaultdict(list)
    for lesson in lessons:
        if lesson.classified:
            clusters[(lesson.agent, lesson.category)].append(lesson)

    proposals = tuple(
        Proposal(agent=agent, category=category, lessons=tuple(group),
                 ready=len(group) >= min_cluster,
                 patch=_patch_block(agent, category, group))
        # Biggest cluster first: the strongest evidence should be the first thing a reviewer reads.
        for (agent, category), group in sorted(
            clusters.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    )
    return EvolutionReport(proposals=proposals, unclassified=unclassified)
