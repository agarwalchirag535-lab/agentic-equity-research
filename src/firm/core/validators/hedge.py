"""Hedge detector (SPEC §9) — flags vague quantifiers that house style §1 forbids, forcing a number."""

from __future__ import annotations

import re

# Vague quantifiers that must be replaced by a number + citation.
HEDGE_WORDS = [
    "strong", "healthy", "significant", "robust", "meaningful", "substantial", "solid",
    "impressive", "attractive", "comfortable", "decent", "handsome", "sizeable", "sizable",
    "considerable", "steady", "good", "strong growth", "healthy margins", "significant opportunity",
]

_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in sorted(HEDGE_WORDS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)


def find_hedges(text: str) -> list[str]:
    """Return the vague quantifiers found in ``text`` (lowercased, in order of appearance)."""
    return [m.group(0).lower() for m in _PATTERN.finditer(text)]


def has_hedges(text: str) -> bool:
    return _PATTERN.search(text) is not None
