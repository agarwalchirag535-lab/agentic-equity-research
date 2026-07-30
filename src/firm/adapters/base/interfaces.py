"""Source-agnostic data adapter contracts (Law 6).

Any market (India first) implements these Protocols; `core/` depends only on the interfaces, so a dead
source is a one-file swap. Rows carry `published_at` where the source exposes it (Law 3); where a source
only gives a *current* snapshot, `published_at` is None and the ingest layer stamps the fetch date and
flags it as snapshot-derived (honest for as-of=today, not for historical eval).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class FinancialRow:
    ticker: str
    statement: str          # 'pnl' | 'balance_sheet' | 'cashflow'
    metric: str
    period: str             # 'FY24', 'Q1FY25'
    value: float
    unit: str               # 'INR_cr'
    consolidated: bool
    source: str
    published_at: date | None = None


@dataclass(frozen=True)
class ShareholdingRow:
    ticker: str
    period: str
    category: str           # 'promoter' | 'fii' | 'dii' | 'public' | 'government'
    pct: float
    source: str
    published_at: date | None = None


@dataclass(frozen=True)
class PriceBar:
    ticker: str
    day: date
    open: float
    high: float
    low: float
    close: float
    volume: float
    source: str


@dataclass(frozen=True)
class Filing:
    ticker: str
    doc_id: str
    title: str
    url: str
    published_at: date
    source: str
    grade: str              # A/B/C/D


@runtime_checkable
class FundamentalsSource(Protocol):
    name: str

    def annual_financials(self, ticker: str) -> list[FinancialRow]: ...

    def shareholding(self, ticker: str) -> list[ShareholdingRow]: ...


@runtime_checkable
class MarketDataSource(Protocol):
    name: str

    def ohlcv(self, ticker: str, start: date, end: date) -> list[PriceBar]: ...


@runtime_checkable
class FilingsSource(Protocol):
    name: str

    def filings(self, ticker: str, since: date) -> list[Filing]: ...
