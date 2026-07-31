"""A peer set built from the peers' own filings (ADR-0039).

`sector_analyst` was the one roster agent that could never be staffed: it requires `peers`, and nothing
in the codebase ingested a peer. The shortcut — lifting a comparison table off an aggregator — is refused
for two reasons that outlast the convenience, and both are asserted here: the figures would be grade B
where the filing is grade A, and they would be computed to a vendor's definitions rather than to
`core/compute`, so a difference in the table would measure the vendors instead of the companies.
"""

from __future__ import annotations

from datetime import date

from firm.core.pipeline.peers import COMPARABLE, build_peer_set, load_peer_config
from tests.conftest import AS_OF, clean_series, seed_store

_CONFIG = {
    "sector": "chemicals",
    "peers": [{"ticker": "PEERCO", "name": "Peerco Limited", "why": "the other domestic producer"}],
}


def test_a_peer_is_derived_by_the_same_compute_layer_as_the_subject(store):
    seed_store(store, "SUBJECT", clean_series())
    seed_store(store, "PEERCO", clean_series(roic_boost=1.6))

    peers = build_peer_set(store, "SUBJECT", AS_OF, config=_CONFIG)
    assert [p.ticker for p in peers.companies] == ["PEERCO"]

    row = peers.companies[0].row()
    assert set(row) == set(COMPARABLE), "the comparable set is fixed, not whatever the peer happened to have"
    assert row["revenue_cagr"]["value"] is not None
    # the same provenance rules as any other number: fact ids and a grade, never a bare figure
    assert row["revenue_cagr"]["fact_ids"]
    assert row["revenue_cagr"]["grade"] in {"A", "B", "C", "D"}


def test_a_metric_the_peer_does_not_disclose_says_why_rather_than_going_blank(store):
    seed_store(store, "SUBJECT", clean_series())
    seed_store(store, "PEERCO", {"pnl:Sales": [600, 700, 800, 900, 1000, 1050],
                                 "pnl:Net Profit": [60, 70, 80, 90, 100, 105]})

    row = build_peer_set(store, "SUBJECT", AS_OF, config=_CONFIG).companies[0].row()
    assert row["roic_latest"]["value"] is None
    assert row["roic_latest"]["unavailable_because"], "a blank cell reads as a zero; a reason does not"


def test_a_declared_peer_with_no_ingested_filings_is_reported_not_dropped(store):
    """A two-peer table quietly presenting itself as the whole industry is the failure to avoid."""
    seed_store(store, "SUBJECT", clean_series())

    peers = build_peer_set(store, "SUBJECT", AS_OF, config=_CONFIG)
    assert peers.companies == ()
    assert [t for t, _ in peers.missing] == ["PEERCO"]
    assert "discover-filings" in peers.missing[0][1], "the reason should say how to fix it"

    payload = peers.as_payload()
    assert payload["peers_not_available"][0]["ticker"] == "PEERCO"


def test_a_peer_with_too_little_history_is_excluded_with_a_reason(store):
    """A peer row of nulls beside a full subject row reads as a difference between the companies."""
    seed_store(store, "SUBJECT", clean_series())
    seed_store(store, "PEERCO", {"pnl:Sales": [900, 1000], "pnl:Net Profit": [90, 100]},
               periods=("FY25", "FY26"))

    peers = build_peer_set(store, "SUBJECT", AS_OF, config=_CONFIG, min_years=3)
    assert peers.companies == ()
    assert "floor for a comparison" in peers.missing[0][1]


def test_the_payload_states_the_basis_and_why_each_peer_is_in_the_set(store):
    """A comparator set without a stated basis is a guess that looks like rigour."""
    seed_store(store, "SUBJECT", clean_series())
    seed_store(store, "PEERCO", clean_series())

    payload = build_peer_set(store, "SUBJECT", AS_OF, config=_CONFIG).as_payload()
    assert "OWN audited filings" in payload["basis"]
    assert payload["peers"][0]["included_because"] == "the other domestic producer"


def test_the_shipped_peer_config_justifies_every_peer_it_names():
    """`why` is not decoration: it is what lets a reader reject the peer set rather than the conclusion."""
    declared = load_peer_config("ALKYLAMINE")
    assert declared, "config/peers.yaml should carry the worked example"
    for peer in declared["peers"]:
        assert peer.get("ticker") and peer.get("ir_url")
        assert len(peer.get("why", "")) > 40, f"{peer['ticker']} is named with no stated basis"


def test_a_ticker_with_no_declared_peers_yields_an_empty_set_rather_than_an_error(store):
    seed_store(store, "LONELY", clean_series())
    peers = build_peer_set(store, "LONELY", date(2026, 7, 23), config={})
    assert peers.companies == () and peers.missing == ()
    assert peers.as_payload()["peers"] == []
