"""Falsifiable predictions (SPEC §7.1) — every thesis emits these; the loop resolves and scores them.

Append-only JSONL is the store (Law 6: no proprietary formats).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

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
