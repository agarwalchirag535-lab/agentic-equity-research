"""Falsifiable predictions (SPEC §7.1) — every thesis emits these; the loop resolves and scores them.

Append-only JSONL is the store (Law 6: no proprietary formats).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

if TYPE_CHECKING:  # import-cycle guard: schemas.report does not depend on monitoring
    from firm.schemas.report import ResearchReport

Operator = Literal[">=", ">", "<=", "<", "=="]


class Prediction(BaseModel):
    prediction_id: str
    run_id: str
    ticker: str
    agent: str
    agent_version: str
    claim: str
    metric: str
    operator: Operator
    threshold: float
    resolve_by: date
    probability: float = Field(ge=0.0, le=1.0)
    load_bearing: bool = False
    evidence_fact_ids: list[str] = Field(default_factory=list)
    resolved: bool | None = None
    outcome: bool | None = None


def append_jsonl(path: Path, pred: Prediction) -> None:
    with Path(path).open("a") as fh:
        fh.write(pred.model_dump_json() + "\n")


def read_jsonl(path: Path) -> list[Prediction]:
    p = Path(path)
    if not p.exists():
        return []
    return [Prediction.model_validate_json(line) for line in p.read_text().splitlines() if line.strip()]


def predictions_from_report(report: ResearchReport) -> list[Prediction]:
    """Turn a published report's **kill** criteria into scoreable predictions (Phase 5, ADR-0023).

    Two decisions, because a prediction log is only worth keeping if it is honest about what was actually
    forecast:

    1. **Kill criteria only.** A kill criterion is the firm's real forecast: "this load-bearing number
       continues to hold, and if it stops the thesis is dead." A *rehabilitation* criterion is the opposite
       — a counterfactual condition the firm expects NOT to occur and is not predicting. Logging both would
       fill the Brier record with events nobody forecast and make the calibration score meaningless. The
       rehabilitation criteria stay in the report, where they belong, and out of the ledger.

    2. **`probability` is the report's own confidence, not a fresh judgment.** Law 1 forbids an LLM
       authoring a number, and inventing a per-criterion probability in code would be worse — arbitrary
       precision with nothing behind it. `Confidence.value` already states how much the firm believes the
       evidence under these claims, computed from playbook evaluability, note-review share, line-item
       coverage and the weakest grade relied on. That is exactly the right quantity: the probability that
       the facts the criterion rests on keep holding. It also means a shallow report logs a low-confidence
       prediction and is scored gently, while a confident one is scored hard — which is the incentive the
       calibration loop should create.

    `prediction_id` is derived from `(run_id, metric)`, so re-running the same inputs cannot double-log
    (Law 5: idempotent).
    """
    return [
        Prediction(
            prediction_id=f"{report.run_id}:{c.metric}",
            run_id=report.run_id,
            ticker=report.ticker,
            # Attribution is to the code path that authored the criterion, not to an agent: these numbers
            # are computed (ADR-0021 decision 4), and crediting an agent for them would be a lie the
            # calibration record then compounds.
            agent="core.report.criteria",
            agent_version="1.0.0",
            claim=c.statement,
            metric=c.metric,
            operator=c.operator,
            threshold=c.threshold,
            resolve_by=c.resolve_by,
            probability=report.confidence.value,
            load_bearing=c.load_bearing,
        )
        for c in report.kill_criteria
    ]


def log_report_predictions(report: ResearchReport, path: Path) -> list[Prediction]:
    """Append a report's kill criteria to the prediction ledger, skipping any already recorded.

    Idempotent by `prediction_id`, so replaying a run appends nothing and the ledger stays a faithful
    record of what was forecast once, rather than of how many times the pipeline was re-run.
    """
    already = {p.prediction_id for p in read_jsonl(path)}
    fresh = [p for p in predictions_from_report(report) if p.prediction_id not in already]
    if fresh:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        for pred in fresh:
            append_jsonl(path, pred)
    return fresh
