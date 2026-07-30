"""Ingestion: immutable bronze archive + resumable backfill (Law 7, ADR-0018)."""

from firm.core.ingest.bronze import (
    BackfillResult,
    BronzeRecord,
    BronzeStore,
    backfill_filings,
)

__all__ = ["BackfillResult", "BronzeRecord", "BronzeStore", "backfill_filings"]
