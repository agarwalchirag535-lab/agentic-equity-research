"""Load policy numbers from config/*.yaml so no threshold is hardcoded in Python (SPEC §3)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from firm.core.compute.quality import ForensicThresholds

# src/firm/core/config.py -> parents: [core, firm, src, <repo root>]
REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG_DIR = REPO_ROOT / "config"


def load_yaml(name: str) -> dict[str, Any]:
    with (CONFIG_DIR / name).open() as fh:
        return yaml.safe_load(fh)


def load_thresholds() -> dict[str, Any]:
    return load_yaml("thresholds.yaml")


def forensic_thresholds() -> ForensicThresholds:
    f = load_thresholds()["forensic"]
    return ForensicThresholds(
        cfo_pat_min=f["cfo_pat_min"],
        cumulative_cfo_pat_min=f["cumulative_cfo_pat_min"],
        sloan_accrual_flag=f["sloan_accrual_flag"],
        beneish_m_threshold=f["beneish_m_threshold"],
    )


def originate_to_sell_thresholds() -> dict[str, float]:
    """Thresholds for the originate-to-sell / lender earnings-quality checks (quality.py)."""
    return load_thresholds()["originate_to_sell"]


def divergence_thresholds() -> dict[str, float]:
    """Thresholds for the exogenous-series divergence scanner (divergence.py)."""
    return load_thresholds()["divergence"]


def universal_forensic_thresholds() -> dict[str, float]:
    """Thresholds for the universal SPEC §5 checks (receivables/inventory/other-income/trader)."""
    return load_thresholds()["universal_forensic"]


def load_playbooks() -> dict[str, Any]:
    """Business-model detection thresholds + per-model check playbooks (ADR-0017)."""
    return load_yaml("forensic_playbooks.yaml")


def model_detection_thresholds() -> dict[str, float]:
    return load_playbooks()["detection"]


def model_playbooks() -> dict[str, Any]:
    return load_playbooks()["playbooks"]
