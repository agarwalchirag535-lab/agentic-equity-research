"""ADR-0050: two defects the real Symphony FY13-FY17 ingest surfaced.

1. `dilution_drag` compared EPS endpoints across a 1:1 bonus — a 14pp "wedge shareholders funded and
   did not keep" on shareholders who kept every share pro-rata and funded nothing.
2. Reading-path facts had no cross-document quarantine, and the value-only classifier would have
   labelled a verified re-presentation (FY13 printing traded-goods purchases inside materials) as
   the firm's own extraction error.
"""

from __future__ import annotations

from datetime import date

import pytest

from firm.core.facts.store import Document, FactStore
from firm.core.ingest.filings import quarantine_store_contradictions
from firm.core.pipeline import derive as D

RECON = {"rounding_abs_cr": 0.01, "rounding_rel": 0.0, "extraction_error_rel": 0.25}


def _store_two_docs(metric, period, earlier_value, later_value, *, verified=(True, True)):
    store = FactStore(":memory:")
    for i, (value, is_verified) in enumerate(zip((earlier_value, later_value), verified)):
        doc = f"AR-{i}"
        store.add_document(Document(
            doc_id=doc, source_url="u", sha256="", published_at=date(2014 + i, 8, 31),
            fetched_at=date(2014 + i, 8, 31), grade="A",
            extractor_version="llm-read@1.0.0+verified" if is_verified else "walker@1"))
        store.add_fact(fact_id=f"{doc}:{metric}:{period}", doc_id=doc, ticker="T", metric=metric,
                       period=period, value=value, unit="INR_cr", locator="p.1")
    return store


# ---- the share-base guard -------------------------------------------------------------------------

BONUS_ROWS = {
    (D.SALES, "FY12"): 313.47, (D.PAT, "FY12"): 53.10, (D.EPS, "FY12"): 15.18,
    (D.EQUITY_CAPITAL, "FY12"): 6.9957,
    (D.SALES, "FY18"): 764.75, (D.PAT, "FY18"): 192.55, (D.EPS, "FY18"): 26.28,
    (D.EQUITY_CAPITAL, "FY18"): 13.9914,   # the 1:1 bonus: capital doubled, nobody was diluted
}


def _facts(rows):
    store = FactStore(":memory:")
    doc, pub = "AR-X", date(2018, 8, 31)
    store.add_document(Document(doc_id=doc, source_url="u", sha256="", published_at=pub,
                                fetched_at=pub, grade="A", extractor_version="t@1"))
    for (metric, period), value in rows.items():
        store.add_fact(fact_id=f"{doc}:{metric}:{period}", doc_id=doc, ticker="T", metric=metric,
                       period=period, value=value, unit="INR_cr", locator="p.1")
    return D.load_company_facts(store, "T", date(2018, 12, 31), start_year=2012)


def test_a_bonus_issue_is_not_published_as_dilution():
    derived = D.derive_metrics(_facts(BONUS_ROWS),
                               forensic={"dilution_drag_max_capital_change": 0.02})
    assert derived.get("dilution_drag") is None
    reason = derived.missing["dilution_drag"][0]
    assert "2.00x" in reason and "bonus" in reason and "corporate-action" in reason
    # the CAGRs themselves are facts as filed and still derive
    assert derived.get("pat_cagr") is not None and derived.get("eps_cagr") is not None


def test_a_stable_share_base_keeps_the_wedge():
    rows = dict(BONUS_ROWS)
    rows[(D.EQUITY_CAPITAL, "FY18")] = 6.9957   # capital flat: EPS endpoints are comparable
    derived = D.derive_metrics(_facts(rows), forensic={"dilution_drag_max_capital_change": 0.02})
    d = derived.get("dilution_drag")
    assert d is not None and d.value == pytest.approx(
        derived.value("pat_cagr") - derived.value("eps_cagr"), abs=1e-9)


def test_an_undisclosed_share_base_keeps_the_status_quo():
    rows = {k: v for k, v in BONUS_ROWS.items() if k[0] != D.EQUITY_CAPITAL}
    derived = D.derive_metrics(_facts(rows), forensic={"dilution_drag_max_capital_change": 0.02})
    # comparability cannot be checked, which is the firm's gap, not the company's — status quo holds
    assert derived.get("dilution_drag") is not None


# ---- store-driven contradiction quarantine --------------------------------------------------------

def test_a_verified_re_presentation_is_named_honestly_and_removed():
    # Symphony FY13 materials: 165.88cr as printed by the FY13 filing (purchases lumped in) vs
    # 41.15cr as the FY14 filing's split comparative — a 4x gap no restatement band covers.
    store = _store_two_docs("pnl:Cost of Materials Consumed", "FY13", 165.88, 41.15)
    records = quarantine_store_contradictions(store, "T", date(2018, 12, 31), RECON)
    assert len(records) == 1 and records[0].kind == "re_presented"
    assert store.query_fact("T", "pnl:Cost of Materials Consumed", "FY13",
                            as_of=date(2018, 12, 31)) is None


def test_an_unverified_side_keeps_the_extraction_error_confession():
    store = _store_two_docs("balance_sheet:Inventories", "FY21", 0.07, 121.90,
                            verified=(False, True))
    records = quarantine_store_contradictions(store, "T", date(2018, 12, 31), RECON)
    assert len(records) == 1 and records[0].kind == "extraction_error"


def test_a_mere_restatement_is_left_alone():
    store = _store_two_docs("pnl:Sales", "FY15", 578.89, 525.87)   # 9.2% — restated, not quarantined
    records = quarantine_store_contradictions(store, "T", date(2018, 12, 31), RECON)
    assert records == []
    assert store.query_fact("T", "pnl:Sales", "FY15", as_of=date(2018, 12, 31)) is not None


def test_law_3_a_future_filings_contradiction_does_not_exist_yet():
    store = _store_two_docs("pnl:Sales", "FY15", 578.89, 100.00)   # later doc published 2015-08-31
    records = quarantine_store_contradictions(store, "T", date(2014, 12, 31), RECON)
    assert records == []
