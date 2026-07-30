"""Parse a SEBI shareholding pattern into promoter holding and pledge (Phase 3, ADR-0032).

WHY THIS GENERALISES
Reg. 31 of the SEBI LODR fixes the *format* of this filing, not just the obligation to make it. Every Indian
listed company files the same table every quarter: category (A) Promoter & Promoter Group, (B) Public,
(C) Non Promoter-Non Public, with a shareholder count, share counts and a holding percentage, plus a
standard question — "Whether any shares held by promoters are pledge or otherwise encumbered?". So a parser
written against one company's filing is a parser for the market, which is why this is worth doing properly
rather than per-issuer.

WHAT IT REFUSES TO DO
The categories are exhaustive by construction: promoter % + public % + non-promoter-non-public % = 100. That
identity is used as an **acceptance test on our own extraction**, not as a fact to report. A PDF text layer
can interleave columns, and a promoter stake that reads 71.96% when it is really 17.96% is the kind of error
that would drive a governance verdict off a cliff while looking entirely plausible. If the categories do not
reconcile to 100 within tolerance, nothing is returned and the reason is stated — the same discipline as the
unit-scale refusal in ADR-0024.

Pledge is tri-state for the ADR-0027 reason: `False` (the filing was read and says no pledge) is a real
governance finding; `None` (no pledge question located) is a refusal to conclude. They must never look alike.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from firm.adapters.base.tables import numbers_on_line

#: The category rows, as SEBI names them. Matched at line start after an optional "(A)"-style marker.
_PROMOTER_ROW = re.compile(r"^\(?A\)?\s+promoter\s*&?\s*promoter\s*group\b", re.I)
_PUBLIC_ROW = re.compile(r"^\(?B\)?\s+public\b", re.I)
_NON_PROMOTER_ROW = re.compile(r"^\(?C\)?\s+non[\s-]*promoter[\s-]*non[\s-]*public\b", re.I)

#: "Whether any shares held by promoters are pledge or otherwise encumbered? No"
_PLEDGE_QUESTION = re.compile(
    r"whether\s+any\s+shares?\s+held\s+by\s+promoters?\s+are\s+pledge[d]?\s+or\s+otherwise\s+"
    r"encumbered\s*\??\s*(yes|no)?",
    re.I,
)
#: The reporting date. Real filings write "As on : 30-09-2024" with a colon and spaces, and some give only
#: "Quarter ending 30-09-2024" — an earlier pattern required "as on" followed immediately by the date and so
#: matched none of the 27 Alkyl Amines filings, leaving every quarter undated.
_AS_ON = re.compile(
    r"(?:as\s+(?:on|at|of)|quarter\s+end(?:ing|ed))\s*:?\s*(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})",
    re.I,
)

#: A holding percentage is in (0, 100]. Share COUNTS are large integers, so a decimal in range is the
#: discriminator that survives column interleaving.
_MAX_PCT = 100.0
#: The categories must reconcile to 100%. Filings round to 2dp, and a few round each category independently,
#: so a few hundredths of slack is real rounding rather than a misread.
_RECONCILE_TOLERANCE = 0.15


@dataclass(frozen=True)
class ShareholdingSummary:
    """One quarter's shareholding pattern, or an explicit refusal to report it."""

    located: bool
    promoter_pct: float | None = None
    public_pct: float | None = None
    promoter_shareholders: int | None = None
    pledged: bool | None = None
    as_on: str | None = None
    page: int = 0
    rejected_because: str | None = None

    @property
    def locator(self) -> str:
        return f"p.{self.page}" if self.located else "shareholding pattern not parsed"

    @property
    def reconciles(self) -> bool:
        """Whether the categories sum to 100 — the extraction's own acceptance test."""
        if self.promoter_pct is None or self.public_pct is None:
            return False
        return abs(self.promoter_pct + self.public_pct - 100.0) <= _RECONCILE_TOLERANCE


#: A percentage welded onto the end of a share count by a text layer that lost the column separator:
#: "3683726872.0265" is 36837268 shares followed by 72.0265 percent. Seen on 15 of Alkyl Amines' 27 filings.
_WELDED = re.compile(r"\d{4,}(\d{1,2}\.\d{2,4})")


