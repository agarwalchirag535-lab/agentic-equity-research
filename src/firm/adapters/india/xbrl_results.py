"""Quarterly results from the exchange's XBRL, already tagged (ADR-0043).

WHAT THIS REPLACES
Reading the P&L out of an annual-report PDF: finding the right page among 228, recognising this issuer's
name for its revenue line, and establishing the scale from a parenthetical that might render the rupee
glyph as a backtick or a capital H. Every one of those was a real defect this session, and every one of
them exists only because the numbers were being recovered from a rendered document.

NSE disseminates each quarterly result as XBRL against the standard BSE financial taxonomy. The company
tagged it; the exchange published it; the scale is declared in the file. `InterestEarned` is an element
name, not a string to hunt for on a page.

THE SECTOR BRANCH ARRIVES AS DATA
A bank files `BANKING_*.xml` and everyone else files `INDAS_*.xml`, and the results metadata carries a
`bank: B|N` flag saying which. ADR-0002 requires lender checks to branch away from Beneish/Piotroski;
until now that branch was inferred from balance-sheet shape. The filing states it.

It also carries `GrossNonPerformingAssets`, `PercentageOfGrossNpa` and `ReturnOnAssets` — the lender
forensic inputs `core/compute/quality.py` has had checks for since Phase 1 and never had data behind.

WHAT IS STILL REFUSED
The scale is read from the XBRL `unit`, never assumed: an element in `iso4217:INR` is converted to the
firm's canonical crore, an element in `xbrli:pure` is a ratio and is left alone, and anything in a unit
this module does not recognise is DROPPED with the reason rather than stored at a guessed scale — the
same discipline as ADR-0024.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date
from typing import Any, Mapping, Sequence

from firm.core.config import load_yaml

#: XBRL money is filed in absolute rupees; the firm's canonical money scale is ₹ crore.
_RUPEES_TO_CRORE = 1e-7
#: Unit measures we understand. Anything else is refused rather than guessed at.
_MONEY_MEASURES = ("iso4217:inr",)
_RATIO_MEASURES = ("xbrli:pure", "pure")


@dataclass(frozen=True)
class XbrlFact:
    """One tagged figure, with the period it covers and the scale already resolved."""

    metric: str
    element: str
    value: float
    period_start: date | None
    period_end: date
    is_ratio: bool

    @property
    def instant(self) -> bool:
        """True for a balance-sheet-style point-in-time figure (no start date)."""
        return self.period_start is None


@dataclass(frozen=True)
class ResultFiling:
    """One quarterly result as the exchange disseminated it."""

    symbol: str
    company_name: str
    period_start: date
    period_end: date
    #: The exchange dissemination timestamp — the honest `published_at` (Law 3).
    broadcast_on: date | None
    audited: bool
    consolidated: bool
    is_bank: bool
    xbrl_url: str
    facts: tuple[XbrlFact, ...] = ()

    @property
    def grade(self) -> str:
        """A when the company declares the figures audited, B when it declares them un-audited.

        Read from the filing's own `audited` flag rather than assumed. A quarterly result is normally
        un-audited and the year-end one is audited, and the feed says which — so the grade is an
        observation about this filing, not a rule of thumb about quarters.
        """
        return "A" if self.audited else "B"

    @property
    def quarter(self) -> str:
        """`FY25Q3` — the Indian fiscal quarter this result covers."""
        month = self.period_end.month
        fiscal_year = self.period_end.year + 1 if month >= 4 else self.period_end.year
        return f"FY{fiscal_year % 100:02d}Q{((month - 4) % 12) // 3 + 1}"


def _metric_map() -> tuple[dict[str, str], dict[str, str], frozenset[str]]:
    """`(banking, indas, ratio metric names)` from `config/xbrl_metrics.yaml`."""
    raw = load_yaml("xbrl_metrics.yaml")
    common = dict(raw.get("common") or {})
    banking = {**common, **(raw.get("banking") or {})}
    indas = {**common, **(raw.get("indas") or {})}
    return banking, indas, frozenset(raw.get("ratios") or ())


def _nse_datetime(value: object) -> date | None:
    """`31-Jan-2025 19:32:58` -> a date, or None."""
    if not value:
        return None
    months = {m: i for i, m in enumerate(
        ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"), start=1)}
    parts = str(value).strip().split(" ")[0].split("-")
    if len(parts) != 3 or not parts[0].isdigit() or not parts[2].isdigit():
        return None
    month = months.get(parts[1].upper()[:3])
    return None if month is None else date(int(parts[2]), month, int(parts[0]))


def parse_xbrl(xml_text: str, *, is_bank: bool) -> list[XbrlFact]:
    """Every mapped element in an exchange XBRL result, with its period and scale resolved.

    An element the config does not map is skipped silently — the taxonomy carries hundreds of tags and
    the firm reads the ones its compute layer uses. An element whose UNIT is unrecognised is skipped
    too, but that is a different thing and deliberately so: an unmappable name is uninteresting, an
    unresolvable scale is dangerous (ADR-0024).
    """
    banking, indas, ratio_metrics = _metric_map()
    mapping = banking if is_bank else indas
    root = ET.fromstring(xml_text)

    contexts: dict[str, tuple[date | None, date]] = {}
    for node in root.iter():
        if not node.tag.endswith("}context"):
            continue
        period = node.find(".//{*}period")
        if period is None:
            continue
        start = period.find("{*}startDate")
        end = period.find("{*}endDate")
        instant = period.find("{*}instant")
        end_text = end.text if end is not None else (instant.text if instant is not None else None)
        if not end_text:
            continue
        contexts[str(node.get("id"))] = (
            date.fromisoformat(start.text) if start is not None and start.text else None,
            date.fromisoformat(end_text[:10]),
        )

    units: dict[str, str] = {}
    for node in root.iter():
        if not node.tag.endswith("}unit"):
            continue
        measure = node.find(".//{*}measure")
        if measure is not None and measure.text:
            units[str(node.get("id"))] = measure.text.strip().lower()

    out: list[XbrlFact] = []
    seen: set[tuple[str, date | None, date]] = set()
    for node in root.iter():
        if "}" not in node.tag:
            continue
        namespace, element = node.tag.split("}")
        if "in-bse-fin" not in namespace or not node.text or not node.text.strip():
            continue
        metric = mapping.get(element)
        context_ref = node.get("contextRef")
        if metric is None or context_ref not in contexts:
            continue
        measure = units.get(str(node.get("unitRef")), "")
        is_ratio = metric in ratio_metrics
        if is_ratio:
            if measure and measure not in _RATIO_MEASURES:
                continue
            scale = 1.0
        else:
            if measure not in _MONEY_MEASURES:
                continue        # scale unknown -> refuse, never guess (ADR-0024)
            scale = _RUPEES_TO_CRORE
        try:
            value = float(node.text.strip())
        except ValueError:
            continue

        start, end = contexts[context_ref]
        key = (metric, start, end)
        if key in seen:
            continue            # the same figure is tagged once per dimension; the undimensioned one wins
        seen.add(key)
        out.append(XbrlFact(metric=metric, element=element, value=value * scale,
                            period_start=start, period_end=end, is_ratio=is_ratio))
    return out


def parse_results_index(payload: Sequence[Mapping[str, Any]]) -> list[ResultFiling]:
    """The results feed's metadata, newest first, before any XBRL is fetched."""
    out: list[ResultFiling] = []
    for row in payload:
        start = _nse_datetime(row.get("fromDate"))
        end = _nse_datetime(row.get("toDate"))
        if start is None or end is None or not row.get("xbrl"):
            continue
        out.append(ResultFiling(
            symbol=str(row.get("symbol") or ""),
            company_name=str(row.get("companyName") or ""),
            period_start=start, period_end=end,
            broadcast_on=_nse_datetime(row.get("broadCastDate")),
            audited=str(row.get("audited") or "").strip().lower().startswith("audited"),
            consolidated=str(row.get("consolidated") or "").strip().lower() == "consolidated",
            is_bank=str(row.get("bank") or "N").strip().upper() == "B",
            xbrl_url=str(row["xbrl"]),
        ))
    return sorted(out, key=lambda r: r.period_end)


