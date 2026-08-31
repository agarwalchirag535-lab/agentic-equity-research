"""The deterministic half of a run, in one place so callers cannot disagree about it (ADR-0057).

WHY THIS MODULE EXISTS. The sibling line found `firm deep-dive` and `firm packets` each assembling this
sequence themselves and drifting apart (its ADR-0060): a packet once told every agent revenue was
shrinking for a company compounding at 11%, because one caller ingested ten filings and the other one.
The golden-set harness is a third caller of the same sequence, and it is the one caller that must never
drift — an evaluation that measures something other than what the firm publishes measures nothing.

Deterministic in the Law-1 sense: facts, derivations, playbook, checks and the Gate-B screen. No agent,
no model, no network beyond fetching the pinned documents themselves. Given the same store and the same
`as_of` it returns the same answer every time, which is what makes it replayable and therefore evaluable.

Two ingest routes, matching the CLI (ADR-0055): the walker (`filings` manifest alone) and the verified
reading path (`readings_dir` beside it), in which case the walker contributes notes only.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from firm.core.compute import quality
from firm.core.compute.models import BusinessModel, Playbook, build_playbook, detect_models
from firm.core.config import (
    forensic_thresholds,
    load_thresholds,
    model_detection_thresholds,
    model_forensic_thresholds,
    model_playbooks,
    universal_forensic_thresholds,
)
from firm.core.facts.store import FactStore
from firm.core.pipeline import derive as D
from firm.core.pipeline.checks import CheckEvaluation, ExternalInputs, evaluate_checks
from firm.core.pipeline.filing import FilingWalk, walk_filing


@dataclass(frozen=True)
class DeterministicRun:
    """Everything the deterministic layer produced, and what it read to produce it."""

    ticker: str
    as_of: date
    facts: D.CompanyFacts
    derived: D.DerivedSet
    models: tuple[BusinessModel, ...]
    playbook: Playbook
    evaluation: CheckEvaluation
    screen: quality.ForensicScreenResult
    #: None when no filings manifest was supplied — the run then rests on whatever is already in the
    #: store, and says so rather than pretending the notes were read.
    walk: FilingWalk | None = None
    ingested: tuple[str, ...] = field(default_factory=tuple)


def deterministic_run(
    store: FactStore,
    ticker: str,
    as_of: date,
    *,
    filings: str | Path | None = None,
    bronze: str | Path = "data/bronze",
    manifest: Mapping[str, Any] | None = None,
    readings_dir: str | Path | None = None,
    fetcher=None,
) -> DeterministicRun:
    """Ingest, walk, derive, classify, check and screen — the whole Law-1 half of a run.

    `filings` (a manifest path) or `manifest` (already loaded) ingests every annual report published on
    or before `as_of`; with `readings_dir` the numeric facts come from the verified reading path
    (ADR-0046/0055) and the walker contributes the latest filing's notes only. The store is left OPEN;
    its lifetime belongs to the caller.
    """
    from firm.core.ingest.filings import (
        filing_from_manifest,
        ingest_manifest,
        load_manifest,
        quarantine_store_contradictions,
    )

    walk: FilingWalk | None = None
    ingested: tuple[str, ...] = ()
    if filings is not None or manifest is not None:
        data = manifest if manifest is not None else load_manifest(filings)  # type: ignore[arg-type]
        if readings_dir is not None:
            from firm.core.ingest.reading import ingest_readings_manifest

            results = ingest_readings_manifest(
                store, data, readings_dir=readings_dir, bronze=bronze, as_of=as_of, fetcher=fetcher)
            ingested = tuple(r.file for r in results if r.status == "registered")
            quarantine_store_contradictions(
                store, ticker, as_of, load_thresholds()["reconciliation"])
        else:
            walker_results = ingest_manifest(store, data, bronze=bronze, as_of=as_of)
            ingested = tuple(r.file for r in walker_results)
            from firm.core.ingest.filings import quarantine_extraction_errors
            from firm.core.pipeline.filing import COMPOSED_ROWS, FILING_ROWS

            quarantine_extraction_errors(
                store, ticker, walker_results, tuple(FILING_ROWS) + tuple(COMPOSED_ROWS),
                load_thresholds()["reconciliation"])
        usable = [
            entry for entry in sorted(data["filings"], key=lambda e: str(e["period"]))
            if date.fromisoformat(str(entry["published_at"])) <= as_of
        ]
        if usable:
            walk = walk_filing(store, ticker, filing_from_manifest(usable[-1], bronze),
                               numeric_rows=readings_dir is None)

    facts = D.load_company_facts(store, ticker, as_of)
    derived = D.derive_metrics(facts)
    from firm.core.pipeline.deep_dive import statement_shape

    models = tuple(detect_models(statement_shape(facts, derived), model_detection_thresholds()))
    playbook = build_playbook(models, model_playbooks())
    thresholds = load_thresholds()
    evaluation = evaluate_checks(
        playbook, derived, facts,
        forensic=thresholds["forensic"],
        universal=universal_forensic_thresholds(),
        model_specific=model_forensic_thresholds(),
        external=walk.external if walk is not None else ExternalInputs(),
    )
    sector = (quality.SectorClass.FINANCIAL
              if BusinessModel.LENDER in models or BusinessModel.BANK in models
              else quality.SectorClass.NON_FINANCIAL)
    screen = quality.forensic_screen(sector, evaluation.metrics, forensic_thresholds(),
                                    checks_ran=evaluation.ran, checks_expected=len(evaluation.applicable),
                                    min_ran_share=float(thresholds["forensic"].get("screen_min_ran_share", 0)))
    return DeterministicRun(
        ticker=ticker, as_of=as_of, facts=facts, derived=derived, models=models,
        playbook=playbook, evaluation=evaluation, screen=screen, walk=walk, ingested=ingested,
    )
