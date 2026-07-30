"""Load an agent from its markdown file: YAML frontmatter + prompt body (Law 6 — prompts live in .md)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class AgentSpec:
    name: str
    version: str
    output_schema: str  # dotted import path, e.g. 'firm.schemas.agents.ForensicAccountantOutput'
    body: str
    meta: dict[str, Any]


def load_agent(path: str | Path) -> AgentSpec:
    text = Path(path).read_text()
    if not text.startswith("---"):
        raise ValueError(f"{path}: missing YAML frontmatter")
    _, frontmatter, body = text.split("---", 2)
    meta = yaml.safe_load(frontmatter) or {}
    return AgentSpec(
        name=meta["name"],
        version=str(meta["version"]),
        output_schema=meta.get("output_schema", ""),
        body=body.strip(),
        meta=meta,
    )
