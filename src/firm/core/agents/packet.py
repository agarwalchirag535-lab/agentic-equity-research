"""Assemble an agent's prompt packet: house style (system) + agent mandate + computed facts + schema.

This is what makes an agent runnable by ANY provider — the paid API, the `claude -p` CLI, or Claude
Code acting as the model directly. Numbers arrive pre-computed from `core/compute` (Law 1); the agent's
job is to reason and return JSON matching its schema (Law 4).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from firm.core.agents.loader import AgentSpec


def load_house_style(repo_root: str | Path) -> str:
    """Concatenate the shared standards every agent inherits (agents/_shared/*.md)."""
    shared = Path(repo_root) / "agents" / "_shared"
    parts = []
    for name in ("house_style.md", "epistemics.md", "forbidden.md"):
        f = shared / name
        if f.exists():
            parts.append(f.read_text().strip())
    return "\n\n---\n\n".join(parts)


def build_packet(
    agent: AgentSpec,
    facts: dict[str, Any],
    schema_json: dict[str, Any],
    house_style: str,
) -> tuple[str, str]:
    """Return (system, user) prompts for the agent.

    - system: the house analytical standards.
    - user: the agent mandate + the computed facts + the required JSON schema.
    """
    system = house_style
    user = (
        f"{agent.body}\n\n"
        "## Computed facts (from core/compute — treat every number as authoritative; DO NOT alter or "
        "invent numbers, Law 1)\n"
        f"```json\n{json.dumps(facts, indent=2, default=str)}\n```\n\n"
        "## Return ONLY a single JSON object matching this schema (Law 4). No prose outside the JSON; "
        "put your reasoning in the `narrative` field.\n"
        f"```json\n{json.dumps(schema_json, indent=2)}\n```"
    )
    return system, user
