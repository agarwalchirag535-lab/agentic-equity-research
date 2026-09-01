"""Source-agnostic data adapter contracts + ingestion bridge (Law 6)."""

from firm.adapters.base.ingest import ingest_financials, sha256
from firm.adapters.base.interfaces import (
    Filing,
    FilingsSource,
    FinancialRow,
    FundamentalsSource,
    MarketDataSource,
    PriceBar,
    ShareholdingRow,
)

__all__ = [
    "Filing",
    "FilingsSource",
    "FinancialRow",
    "FundamentalsSource",
    "MarketDataSource",
    "PriceBar",
    "ShareholdingRow",
    "ingest_financials",
    "sha256",
]
