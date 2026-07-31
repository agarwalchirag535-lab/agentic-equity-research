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
#:
#: DELIBERATELY SHORTER THAN THE FULL CATEGORY NAME. The first version required
#: `A Promoter & Promoter Group` to appear on ONE line, and a PDF text layer does not promise that: on 14 of
#: Alkyl Amines' 27 filings the cell wraps as `A Promoter &` / `Promoter` / `Group`, with the figures several
#: lines below. Anchoring on the category letter plus its first word matches the row wherever the extractor
#: chose to break it; `_row_block` then reads the whole row rather than one line of it.
_PROMOTER_ROW = re.compile(r"^\(?A\)?[\s.]+promoter\b", re.I)
_PUBLIC_ROW = re.compile(r"^\(?B\)?[\s.]+public\b", re.I)
_NON_PROMOTER_ROW = re.compile(r"^\(?C\)?[\s.]+non[\s-]*promoter\b", re.I)

#: A row's figures never run more than this many wrapped lines past its label. A cap matters: without one a
#: mis-detected category marker would swallow the rest of the document and scavenge a reconciling pair out
#: of unrelated tables.
_MAX_ROW_LINES = 40

#: "Whether any shares held by promoters are pledge or otherwise encumbered? No"
_PLEDGE_QUESTION = re.compile(
    r"whether\s+any\s+shares?\s+held\s+by\s+promoters?\s+are\s+pledge[d]?\s+or\s+otherwise\s+"
    r"encumbered\s*\??\s*(yes|no)?",
    re.I,
)
#: The reporting date. SEBI's own cover page writes "4. Share Holding Pattern as on : 31-Mar-2022", so the
#: separator is optional-colon and the month is as often a NAME as a number. The numeric-only pattern found
#: the date on **none** of Alkyl Amines' 27 filings, which for a point-in-time system is the whole ballgame:
#: an undated quarterly filing cannot be placed in a series and cannot be filtered by `published_at <= as_of`.
_MONTHS = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), start=1)}
_AS_ON_NUMERIC = re.compile(
    r"as\s+(?:on|at|of)\s*:?\s*(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})", re.I)
_AS_ON_NAMED = re.compile(
    r"as\s+(?:on|at|of)\s*:?\s*(\d{1,2})[\s/\-.]*([A-Za-z]{3,9})[\s/\-.,]*(\d{4})", re.I)


#: Some filings carry no "as on" line at all, only the depository extraction header:
#: `GENERATED ON :13/01/2026   NSDL : 31/12/2025   CDSL :31/12/2025`. The NSDL/CDSL date is the quarter end
#: the register was pulled as of — the reporting date by another name — while GENERATED ON is the day the
#: form was produced, which is later and is NOT the reporting date. Read the former, never the latter, and
#: label the basis so a reader can tell a stated date from a recovered one.
_DEPOSITORY_DATE = re.compile(r"\b(?:NSDL|CDSL)\s*:?\s*(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})", re.I)


def _as_on_date(line: str) -> str | None:
    """The reporting date in ISO form, or None. Both `31-03-2022` and `31-Mar-2022` are the same filing."""
    numeric = _AS_ON_NUMERIC.search(line)
    if numeric is not None:
        return f"{numeric.group(3)}-{int(numeric.group(2)):02d}-{int(numeric.group(1)):02d}"
    named = _AS_ON_NAMED.search(line)
    if named is not None:
        month = _MONTHS.get(named.group(2)[:3].lower())
        if month is not None:
            return f"{named.group(3)}-{month:02d}-{int(named.group(1)):02d}"
    return None


def _depository_date(line: str) -> str | None:
    """The quarter-end the depository register was extracted as of, or None."""
    found = _DEPOSITORY_DATE.search(line)
    if found is None:
        return None
    return f"{found.group(3)}-{int(found.group(2)):02d}-{int(found.group(1)):02d}"

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
    #: How `as_on` was established — `stated` (the filing's own "as on" line) or `depository-date` (recovered
    #: from the NSDL/CDSL extraction header on a filing that carries no "as on" line). Travels with the date
    #: for the same reason `published_at_basis` travels with a filing's: a point-in-time claim resting on a
    #: recovered date should not be indistinguishable from one resting on a stated one.
    as_on_basis: str | None = None
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


def _integer_pcts(text: str) -> list[float]:
    """Whole-number readings of a holding percentage — the `72` / `28` case.

    Kept SEPARATE from the decimal candidates and consulted only if no decimal pair reconciles. A promoter
    stake that is exactly 72.00% is filed as `72`, and refusing it would reject a real disclosure over a
    formatting choice — but a row also contains shareholder counts, and `13` or `28` are perfectly good
    integers too. Trying decimals first means the 13 filings that already parsed keep parsing by exactly the
    route they did, and the integer reading is reached only where the alternative is reporting nothing.
    """
    out: list[float] = []
    for value in numbers_on_line(text):
        if 0 < value <= _MAX_PCT and value == int(value) and value not in out:
            out.append(value)
    return out


def _row_block(lines: list[str], start: int, boundaries: list[int]) -> str:
    """One category row as a single string, however many lines the text layer wrapped it across.

    Joined with SPACES, never concatenated. Concatenation would repair `3678526` + `8` into the true share
    count but would equally weld `72.03` onto whatever preceded it, inventing figures. Spacing leaves the
    split share count as two meaningless integers — which the percentage scan ignores — while the holding
    percentage, printed once per column, survives intact as a standalone token.
    """
    ends = [b for b in boundaries if b > start]
    end = min(ends) if ends else len(lines)
    return " ".join(line.strip() for line in lines[start:min(end, start + _MAX_ROW_LINES)])


