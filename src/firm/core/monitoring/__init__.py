"""The memory / self-improvement loop (SPEC §7): predictions, resolution, Brier calibration."""

from firm.core.monitoring.brier import brier_by_agent, brier_score
from firm.core.monitoring.predictions import Prediction, append_jsonl, read_jsonl
from firm.core.monitoring.resolver import evaluate, resolve

__all__ = [
    "brier_by_agent", "brier_score",
    "Prediction", "append_jsonl", "read_jsonl",
    "evaluate", "resolve",
]
