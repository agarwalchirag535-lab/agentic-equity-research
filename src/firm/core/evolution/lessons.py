"""The lesson ledger: what a resolved prediction taught, in a form a machine can cluster (SPEC §7.2).

A lesson is written by a PERSON, from a prediction that resolved. That is deliberate and is the line
this module does not cross: the root cause of a forecasting miss is a judgment about why the world
differed from the model, and a system that infers its own root causes from its own failure log will
reliably conclude that it was nearly right.

So the schema carries two fields the free-text ledger did not have — `category` (from SPEC §7.2's fixed
taxonomy) and `agent` (whose prompt the lesson bears on) — and a lesson missing either is REPORTED as
needing classification rather than quietly bucketed. The 18 lessons written before this schema existed
are exactly that case, and they are surfaced, not guessed at.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

#: SPEC §7.2 step 3, verbatim. A closed taxonomy on purpose: an open one drifts into a synonym per
#: lesson, and then nothing ever clusters and no change is ever proposed.
ROOT_CAUSES: frozenset[str] = frozenset({
    "data_error",
    "parsing_error",
    "wrong_base_rate",
    "overweighted_management_claim",
    "missed_competitive_response",
    "missed_capital_structure_risk",
    "macro_shock",
    "overconfident_prior",
    "insufficient_disconfirming_search",
})


class Lesson(BaseModel):
    """One thing a resolved prediction taught. Free-text fields are the author's; the rest is structure."""

    date: str
    run_id: str = ""
    ticker: str = ""
    source: str = ""
    lesson: str
    evidence: list[str] = Field(default_factory=list)
    #: What the author proposes doing about it. This — not a generated sentence — is what a prompt
    #: proposal is built from, so every proposed change traces to something a person wrote.
    action: str = ""
    #: SPEC §7.2's fixed taxonomy. Empty means unclassified, which blocks clustering by design.
    category: str = ""
    #: Which agent's card this bears on. Empty means untargetable — a proposal needs a file to change.
    agent: str = ""

    @property
    def classified(self) -> bool:
        return self.category in ROOT_CAUSES and bool(self.agent)

    @property
    def blocking_reason(self) -> str:
        """Why this lesson cannot yet drive a proposal, or "" when it can."""
        if not self.category:
            return "no `category` — cannot cluster a lesson whose root cause nobody has named"
        if self.category not in ROOT_CAUSES:
            return (f"category {self.category!r} is outside SPEC §7.2's taxonomy "
                    f"({', '.join(sorted(ROOT_CAUSES))})")
        if not self.agent:
            return "no `agent` — a prompt proposal needs a card to change"
        return ""


def read_lessons(path: str | Path) -> list[Lesson]:
    """Read `memory/lessons.jsonl`. A malformed line is a defect to see, not one to skip silently."""
    p = Path(path)
    if not p.exists():
        return []
    out: list[Lesson] = []
    for number, line in enumerate(p.read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            out.append(Lesson.model_validate(json.loads(line)))
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError(f"{p}:{number} is not a readable lesson — {exc}") from exc
    return out
