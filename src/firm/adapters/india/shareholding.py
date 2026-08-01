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
from typing import Sequence

from firm.adapters.base.tables import numbers_on_line

#: The category rows, as SEBI names them. Matched anywhere in the whitespace-collapsed page rather than at
#: line start: in the pre-2023 layout the label itself wraps ("A Promoter &\nPromoter\nGroup") and so does
#: the row's data, so no single physical line ever holds a whole row. A line-anchored pattern located 13 of
#: Alkyl Amines' 27 filings and silently refused the other 14 — seven years of the promoter series.
_PROMOTER_ROW = re.compile(r"(?:^|\s)\(?A\)?\s+promoter\s*&?\s*promoter\s*group\b", re.I)
_PUBLIC_ROW = re.compile(r"(?:^|\s)\(?B\)?\s+public\b", re.I)
_NON_PROMOTER_ROW = re.compile(r"(?:^|\s)\(?C\d?\)?\s+non[\s-]*promoter[\s-]*non[\s-]*public\b", re.I)
#: Where a category row's figures must stop. Without a terminator the public row would run on into Table II
#: (the promoter-by-name breakdown), whose per-shareholder percentages would then compete with the
#: category's own — and one of them reconciles to 100 by coincidence often enough to matter.
_ROW_END = re.compile(
    r"(?:^|\s)(?:\(?[BC]\d?\)?\s+(?:public|non[\s-]*promoter)|total\b|table\s+I{2,})", re.I
)