def annual_from_quarters(
    facts: Sequence[XbrlFact], metric: str, fiscal_year_end: date
) -> tuple[float | None, int]:
    """Sum four quarters of a flow metric into the fiscal year, and say how many were found.

    THIS IS THE CROSS-CHECK, not a convenience. A quarterly series that sums to the audited annual figure
    validates BOTH: the quarters were read correctly and the annual filing agrees with what the company
    reported through the year. Returns `(sum, quarters_found)` so a caller can refuse a partial year
    rather than publish three quarters as if they were four.
    """
    start = date(fiscal_year_end.year - 1, 4, 1)
    within = [
        f for f in facts
        if f.metric == metric and not f.instant and not f.is_ratio
        and f.period_start is not None and f.period_start >= start and f.period_end <= fiscal_year_end
    ]
    # Keep only the ~3-month periods: the same filing also tags year-to-date and full-year spans, and
    # adding those to the quarters would double- or triple-count the year.
    quarters = [f for f in within if 80 <= (f.period_end - f.period_start).days <= 100]
    if not quarters:
        return None, 0
    return sum(f.value for f in quarters), len(quarters)


__all__ = [
    "ResultFiling",
    "XbrlFact",
    "annual_from_quarters",
    "parse_results_index",
    "parse_xbrl",
]