def _best_pair(
    promoter: list[float], public: list[float]
) -> tuple[float, float] | None:
    """The (promoter, public) reading closest to summing to 100, or None if either side has no candidate."""
    if not promoter or not public:
        return None
    return min(
        ((p, q) for p in promoter for q in public),
        key=lambda pair: abs(pair[0] + pair[1] - 100.0),
    )


def parse_shareholding(pages: tuple[str, ...]) -> ShareholdingSummary:
    """Promoter holding, public holding and pledge status from a SEBI shareholding pattern.

    Returns `located=False` with `rejected_because` set when the categories cannot be reconciled, rather
    than a plausible-looking wrong stake.
    """
    # Flatten to lines once, remembering which page each came from: a row's label and its figures can
    # straddle a page break, and the row is the unit of meaning, not the page.
    lines: list[str] = []
    page_of: list[int] = []
    pledged: bool | None = None
    as_on: str | None = None
    as_on_basis: str | None = None
    depository_on: str | None = None
    for index, page in enumerate(pages, start=1):
        for line in page.splitlines():
            stripped = line.strip()
            lines.append(stripped)
            page_of.append(index)

            pledge_match = _PLEDGE_QUESTION.search(stripped)
            if pledge_match is not None and pledged is None:
                answer = (pledge_match.group(1) or "").lower()
                # An unanswered question stays None: the form was present, the answer was not.
                pledged = True if answer == "yes" else (False if answer == "no" else None)

            if as_on is None:
                as_on = _as_on_date(stripped)
                as_on_basis = "stated" if as_on else None
            if depository_on is None:
                depository_on = _depository_date(stripped)

    if as_on is None and depository_on is not None:
        as_on, as_on_basis = depository_on, "depository-date"

    # The SEBI wording sometimes puts the pledge answer on the line AFTER the question, because the question
    # wraps. Look one line on before concluding the form was left blank.
    if pledged is None:
        for index, line in enumerate(lines):
            if _PLEDGE_QUESTION.search(line) and index + 1 < len(lines):
                answer = lines[index + 1].strip().lower()
                if answer in ("yes", "no"):
                    pledged = answer == "yes"
                    break

    starts = {"promoter": None, "public": None, "non_public": None}
    boundaries: list[int] = []
    for index, line in enumerate(lines):
        for key, pattern in (("promoter", _PROMOTER_ROW), ("public", _PUBLIC_ROW),
                             ("non_public", _NON_PROMOTER_ROW)):
            if pattern.match(line):
                boundaries.append(index)
                if starts[key] is None:
                    starts[key] = index

    if starts["promoter"] is None or starts["public"] is None:
        return ShareholdingSummary(
            located=False, pledged=pledged, as_on=as_on, as_on_basis=as_on_basis,
            rejected_because="the promoter and public category rows were not both located",
        )

    promoter_block = _row_block(lines, starts["promoter"], boundaries)
    public_block = _row_block(lines, starts["public"], boundaries)
    page_found = page_of[starts["promoter"]]

    counts = [v for v in numbers_on_line(promoter_block) if v == int(v) and v > 0]
    promoter_holders = int(counts[0]) if counts else None

    promoter_candidates = _candidate_pcts(promoter_block)
    public_candidates = _candidate_pcts(public_block)

    # THE IDENTITY DISAMBIGUATES. Promoter % + public % = 100 by construction, so where the text layer welded
    # a percentage onto a share count the correct split is the one that reconciles. This turns an acceptance
    # test into a repair — and one that cannot invent a stake, because a wrong split simply fails to sum.
    #
    # Decimals are tried alone first and integers folded in only if nothing reconciles, so a filing that
    # states 72.03/27.97 is never at risk of a coincidental integer pair, while one that states a flat 72/28
    # is still read. Fall back rather than merge.
    best = _best_pair(promoter_candidates, public_candidates)
    if best is None or abs(best[0] + best[1] - 100.0) > _RECONCILE_TOLERANCE:
        widened = _best_pair(
            promoter_candidates + _integer_pcts(promoter_block),
            public_candidates + _integer_pcts(public_block),
        )
        if widened is not None and (best is None
                                    or abs(widened[0] + widened[1] - 100.0)
                                    < abs(best[0] + best[1] - 100.0)):
            best = widened

    if best is None:
        return ShareholdingSummary(
            located=False, pledged=pledged, as_on=as_on, as_on_basis=as_on_basis,
            rejected_because="no percentage could be read from the promoter or public category row",
        )
    promoter_pct, public_pct = best

    summary = ShareholdingSummary(
        located=True, promoter_pct=promoter_pct, public_pct=public_pct,
        promoter_shareholders=promoter_holders, pledged=pledged, as_on=as_on,
        as_on_basis=as_on_basis, page=page_found,
    )
    if not summary.reconciles:
        # A stake that reads 71.96% when it is really 17.96% would look entirely plausible and drive a
        # governance verdict off a cliff. Refuse rather than report.
        return ShareholdingSummary(
            located=False, pledged=pledged, as_on=as_on, as_on_basis=as_on_basis,
            rejected_because=(
                f"promoter {promoter_pct}% + public {public_pct}% = "
                f"{promoter_pct + public_pct:.2f}%, which does not reconcile to 100% — the columns were "
                f"likely interleaved by the text layer, so no holding is reported"
            ),
        )
    return summary
