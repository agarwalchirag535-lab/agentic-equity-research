"""Citation validator (Law 2 / SPEC §9) — every number in a report must map to a known fact_id.

Convention: a number is cited by an adjacent token ``[fact:<id>]``. The validator extracts numbers and,
for each, checks a citation token follows within a short window, that its id is known, and — when the
caller supplies the values — that the number actually **matches** the fact it points at. Year tokens
(FY24) and quarter tokens (Q1FY25) are ignored: they are labels, not claims.

Three deliberate design points, each of which was a defect before it was decided:

1. **Fact ids contain colons** (``derived:cum_cfo_pat``, ``screener-X:pnl:Sales:FY26``). An id grammar
   that excluded them meant no real id could ever be cited, so the validator silently degenerated into
   "no numbers in prose at all" — passing by vacuum rather than by provenance.
2. **A digit glued to a preceding word is still a number.** "Rs9999 crore" is ordinary Indian financial
   prose; excluding it let a fabricated figure through unchecked. The cost of this strictness is that
   alphanumeric identifiers ("COVID-19") must be reworded or cited — a false positive fails the run and
   is corrected on retry, which is the safe direction for a fraud detector.
3. **A citation token is not a value check.** Pointing at a real fact while stating a different number is
   the most plausible way an LLM corrupts a figure it was handed. When ``values`` is supplied, the stated
   number must equal the fact within tolerance, in either decimal or percentage form.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping

# A numeric claim: an integer/decimal, optionally signed, optionally with thousands separators or %.
# The lookbehind excludes only a preceding digit or dot, so a decimal is never split — but a number
# glued to letters ("Rs9999") IS a claim (see design point 2 above).
_NUMBER = re.compile(r"(?<![\d.])[-+]?\d[\d,]*(?:\.\d+)?%?")
# Fact ids are namespaced with colons and may carry dots/dashes: derived:cum_cfo_pat,
# screener-ALKYLAMINE-2026-07-23:pnl:Sales:FY26.
_CITE = re.compile(r"\[fact:([A-Za-z0-9_.:\-]+)\]")
# Tokens that look numeric but are labels, not claims.
_LABEL = re.compile(r"\b(FY\d{2,4}|Q[1-4]FY\d{2,4})\b", re.IGNORECASE)

#: A quoted figure may be rounded, and may be written as a percentage of the underlying ratio.
_VALUE_REL_TOL = 0.02

#: Typographic minus signs, normalised to ASCII before scanning. An LLM writing polished prose emits
#: U+2212 routinely; leaving it unhandled meant "−0.03" parsed as **+0.03**, so a sign corruption — the
#: exact "keep the citation, change the number" attack the value check exists to stop — passed, while
#: correctly-written negative prose failed. Same-width replacements keep `position` offsets truthful.
_MINUS_SIGNS = str.maketrans({"\u2212": "-", "\u2013": "-"})


@dataclass(frozen=True)
class CitationProblem:
    number: str
    position: int
    reason: str  # 'no_citation' | 'unknown_fact_id' | 'value_mismatch'


def parse_quoted(token: str) -> float | None:
    """'1,234' → 1234.0 · '13.2%' → 13.2 · '-0.03' → -0.03. None when unparseable."""
    cleaned = token.replace(",", "").rstrip("%")
    try:
        return float(cleaned)
    except ValueError:  # pragma: no cover - _NUMBER only matches parseable tokens
        return None


def _decimals(token: str) -> int:
    body = token.replace(",", "").rstrip("%")
    return len(body.split(".", 1)[1]) if "." in body else 0


def _matches_value(quoted: str, actual: float) -> bool:
    """Does the quoted figure state the fact's value, allowing rounding and percentage form?

    Two acceptances, because a flat relative tolerance is wrong for small magnitudes: an analyst writing
    "-0.03" for -0.0320 is rounding correctly, not changing the number. So a quote passes if it is within
    ``_VALUE_REL_TOL`` of the fact **or** equals the fact rounded to the precision the quote itself uses.
    Changing the digits ("0.42" for 1.2714) fails both.
    """
    parsed = parse_quoted(quoted)
    if parsed is None:  # pragma: no cover - see parse_quoted
        return False
    places = _decimals(quoted)
    for candidate in (actual, actual * 100.0):
        scale = max(abs(candidate), 1e-9)
        if abs(parsed - candidate) <= _VALUE_REL_TOL * scale:
            return True
        if round(candidate, places) == round(parsed, places):
            return True
    return False


def validate(
    text: str,
    known_fact_ids: set[str],
    window: int = 24,
    values: Mapping[str, float] | None = None,
) -> list[CitationProblem]:
    """Return unsourced, wrongly-sourced or misquoted numbers. Empty list = every number checks out.

    ``window`` is how far after the number the citation token may sit. ``values`` is optional: supply
    ``{fact_id: value}`` and a number that cites a real fact but states a different figure is reported as
    ``value_mismatch`` rather than accepted.

    Known and accepted strictness (all fail toward "flag it", which is the safe direction for a fraud
    detector — an author reformulates and the run retries):

    * a **bare calendar year** ("commissioned in 2019") is a claim, because a 4-digit number is also how a
      real figure would hide. Use the FY form (`FY19`), which is a recognised label;
    * a **chemical formula** ("CO2", "NH3") reads as a glued number — write the compound out;
    * a **range** ("18-20%") is two numbers, and each needs its own source;
    * with two numbers before one token ("grew from 1000 to 1050 [fact:X]"), both are attributed to X, so
      the first will usually be a `value_mismatch`. Cite each figure separately.
    """
    text = text.translate(_MINUS_SIGNS)
    ignore_spans = [m.span() for m in _LABEL.finditer(text)]
    ignore_spans += [m.span() for m in _CITE.finditer(text)]  # don't flag digits inside a fact id
    problems: list[CitationProblem] = []
    for m in _NUMBER.finditer(text):
        start, end = m.span()
        if any(ls <= start < le for ls, le in ignore_spans):  # FY24 / Q1FY25 / inside a cite token
            continue
        # `window` bounds where the token may START, not how much text is searched: a namespaced id is
        # easily longer than the window, and truncating the search made long (i.e. real) ids unmatchable.
        cite = _CITE.search(text, end)
        if cite is None or cite.start() - end > window:
            problems.append(CitationProblem(m.group(0), start, "no_citation"))
            continue
        fact_id = cite.group(1)
        if fact_id not in known_fact_ids:
            problems.append(CitationProblem(m.group(0), start, "unknown_fact_id"))
        elif values is not None and fact_id in values and not _matches_value(m.group(0), values[fact_id]):
            problems.append(CitationProblem(m.group(0), start, "value_mismatch"))
    return problems
