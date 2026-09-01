"""Daily closing prices from the exchange's own chart endpoint (ADR-0062).

WHY THIS SOURCE, AND WHY IT IS FREE. Valuation needs a price: an enterprise value to invert (SPEC §5's
"reverse DCF first" asks what growth today's price already demands), and a market cap to size a
position against. `config/roster.yaml` has therefore listed `prices` as `portfolio_manager`'s
prerequisite — and as NOT INGESTED — since Phase 3.

The obvious move is a market-data vendor. It is the wrong move twice over. Money is the smaller
reason. The larger one is `adapters/base/sourcing.py`: this firm grades a primary filing A and an
aggregator B, and every published number carries its grade. A price scraped from a third-party
aggregator would be a grade-B input to the one number the whole valuation tier pivots on, with a
citation a reader cannot check. BSE publishes its own settled closes, keyed by scrip code, with no
API key — the same origin as the announcements and annual reports that are already this firm's
point-in-time spine. That is a grade-A price, cited to the exchange, for nothing.

LAW 3 IS THE WHOLE DESIGN HERE. A price series is the easiest place in the system to leak the future:
one careless `series[-1]` in a replay of 2019 values a company at today's price and every backtest
becomes a fantasy. `close_on_or_before` is therefore the ONLY accessor — it takes the `as_of` and
refuses to look past it — and the raw series is never handed out for a caller to index.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from typing import Callable, Sequence

#: The exchange's chart endpoint. `flag=1` is the daily-close series; `flag=0` is intraday ticks.
_CHART = ("https://api.bseindia.com/BseIndiaAPI/api/StockReachGraph/w"
          "?scripcode={scrip}&flag=1&fromdate={start:%Y%m%d}&todate={end:%Y%m%d}&seriesid=")

#: How the endpoint writes a day: "Mon Jan 01 2018 00:00:00". Parsed strictly rather than with a
#: permissive dateutil-style guess — a misparsed date in a point-in-time series is a look-ahead bug
#: that no downstream check can see.
_DAY = re.compile(r"^[A-Za-z]{3}\s+([A-Za-z]{3})\s+(\d{1,2})\s+(\d{4})\b")
_MONTHS = {m: i + 1 for i, m in enumerate(
    ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"))}


@dataclass(frozen=True)
class Close:
    """One settled daily close, as the exchange published it."""

    on: date
    price: float
    volume: float


def price_url(scrip_code: str, start: date, end: date) -> str:
    return _CHART.format(scrip=scrip_code, start=start, end=end)


def parse_closes(payload: str) -> list[Close]:
    """The endpoint's nested payload as a dated series, oldest first.

    The response is JSON whose `Data` member is itself a JSON *string* — decoded here rather than by a
    caller, so the double encoding has exactly one place to be got wrong. A row whose date or price
    cannot be parsed is DROPPED rather than guessed at: a gap in a price series is visible to
    `close_on_or_before` (it returns an older close, with its real date), while an invented price is
    not visible to anything.
    """
    try:
        outer = json.loads(payload)
        rows = json.loads(outer.get("Data") or "[]")
    except (ValueError, AttributeError):
        return []
    out: list[Close] = []
    for row in rows:
        match = _DAY.match(str(row.get("dttm", "")))
        if match is None:
            continue
        month = _MONTHS.get(match.group(1))
        if month is None:
            continue
        try:
            on = date(int(match.group(3)), month, int(match.group(2)))
            price = float(row["vale1"])
            volume = float(row.get("vole") or 0.0)
        except (KeyError, TypeError, ValueError):
            continue
        if price > 0:
            out.append(Close(on, price, volume))
    return sorted(out, key=lambda c: c.on)


def close_on_or_before(closes: Sequence[Close], as_of: date) -> Close | None:
    """The most recent close AT OR BEFORE `as_of`, or None if the series starts later.

    The only way to read a price in this firm. A weekend, a holiday or a trading halt means the answer
    is an older close — which is correct and, because `Close.on` travels with it, visible: a valuation
    dated 2019-01-31 that rests on a 2019-01-29 close says so in its own citation.
    """
    eligible = [c for c in closes if c.on <= as_of]
    return max(eligible, key=lambda c: c.on) if eligible else None


def fetch_closes(
    scrip_code: str, start: date, end: date, fetch: Callable[[str], str]
) -> list[Close]:
    """Daily closes for a scrip over a window. `fetch` is injected so this is offline-testable."""
    return parse_closes(fetch(price_url(scrip_code, start, end)))
