"""Run the golden set against the deterministic pipeline (ADR-0061).

The impure half: it opens stores, reads PDFs and calls `deterministic_run` — the SAME sequence
`firm deep-dive` and `firm packets` call (ADR-0060). That is not a convenience. An evaluation that
measures something other than what the firm publishes measures nothing, and the two commands had already
drifted from each other once.

Scoring lives in `golden.py` and is pure, so a change in how a case is judged can never be mistaken for a
change in what the pipeline read.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from firm.core.eval.golden import CaseResult, EvalReport, GoldenCase, load_cases, score_case
from firm.core.facts.store import FactStore


def run_case(case: GoldenCase, *, bronze: str | Path, db: str = ":memory:") -> CaseResult:
    """Replay one case at its own `as_of` and score it.

    A fresh in-memory store per case by default: a golden case is a claim about what the firm concludes
    from THIS company's filings as of THIS date, and a store carrying another case's facts would quietly
    make that claim about something else.
    """
    from firm.core.pipeline.deterministic import deterministic_run

    store = FactStore(db)
    try:
        run = deterministic_run(store, case.ticker, case.as_of, filings=case.manifest, bronze=bronze,
                                readings_dir=case.readings or None)
        facts = {
            (metric, period): fact.value
            for metric, series in run.facts.series.items()
            for period, fact in series.items()
        }
        return score_case(
            case,
            screen=run.screen.verdict.value,
            flags=[f.name for f in run.screen.flags],
            facts=facts,
        )
    finally:
        store.close()


def run_golden_set(
    directory: str | Path = "evals/golden_set",
    *,
    bronze: str | Path = "data/bronze",
    only: Sequence[str] = (),
) -> EvalReport:
    """Every case in `directory` (or just `only`), replayed and scored."""
    cases = [c for c in load_cases(directory) if not only or c.case_id in only]
    return EvalReport(tuple(run_case(c, bronze=bronze) for c in cases))