def _candidate_pcts(line: str) -> list[float]:
    """Every reading of this row that could be a holding percentage, best guess first.

    Two sources. The clean case: a standalone decimal in (0, 100]. The broken case: a percentage welded to
    the share count because the PDF text layer dropped the column boundary. The welded case is genuinely
    ambiguous — "3683726872.0265" splits as 36837268 + 72.0265 or as 368372687 + 2.0265, and nothing in the
    token says which. `parse_shareholding` resolves it with the category identity rather than a guess.
    """
    out: list[float] = []
    for value in numbers_on_line(line):
        if 0 < value <= _MAX_PCT and value != int(value):
            out.append(value)
    for token in re.findall(r"\d+\.\d+", line):
        whole, _, decimals = token.partition(".")
        # A share count welded to a percentage: the integer part is far longer than any percentage. Emit
        # BOTH readings — the last one or two digits of the integer part — because the token itself cannot
        # say which is right. A greedy single regex silently picked the one-digit split and produced 2.0265
        # where the truth is 72.0265; generating both and letting the identity choose is what fixes it.
        if len(whole) < 3 or len(decimals) < 2:
            continue
        for width in (2, 1):
            candidate = float(f"{whole[-width:]}.{decimals}")
            if 0 < candidate <= _MAX_PCT and candidate not in out:
                out.append(candidate)
    return out


def _holding_pct(line: str) -> float | None:
    """The single best reading of a category row's percentage, for callers that cannot disambiguate."""
    candidates = _candidate_pcts(line)
    return candidates[0] if candidates else None


def parse_shareholding(pages: tuple[str, ...]) -> ShareholdingSummary:
    """Promoter holding, public holding and pledge status from a SEBI shareholding pattern.

    Returns `located=False` with `rejected_because` set when the categories cannot be reconciled, rather
    than a plausible-looking wrong stake.
    """
    promoter_candidates: list[float] = []
    public_candidates: list[float] = []
    promoter_holders = None
    pledged: bool | None = None
    as_on: str | None = None
    page_found = 0

    for index, page in enumerate(pages, start=1):
        for line in page.splitlines():
            stripped = line.strip()
            if not promoter_candidates and _PROMOTER_ROW.match(stripped):
                promoter_candidates = _candidate_pcts(stripped)
                counts = [v for v in numbers_on_line(stripped) if v == int(v) and v > 0]
                promoter_holders = int(counts[0]) if counts else None
                page_found = page_found or index
            elif not public_candidates and _PUBLIC_ROW.match(stripped):
                public_candidates = _candidate_pcts(stripped)
                page_found = page_found or index

            pledge_match = _PLEDGE_QUESTION.search(stripped)
            if pledge_match is not None and pledged is None:
                answer = (pledge_match.group(1) or "").lower()
                # An unanswered question stays None: the form was present, the answer was not.
                pledged = True if answer == "yes" else (False if answer == "no" else None)

            if as_on is None:
                on = _AS_ON.search(stripped)
                if on is not None:
                    as_on = f"{on.group(3)}-{int(on.group(2)):02d}-{int(on.group(1)):02d}"

    if not promoter_candidates or not public_candidates:
        return ShareholdingSummary(
            located=False, pledged=pledged, as_on=as_on,
            rejected_because="the promoter and public category rows were not both located",
        )

    # THE IDENTITY DISAMBIGUATES. Promoter % + public % = 100 by construction, so where the text layer welded
    # a percentage onto a share count the correct split is the one that reconciles. This turns an acceptance
    # test into a repair — and one that cannot invent a stake, because a wrong split simply fails to sum.
    best = min(
        ((p, q) for p in promoter_candidates for q in public_candidates),
        key=lambda pair: abs(pair[0] + pair[1] - 100.0),
    )
    promoter_pct, public_pct = best

    summary = ShareholdingSummary(
        located=True, promoter_pct=promoter_pct, public_pct=public_pct,
        promoter_shareholders=promoter_holders, pledged=pledged, as_on=as_on, page=page_found,
    )
    if not summary.reconciles:
        # A stake that reads 71.96% when it is really 17.96% would look entirely plausible and drive a
        # governance verdict off a cliff. Refuse rather than report.
        return ShareholdingSummary(
            located=False, pledged=pledged, as_on=as_on,
            rejected_because=(
                f"promoter {promoter_pct}% + public {public_pct}% = "
                f"{promoter_pct + public_pct:.2f}%, which does not reconcile to 100% — the columns were "
                f"likely interleaved by the text layer, so no holding is reported"
            ),
        )
    return summary