#: The promoter-pledge declaration, in both wordings SEBI has used.
#:
#: Pre-2025 the form asked one question: "Whether any shares held by promoters are pledge or otherwise
#: encumbered? No". From 2025 it asks three — encumbered under "Pledged", under "Non-Disposal
#: Undertaking", and otherwise — and the single-question pattern matched none of them, so the most recent
#: filings reported pledge as *unknown* while the page in front of us answered "No".
#:
#: This reads the PLEDGE question only. NDU and other encumbrance are different instruments that SEBI
#: deliberately separated, and folding them into a field named `pledged` would misreport them; they are an
#: open gap, not a silent alias. The alternation cannot drift onto them: question 9 reads "encumbered,
#: other than by way of Pledge" (comma, no "under") and question 8 names the NDU.
_PLEDGE_QUESTION = re.compile(
    r"whether\s+any\s+shares?\s+held\s+by\s+promoters?\s+are\s+"
    r"(?:pledge[d]?\s+or\s+otherwise\s+encumbered"
    r"|encumbered\s+under\s*[\"'“”]?\s*pledged)"
    r"[\"'“”]?\s*\??\s*(yes|no)?",
    re.I,
)
#: The reporting date. Real filings write "As on : 30-09-2024" with a colon and spaces, and some give only
#: "Quarter ending 30-09-2024" — an earlier pattern required "as on" followed immediately by the date and so
#: matched none of the 27 Alkyl Amines filings, leaving every quarter undated. The pre-2023 layout writes
#: the month as a NAME ("as on : 31-Mar-2021"), which no all-digit pattern can read.
_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
_AS_ON_PREFIX = r"(?:as\s+(?:on|at|of)|quarter\s+end(?:ing|ed))\s*:?\s*"
_AS_ON = re.compile(_AS_ON_PREFIX + r"(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})", re.I)
_AS_ON_NAMED = re.compile(
    _AS_ON_PREFIX + r"(\d{1,2})[/\-.\s]*(" + "|".join(_MONTHS) + r")[a-z]*[/\-.\s]*(\d{4})", re.I
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


def _row_region(flat: str, start: int) -> str:
    """The figures belonging to the category row that begins at ``start``, up to the next row's label.

    The row is bounded rather than read to end-of-page because Table II (the promoter breakdown by name)
    follows Table I on the same document, and its per-shareholder percentages must never be mistaken for
    the category's own.
    """
    end = _ROW_END.search(flat, start)
    return flat[start:end.start()] if end is not None else flat[start:]


def _integer_pcts(line: str) -> list[float]:
    """Whole-number readings of a row's percentage — the fallback when the filing does not print decimals.

    Some quarters round the category percentage to an integer ("(A) Promoter & Promoter Group 13 36819268
    36819268 72 ..."), which the decimal discriminator rejects by construction. Integers are far weaker
    evidence — the shareholder count is a small integer too — so they are tried ONLY after the decimal
    reading has failed to reconcile, and the identity still has to hold before anything is reported.
    """
    return [v for v in numbers_on_line(line) if 0 < v <= _MAX_PCT and v == int(v)]


def _closest_pair(promoter: Sequence[float], public: Sequence[float]) -> tuple[float, float]:
    """The (promoter, public) reading whose sum sits nearest the 100% the categories must total."""
    return min(((p, q) for p in promoter for q in public),
               key=lambda pair: abs(pair[0] + pair[1] - 100.0))


def _reconciles(promoter: float, public: float) -> bool:
    return abs(promoter + public - 100.0) <= _RECONCILE_TOLERANCE


def parse_shareholding(pages: tuple[str, ...]) -> ShareholdingSummary:
    """Promoter holding, public holding and pledge status from a SEBI shareholding pattern.

    Returns `located=False` with `rejected_because` set when the categories cannot be reconciled, rather
    than a plausible-looking wrong stake.
    """
    promoter_candidates: list[float] = []
    public_candidates: list[float] = []
    promoter_integers: list[float] = []
    public_integers: list[float] = []
    promoter_holders = None
    pledged: bool | None = None
    as_on: str | None = None
    page_found = 0

    for index, page in enumerate(pages, start=1):
        # ONE COLLAPSED STRING PER PAGE. Both layouts then read alike: the 2023-onward filings put a
        # category row on one physical line, the older ones wrap the label and its figures over a dozen.
        # Collapsing per page (not per document) keeps the page number the locator needs.
        flat = re.sub(r"\s+", " ", page)

        promoter_row = _PROMOTER_ROW.search(flat)
        if not promoter_candidates and not promoter_integers and promoter_row is not None:
            region = _row_region(flat, promoter_row.end())
            promoter_candidates = _candidate_pcts(region)
            promoter_integers = _integer_pcts(region)
            counts = [v for v in numbers_on_line(region) if v == int(v) and v > 0]
            promoter_holders = int(counts[0]) if counts else None
            page_found = page_found or index

        public_row = _PUBLIC_ROW.search(flat)
        if not public_candidates and not public_integers and public_row is not None:
            region = _row_region(flat, public_row.end())
            public_candidates = _candidate_pcts(region)
            public_integers = _integer_pcts(region)
            page_found = page_found or index

        pledge_match = _PLEDGE_QUESTION.search(flat)
        if pledge_match is not None and pledged is None:
            answer = (pledge_match.group(1) or "").lower()
            # An unanswered question stays None: the form was present, the answer was not.
            pledged = True if answer == "yes" else (False if answer == "no" else None)

        if as_on is None:
            on = _AS_ON.search(flat)
            if on is not None:
                as_on = f"{on.group(3)}-{int(on.group(2)):02d}-{int(on.group(1)):02d}"
            else:
                named = _AS_ON_NAMED.search(flat)
                if named is not None:
                    month = _MONTHS.index(named.group(2).lower()) + 1
                    as_on = f"{named.group(3)}-{month:02d}-{int(named.group(1)):02d}"

    all_promoter = promoter_candidates + promoter_integers
    all_public = public_candidates + public_integers
    if not all_promoter or not all_public:
        return ShareholdingSummary(
            located=False, pledged=pledged, as_on=as_on,
            rejected_because="the promoter and public category rows were not both located",
        )

    # THE IDENTITY DISAMBIGUATES. Promoter % + public % = 100 by construction, so where the text layer welded
    # a percentage onto a share count the correct split is the one that reconciles. This turns an acceptance
    # test into a repair — and one that cannot invent a stake, because a wrong split simply fails to sum.
    #
    # The decimal reading leads. A decimal in range is strong evidence of a percentage, because share counts
    # are large integers; a whole number is weak evidence, because the shareholder count is a small integer
    # too. So the integer reading is consulted only where the decimal one does not reconcile — and it must
    # still satisfy the identity, which for two integers means summing to exactly 100.
    decimal_pair = (_closest_pair(promoter_candidates, public_candidates)
                    if promoter_candidates and public_candidates else None)
    integer_pair = _closest_pair(all_promoter, all_public)
    if decimal_pair is not None and _reconciles(*decimal_pair):
        best = decimal_pair
    elif _reconciles(*integer_pair):
        best = integer_pair
    else:
        # Nothing reconciles. Refuse below, quoting the strongest reading available.
        best = decimal_pair or integer_pair
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
