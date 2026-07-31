"""Read the Schedule III ageing schedules — receivables, payables and capital work-in-progress (ADR-0038).

WHY THIS EXISTS
ADR-0037 established that these three tables are present in the filing and located them. Locating a table is
not reading it. Until this module, the report could say "the receivables ageing schedule is disclosed" and
nothing more, while the table itself carries the answers to the questions the forensic checks most want:

* how much of the receivable book is **disputed** or **credit-impaired** rather than merely outstanding;
* how much is aged **beyond a year**, which is the tail that a channel-stuffed book grows first;
* how much capital work-in-progress is in projects **temporarily suspended**, and how much has been sitting
  in the 2-3 year and >3 year buckets — the `ageing_cwip` cash-reality check (ADR-0006) has had no data
  behind it since it was written.

WHAT MAKES IT SAFE
Three refusals, because a wrong figure carrying a grade-A filing locator is worse than no figure:

1. **A dash is a zero, not a missing column.** These tables print "-" for nil, and a numeric scan silently
   drops it — which shifts every remaining figure one column left and reads a 2-3 year balance as a
   "less than 1 year" one. Rows are tokenised so "-" occupies its column.
2. **Alignment is verified, never assumed.** A row is only bucketed when its token count matches the header
   and its buckets sum to its own printed total. Otherwise the row keeps its total and reports
   `aligned=False`, so a caller can use the total and must not use the buckets.
3. **`located=False` is distinct from an empty table.** Not finding the schedule and finding it empty are
   opposite findings (the ADR-0027 rule, applied to tables).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from firm.adapters.base.tables import page_unit_hint, parse_number, to_canonical_crore

#: The table's own header. Every Indian filing prints one of these two phrasings above the buckets.
_ANCHORS: dict[str, tuple[str, ...]] = {
    "receivables": (r"outstanding\s+for\s+following\s+periods\s+from\s+due\s+date\s+of\s+payment",),
    "payables": (r"outstanding\s+for\s+following\s+periods\s+from\s+due\s+date\s+of\s+payment",),
    "cwip": (r"ageing\s+of\s+capital\s+work", r"amounts?\s+in\s+capital\s+work[\s-]*in[\s-]*progress"),
}

#: Bucket column labels, longest first so "more than 3 years" is not eaten by "3 years".
_BUCKET_LABELS: tuple[str, ...] = (
    "more than 3 years", "less than 6 months", "less than 1 year",
    "6 months-1year", "6 months- 1year", "6 months", "1-2 years", "2-3 years",
    "unbilled", "not due", "1year", "total",
)
_BUCKET_RE = re.compile("|".join(re.escape(b) for b in _BUCKET_LABELS), re.IGNORECASE)

#: A row label that classifies the balance rather than merely naming it. These are the forensic handles.
_DISPUTED = re.compile(r"\bdisputed\b", re.IGNORECASE)
_UNDISPUTED = re.compile(r"\bundisputed\b", re.IGNORECASE)
_IMPAIRED = re.compile(r"credit\s*impaired", re.IGNORECASE)
_SIGNIFICANT_RISK = re.compile(r"significant\s+increase\s+in\s+credit\s+risk", re.IGNORECASE)
_SUSPENDED = re.compile(r"temporarily\s+suspended", re.IGNORECASE)
_TOTAL_ROW = re.compile(r"^\s*total\b", re.IGNORECASE)

#: A numeric token OR a lone dash standing for nil. Order matters: try the number first.
_TOKEN = re.compile(r"\(?-?\d[\d,]*(?:\.\d+)?\)?|(?<![\w.])-(?![\w.])")
#: Where the figures start on a row: the first numeric-or-dash token preceded by label text.
_ROW_SPLIT = re.compile(r"^(?P<label>.*?)(?P<tail>(?:\s{1,}(?:\(?-?\d[\d,]*(?:\.\d+)?\)?|-))+\s*)$")


@dataclass(frozen=True)
class AgeingRow:
    """One line of an ageing table. `aligned` gates whether `buckets` may be trusted."""

    label: str
    buckets: tuple[float, ...]
    total: float
    aligned: bool

    @property
    def is_disputed(self) -> bool:
        return bool(_DISPUTED.search(self.label)) and not _UNDISPUTED.search(self.label)

    @property
    def is_impaired(self) -> bool:
        return bool(_IMPAIRED.search(self.label))

    @property
    def is_significant_risk(self) -> bool:
        return bool(_SIGNIFICANT_RISK.search(self.label))

    @property
    def is_suspended(self) -> bool:
        return bool(_SUSPENDED.search(self.label))


@dataclass(frozen=True)
class AgeingTable:
    """A parsed Schedule III ageing schedule, in canonical crore."""

    kind: str                       # 'receivables' | 'payables' | 'cwip'
    buckets: tuple[str, ...]
    rows: tuple[AgeingRow, ...]
    total: float
    page: int
    located: bool
    reason: str = ""                # why it is not located / not aligned

    @property
    def locator(self) -> str:
        return f"p.{self.page}" if self.located else "not found"

    @property
    def disputed(self) -> float:
        return sum(r.total for r in self.rows if r.is_disputed)

    @property
    def impaired(self) -> float:
        return sum(r.total for r in self.rows if r.is_impaired)

    @property
    def significant_risk(self) -> float:
        return sum(r.total for r in self.rows if r.is_significant_risk)

    @property
    def suspended(self) -> float:
        return sum(r.total for r in self.rows if r.is_suspended)

    @property
    def aligned(self) -> bool:
        """True when every non-total row bucketed cleanly, so `long_dated` may be quoted."""
        body = [r for r in self.rows if not _TOTAL_ROW.match(r.label)]
        return bool(body) and all(r.aligned for r in body)

    def bucket_total(self, *names: str) -> float | None:
        """Summed balance across the named buckets, or None when the columns are not trustworthy."""
        if not self.aligned:
            return None
        wanted = {n.lower() for n in names}
        idx = [i for i, b in enumerate(self.buckets) if b.lower() in wanted]
        if not idx:
            return None
        body = [r for r in self.rows if not _TOTAL_ROW.match(r.label)]
        return sum(r.buckets[i] for r in body for i in idx if i < len(r.buckets))

    @property
    def long_dated(self) -> float | None:
        """Balance aged beyond one year — the tail a deteriorating book grows first."""
        return self.bucket_total("1-2 years", "2-3 years", "more than 3 years")


def _tokenise(tail: str) -> list[float]:
    """Figures on a row, with a lone '-' read as 0.0 so columns keep their positions."""
    out: list[float] = []
    for match in _TOKEN.finditer(tail):
        token = match.group(0)
        if token == "-":
            out.append(0.0)
            continue
        value = parse_number(token)
        if value is not None:
            out.append(value)
    return out


def _bucket_labels(header: str) -> tuple[str, ...]:
    """Column labels in printed order, from a (possibly line-wrapped, already flattened) header."""
    return tuple(m.group(0).lower().replace("- 1year", "-1year") for m in _BUCKET_RE.finditer(header))


#: Trade receivables and trade payables print the SAME header phrase, so the anchor alone cannot tell them
#: apart. The note they sit under can: whichever of the two nouns appears most recently before the table is
#: the one it belongs to. Without this the caller has to pass a magic occurrence index that happens to be
#: right for one company's page order and silently wrong for the next.
_KIND_CONTEXT: dict[str, tuple[str, str]] = {
    "receivables": (r"trade\s+receivable", r"trade\s+payable"),
    "payables": (r"trade\s+payable", r"trade\s+receivable"),
}


def _context_matches(
    pages: tuple[str, ...], index: int, lines: list[str], line_no: int, kind: str
) -> bool:
    """Does the text preceding this table identify it as ``kind``? True when the kind is unambiguous."""
    pair = _KIND_CONTEXT.get(kind)
    if pair is None:
        return True
    # The owning note heading is often on the PREVIOUS page (note 24 on p.111, its ageing table on p.112),
    # so the lookback deliberately crosses the page boundary.
    before = ("\n".join(pages[index - 1].splitlines()[-60:]) if index else "") + "\n" \
        + "\n".join(lines[max(0, line_no - 60):line_no])
    mine = [m.end() for m in re.finditer(pair[0], before, re.IGNORECASE)]
    theirs = [m.end() for m in re.finditer(pair[1], before, re.IGNORECASE)]
    if not mine:
        return False
    return not theirs or mine[-1] > theirs[-1]


def parse_ageing_table(
    pages: tuple[str, ...], kind: str, *, occurrence: int = 0, max_lines: int = 40
) -> AgeingTable:
    """The ``occurrence``-th ageing schedule of ``kind`` in the document (0 = the first, i.e. current year).

    These tables are printed twice — current year then comparative — so the caller must say which it wants
    rather than getting whichever the scan happened to hit.
    """
    anchors = [re.compile(p, re.IGNORECASE) for p in _ANCHORS[kind]]
    # Collect anchor hits first, then DEDUPLICATE the ones inside a single table. `cwip` has two anchor
    # phrasings and both appear in the same schedule ("3.3a Ageing of Capital Work in progress" then
    # "Amounts in capital work-in-progress for a period of"), so counting raw matches made occurrence 1
    # the second HEADER LINE of the first table rather than the comparative-year table — silently
    # returning the current year twice.
    hits: list[tuple[int, int, list[str]]] = []
    for index, page in enumerate(pages):
        lines = page.splitlines()
        for line_no, line in enumerate(lines):
            if not any(a.search(line) for a in anchors):
                continue
            if hits and hits[-1][0] == index and line_no - hits[-1][1] < 4:
                continue                      # same table, second phrasing of its own header
            if not _context_matches(pages, index, lines, line_no, kind):
                continue
            hits.append((index, line_no, lines))
    if occurrence < len(hits):
        index, line_no, lines = hits[occurrence]
        return _parse_from(pages, index, lines, line_no, kind, max_lines)
    return AgeingTable(kind, (), (), 0.0, 0, False,
                       f"no {kind} ageing schedule found in the filing"
                       if not hits else
                       f"the filing carries {len(hits)} {kind} ageing schedule(s); "
                       f"occurrence {occurrence} was requested")


def _parse_from(
    pages: tuple[str, ...], index: int, lines: list[str], line_no: int, kind: str, max_lines: int
) -> AgeingTable:
    unit = page_unit_hint(pages[index])
    window = lines[line_no:line_no + max_lines]
    anchors = [re.compile(p, re.IGNORECASE) for p in _ANCHORS[kind]]

    # The header may wrap over several lines ("Unbilled Not due Less than / 6 months / ... / Total"), so
    # accumulate header lines until a row carrying figures appears.
    header_parts: list[str] = []
    body_start = 1
    for offset, line in enumerate(window[1:], start=1):
        stripped = line.strip()
        body_start = offset
        if _ROW_SPLIT.match(line.rstrip()) and _BUCKET_RE.search(" ".join(header_parts)):
            break
        # Once two or more columns are known, a line that carries words which are NOT column labels is the
        # first ROW, not more header. Without this the header swallows "i) Undisputed Trade receivable-",
        # and that prefix is exactly what classifies the row as disputed or not — the forensic point of
        # reading the table at all.
        if len(_bucket_labels(" ".join(header_parts))) >= 2 and stripped:
            residue = _BUCKET_RE.sub("", stripped)
            if len(re.sub(r"[^A-Za-z]", "", residue)) >= 4:
                break
        header_parts.append(line)
    buckets = _bucket_labels(" ".join(header_parts))

    rows: list[AgeingRow] = []
    pending_label = ""
    for line in window[body_start:]:
        stripped = line.rstrip()
        if not stripped.strip():
            continue
        # A new ageing schedule (or the next note) ends this table.
        if rows and any(a.search(stripped) for a in anchors):
            break
        match = _ROW_SPLIT.match(stripped)
        if match is None:
            # A label with no figures: it wraps onto the next line, so carry it forward.
            pending_label = f"{pending_label} {stripped.strip()}".strip()
            if len(pending_label) > 200:
                pending_label = ""
            continue
        label = f"{pending_label} {match.group('label').strip()}".strip()
        pending_label = ""
        values = _tokenise(match.group("tail"))
        if not values:
            continue
        total_raw = values[-1]
        body = values[:-1]
        # ALIGNMENT IS EARNED. The buckets are trusted only when the row has one figure per column AND
        # they add up to the row's own printed total — the table checks itself.
        aligned = (
            len(buckets) > 1
            and len(values) == len(buckets)
            and abs(sum(body) - total_raw) <= max(0.02 * max(abs(total_raw), 1.0), 0.05)
        )
        converted = [to_canonical_crore(v, unit) for v in values]
        if any(c is None for c in converted):
            continue
        rows.append(AgeingRow(
            label=label, buckets=tuple(converted[:-1]),  # type: ignore[arg-type]
            total=converted[-1],                          # type: ignore[arg-type]
            aligned=aligned,
        ))
        if _TOTAL_ROW.match(label):
            break

    if not rows:
        return AgeingTable(kind, buckets, (), 0.0, index + 1, False,
                           "the schedule heading was found but no figure rows could be parsed beneath it")
    total_row = next((r for r in rows if _TOTAL_ROW.match(r.label)), None)
    body_rows = [r for r in rows if not _TOTAL_ROW.match(r.label)]
    total = total_row.total if total_row is not None else sum(r.total for r in body_rows)
    reason = "" if all(r.aligned for r in body_rows) else (
        "row figures could not be matched to their columns (a row's buckets do not sum to its printed "
        "total), so bucket-level balances are withheld and only row totals are reported"
    )
    # Drop the printed Total row from `rows`: it is a sum, and leaving it in would double every aggregate.
    return AgeingTable(kind, buckets[:-1] if buckets and buckets[-1] == "total" else buckets,
                       tuple(body_rows), total, index + 1, True, reason)


__all__ = ["AgeingRow", "AgeingTable", "parse_ageing_table"]
