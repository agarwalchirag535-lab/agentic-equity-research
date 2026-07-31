"""A peer set built the same way the subject is: from each peer's own filings (ADR-0039).

WHY THE OBVIOUS SHORTCUT IS REFUSED
The cheap way to get a peer table is to scrape a comparison widget off an aggregator. It would work
today and it would poison everything downstream, for two reasons that matter more than convenience:

1. **Grade.** Owner directive 1 makes the audited filing the source of record and screener.in a grade-B
   cross-check. A peer figure lifted from an aggregator is grade B at best, and the worst-input rule
   would drag every comparison built on it down with it — so a `sector_analyst` conclusion would rest
   on exactly the secondary sourcing the firm exists to avoid.
2. **Comparability.** An aggregator's "OPM" is its own definition applied to its own normalisation. Ours
   is `core/compute` applied to figures read off the statements with a `(page, line)` locator. Putting
   the two side by side in one table produces a difference that measures the vendors, not the companies.

So a peer is not a special kind of data. A peer is another company run through the identical pipeline —
`discover-filings` against its own IR page, the same PDF walk, the same fact store, the same derivations
— and the comparison is between numbers this firm computed, both times, the same way.

WHY THE PEER SET IS DECLARED AND JUSTIFIED
`config/peers.yaml` requires a `why` for every peer. A peer set assembled without a stated basis is a
guess about what competes with what, and a sector conclusion resting on a guessed comparator set is
worse than no sector conclusion — it looks rigorous. The `why` is published with the comparison.

WHAT A MISSING PEER DOES
It is reported, never dropped. A peer named in the config whose filings are not ingested appears in
`missing` with the reason, so a two-peer table cannot silently present itself as the whole industry.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from firm.core.config import CONFIG_DIR
from firm.core.facts.store import FactStore
from firm.core.pipeline import derive as D
from firm.core.pipeline.derive import DerivedSet

#: The metrics a peer comparison is actually made of. Deliberately short: a wide table invites the reader
#: to hunt for a difference, and these are the ones that separate a business from its competitor rather
#: than describing the same cycle twice.
COMPARABLE: tuple[str, ...] = (
    "revenue_cagr", "opm_latest", "roic_latest", "incremental_roic_3y",
    "cum_cfo_pat", "self_funding_ratio",
)


@dataclass(frozen=True)
class PeerCompany:
    """One peer, with the same derivations the subject got and the same provenance rules."""

    ticker: str
    name: str
    why: str
    derived: DerivedSet

    @property
    def years(self) -> int:
        return self.derived.years

    def row(self) -> dict[str, Any]:
        """The comparable metrics, each with the fact ids and grade behind it."""
        out: dict[str, Any] = {}
        for metric in COMPARABLE:
            derivation = self.derived.get(metric)
            if derivation is None:
                out[metric] = {
                    "value": None,
                    "unavailable_because": ", ".join(self.derived.missing.get(metric, ("no inputs",))),
                }
                continue
            out[metric] = {
                "value": derivation.value,
                "fact_ids": list(derivation.fact_ids),
                "grade": derivation.citation.grade.value,
            }
        return out


@dataclass(frozen=True)
class PeerSet:
    """The peers that could be built, and the ones that could not, with reasons."""

    subject: str
    as_of: date
    sector: str | None = None
    companies: tuple[PeerCompany, ...] = ()
    missing: tuple[tuple[str, str], ...] = ()

    def as_payload(self) -> dict[str, Any]:
        """The shape an agent's brief carries. Peers and refusals in one object, never separated."""
        return {
            "sector": self.sector,
            "basis": ("every figure below is computed by `core/compute` from that peer's OWN audited "
                      "filings, by the identical path used for the subject — so the comparison is "
                      "between like and like, not between two vendors' definitions"),
            "subject": self.subject,
            "peers": [
                {"ticker": p.ticker, "name": p.name, "included_because": p.why,
                 "history_years": p.years, "metrics": p.row()}
                for p in self.companies
            ],
            "peers_not_available": [
                {"ticker": ticker, "reason": reason} for ticker, reason in self.missing
            ],
        }


def load_peer_config(subject: str, path: str | Path | None = None) -> dict[str, Any]:
    """The declared peer set for a ticker, or an empty declaration if none is configured."""
    location = Path(path) if path else CONFIG_DIR / "peers.yaml"
    if not location.exists():
        return {}
    raw = yaml.safe_load(location.read_text()) or {}
    return dict((raw.get("universe") or {}).get(subject) or {})


def build_peer_set(
    store: FactStore,
    subject: str,
    as_of: date,
    *,
    config: Mapping[str, Any] | None = None,
    start_year: int = 2015,
    min_years: int = 3,
) -> PeerSet:
    """Derive the same metric set for every declared peer, from facts already in the store.

    `min_years` is a floor on the comparison, not on the peer: two years of history cannot establish a
    CAGR, and a peer row full of nulls beside a full subject row reads as a difference between the
    companies when it is a difference in what we ingested.
    """
    declared = dict(config if config is not None else load_peer_config(subject))
    entries: Sequence[Mapping[str, Any]] = declared.get("peers") or ()

    companies: list[PeerCompany] = []
    missing: list[tuple[str, str]] = []
    for entry in entries:
        ticker = str(entry["ticker"])
        facts = D.load_company_facts(store, ticker, as_of, start_year=start_year)
        derived = D.derive_metrics(facts)
        if not derived.values:
            missing.append((ticker, (
                "no facts are in the store for this peer as of this date — run `firm discover-filings` "
                "against its IR page, download the reports, then `firm ingest-peer`")))
            continue
        if derived.years < min_years:
            missing.append((ticker, (
                f"only {derived.years}y of history ingested; {min_years}y is the floor for a comparison, "
                "and a peer row of nulls beside a full subject row would read as a real difference")))
            continue
        companies.append(PeerCompany(
            ticker=ticker, name=str(entry.get("name") or ticker),
            why=str(entry.get("why") or "no basis stated in config/peers.yaml"),
            derived=derived,
        ))

    return PeerSet(
        subject=subject, as_of=as_of, sector=declared.get("sector"),
        companies=tuple(companies), missing=tuple(missing),
    )


__all__ = ["COMPARABLE", "PeerCompany", "PeerSet", "build_peer_set", "load_peer_config"]
