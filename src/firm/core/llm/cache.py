"""On-disk LLM response cache (Law 5). Keyed by a stable hash so re-runs are free and crashes resume."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def make_key(*parts: str) -> str:
    """Stable content hash over ordered string parts."""
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


@dataclass
class DiskCache:
    root: Path

    def __post_init__(self) -> None:
        self.root = Path(self.root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.root / f"{key}.json"

    def get(self, key: str) -> dict[str, Any] | None:
        p = self._path(key)
        if not p.exists():
            return None
        return json.loads(p.read_text())

    def set(self, key: str, value: dict[str, Any]) -> None:
        self._path(key).write_text(json.dumps(value))
