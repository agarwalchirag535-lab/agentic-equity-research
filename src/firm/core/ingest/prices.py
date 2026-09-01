"""Register the exchange's settled close as a citable fact (ADR-0062).

WHY ONE PRICE AND NOT THE SERIES. A valuation needs the price on ONE day: the `as_of`. Writing 2,000
daily closes into the fact store per company would multiply its size for no analytical gain — the
series is how the close is FOUND, not what the report cites. Any historical price is re-fetchable
deterministically from the same endpoint and window, so nothing is lost by not hoarding it.

WHAT IS REGISTERED, AND WHY EACH ONE
  `market:Close`     the settled close on or before `as_of`, ₹ per share. The input the reverse DCF
                     inverts: "what growth does THIS price already demand?"
  `market:ADV`       average daily traded value over the trailing window, ₹ crore. SPEC §8's Gate A
                     has always specified a liquidity floor (`screen.adv_floor_cr`) and never had a
                     number to apply it to; this is that number. A 5-10x thesis on a stock nobody can
                     buy is a paper return.

THE DATE IS THE TRADING DATE, NEVER THE FETCH DATE — the same rule the filings spine follows
(ADR-0018). `published_at` is the day the exchange settled that close, so Law 3's
`published_at <= as_of` filter is exact rather than approximately right, and a report dated to a
Sunday cites the Friday it actually rests on.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from firm.adapters.india.prices import Close, close_on_or_before, fetch_closes, price_url
from firm.core.facts.store import Document, FactStore

CLOSE = "market:Close"
ADV = "market:ADV"

#: Trailing window for the liquidity average. A quarter of trading smooths a single block deal without
#: averaging across a re-rating.
ADV_WINDOW_DAYS = 90

#: How far back to pull so the window is full even across a long holiday or a trading suspension.
_FETCH_LOOKBACK_DAYS = 400


@dataclass(frozen=True)
class PriceIngestResult:
    """What the price ingest contributed, or why it could not."""

    status: str                       # 'registered' | 'no_price_at_as_of' | 'empty_series'
    close: Close | None = None
    adv_cr: float | None = None
    fact_ids: tuple[str, ...] = ()
    #: The registered facts themselves, so a valuation built on them carries their
    #: citation and grade rather than a re-lookup by id.
    facts: tuple[Any, ...] = ()
    detail: str = ""


def average_daily_value_cr(closes: Sequence[Close], as_of: date, window_days: int) -> float | None:
    """Mean daily traded VALUE (₹ crore) over the trailing window, or None if nothing traded in it.

    Value, not volume: a lakh shares of a ₹20 stock and a lakh of a ₹2,000 stock are not comparable
    liquidity, and the floor in `config/thresholds.yaml` is denominated in rupees. Computed here in
    trusted code from exchange data — never by an agent (Law 1).
    """
    start = as_of - timedelta(days=window_days)
    days = [c for c in closes if start <= c.on <= as_of]
    if not days:
        return None
    return sum(c.price * c.volume for c in days) / len(days) / 1e7   # rupees -> ₹ crore


def ingest_prices(
    store: FactStore,
    ticker: str,
    scrip_code: str,
    as_of: date,
    *,
    fetch: Callable[[str], str],
    window_days: int = ADV_WINDOW_DAYS,
) -> PriceIngestResult:
    """Fetch the close series and register the `as_of` close (and its trailing ADV) as grade-A facts.

    An absence is a status, never a silent zero (owner directive 2): a company whose series does not
    reach `as_of` returns `no_price_at_as_of`, and every valuation downstream reports UNAVAILABLE with
    that reason rather than valuing the company at a price nobody quoted.
    """
    start = as_of - timedelta(days=_FETCH_LOOKBACK_DAYS)
    closes = fetch_closes(scrip_code, start, as_of, fetch)
    if not closes:
        return PriceIngestResult("empty_series",
                                 detail=f"the exchange returned no closes for scrip {scrip_code} "
                                        f"in {start}..{as_of}")
    settled = close_on_or_before(closes, as_of)
    if settled is None:
        return PriceIngestResult("no_price_at_as_of",
                                 detail=f"the series starts {closes[0].on}, after as_of {as_of} — "
                                        "no price existed to value this company on that date")

    doc_id = f"BSE-CLOSE-{scrip_code}-{settled.on:%Y%m%d}"
    store.add_document(Document(
        doc_id=doc_id, source_url=price_url(scrip_code, start, as_of), sha256="",
        published_at=settled.on, fetched_at=settled.on, grade="A",
        extractor_version="bse-chart@1.0.0",
    ))
    period = settled.on.isoformat()
    ids: list[str] = []
    written: list[Any] = []

    def write(metric: str, value: float, unit: str, locator: str) -> None:
        fact_id = f"{doc_id}:{metric}:{period}"
        store.add_fact(fact_id=fact_id, doc_id=doc_id, ticker=ticker, metric=metric, period=period,
                       value=value, unit=unit, locator=locator, period_end=settled.on)
        ids.append(fact_id)
        got = store.query_fact(ticker, metric, period, as_of=settled.on)
        if got is not None:
            written.append(got)

    write(CLOSE, settled.price, "INR",
          f"BSE settled close for scrip {scrip_code} on {settled.on:%Y-%m-%d}")
    adv = average_daily_value_cr(closes, as_of, window_days)
    if adv is not None:
        write(ADV, adv, "INR_cr",
              f"mean daily traded value over the {window_days} days to {as_of:%Y-%m-%d} "
              f"(BSE daily close x volume)")
    return PriceIngestResult("registered", close=settled, adv_cr=adv, fact_ids=tuple(ids),
                             facts=tuple(written))


def latest_market_fact(store: FactStore, ticker: str, metric: str, as_of: date) -> Any | None:
    """The most recent `metric` fact dated on or before `as_of`, or None.

    Market facts are keyed by their TRADING DATE, not by a fiscal period, so `query_fact` — which wants
    a period it can name — cannot reach them. Both accessors that need one (the close for the
    valuation, the ADV for Gate A's liquidity floor) must also pin the period at or before the run
    date: the store's `published_at <= as_of` filter and this one are two different guards, and a
    price series is the place where losing either leaks the future into a replay.
    """
    dated = [f for f in store.query_metric_prefix(ticker, metric, as_of)
             if f.period <= as_of.isoformat()]
    return max(dated, key=lambda f: f.period) if dated else None
