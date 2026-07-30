"""Citation validator (Law 2 / SPEC §9) — every number in a report must map to a known fact_id.

Convention: a number is cited by an adjacent token ``[fact:<id>]``. The validator extracts numbers and,
for each, checks a citation token follows within a short window and that its id is known. Percentages,
year tokens (FY24), and quarter tokens (Q1FY25) are ignored — they are labels, not claims.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# A numeric claim: an integer/decimal, optionally signed, optionally with thousands separators or %.
_NUMBER = re.compile(r"(?<![\w.])[-+]?\d[\d,]*(?:\.\d+)?%?")
_CITE = re.compile(r"\[fact:([A-Za-z0-9_\-]+)\]")
# Tokens that look numeric but are labels, not claims.
_LABEL = re.compile(r"\b(FY\d{2,4}|Q[1-4]FY\d{2,4})\b", re.IGNORECASE)


@dataclass(frozen=True)
class CitationProblem:
    number: str
    position: int
    reason: str  # 'no_citation' | 'unknown_fact_id'


def validate(text: str, known_fact_ids: set[str], window: int = 24) -> list[CitationProblem]:
    """Return unsourced or wrongly-sourced numbers. Empty list = every number is properly cited."""
    ignore_spans = [m.span() for m in _LABEL.finditer(text)]
    ignore_spans += [m.span() for m in _CITE.finditer(text)]  # don't flag digits inside [fact:112]
    problems: list[CitationProblem] = []
    for m in _NUMBER.finditer(text):
        start, end = m.span()
        if any(ls <= start < le for ls, le in ignore_spans):  # FY24 / Q1FY25 / inside a cite token
            continue
        tail = text[end:end + window]
        cite = _CITE.search(tail)
        if cite is None:
            problems.append(CitationProblem(m.group(0), start, "no_citation"))
        elif cite.group(1) not in known_fact_ids:
            problems.append(CitationProblem(m.group(0), start, "unknown_fact_id"))
    return problems
