"""End-to-end: the full primary-source chain composes (offline, no network).

Proves the pieces built for ADR-0015/0017/0018 actually fit together:

  BSE archive fixture → Filing rows (exchange dissemination dates, Law 3)
    → bronze backfill (immutable, content-addressed, resumable)
      → robust extraction (OCR fallback for an image-only filing)
        → provenance-locked figures (page/line locators, Law 2)
          → notes-walk (enumerate → disposition → 100% coverage gate) + Schedule III + CARO
            → business-model detection → playbook selection
              → deterministic forensic screen

Two companies are run through it: a clean manufacturer (must PASS) and a manipulated one (must flag),
so the chain is shown to discriminate rather than merely execute.
"""

import json
from datetime import date
from pathlib import Path

from firm.adapters.base.extract import extract_document
from firm.adapters.base.sourcing import assess_sourcing
from firm.adapters.base.tables import find_row
from firm.adapters.india.exchange import parse_annual_reports
from firm.adapters.india.filings import disclosure_gaps, forensic_sections
from firm.adapters.india.notes import (
    NoteDisposition,
    caro_candidate_flags,
    coverage,
    enumerate_notes,
    parse_caro_clauses,
    scan_schedule_iii,
    schedule_iii_gaps,
)
from firm.core.compute import (
    BusinessModel,
    ForensicMetrics,
    ForensicVerdict,
    SectorClass,
    StatementShape,
    build_playbook,
    detect_models,
    forensic_screen,
    stock_flow_divergence,
)
from firm.core.config import (
    forensic_thresholds,
    model_detection_thresholds,
    model_playbooks,
    universal_forensic_thresholds,
)
from firm.core.ingest.bronze import BronzeStore, backfill_filings

FIXTURES = Path(__file__).resolve().parent / "fixtures"
AS_OF = date(2026, 7, 30)

# A synthetic annual-report page set for a MANUFACTURER, in the layout real Indian ARs use.
AR_PAGES_CLEAN = [
    (
        "ABC CHEMICALS LIMITED — Notes to the Financial Statements (₹ in crore)\n"
        "Note 1: Corporate Information\n"
        "Note 2: Significant Accounting Policies\n"
        "Note 9: Trade Receivables 118.0 110.0\n"
        "Note 10: Inventories 96.0 90.0\n"
        "Revenue from operations 1,050.0 1,000.0\n"
        "Note 29: CONTINGENT LIABILITIES AND COMMITMENTS\n"
        "Note 30: RELATED PARTY DISCLOSURES\n"
    ),
    (
        "INDEPENDENT AUDITOR'S REPORT\n"
        "Opinion: the financial statements give a true and fair view.\n"
        "Key Audit Matters: Litigation and contingencies.\n"
        "Related party: transactions are at arm's length.\n"
        "Contingent Liabilities: claims not acknowledged as debt.\n"
        "Annexure B — Companies (Auditor's Report) Order, 2020\n"
        "(i) The Company has maintained proper records of Property, Plant and Equipment.\n"
        "(ii) Physical verification of inventory was conducted; no material discrepancies were noticed.\n"
        "(xi) No fraud by the Company has been noticed or reported during the year.\n"
        "Relationship with struck off companies: NIL.\n"
        "Details of Benami property: no proceedings initiated.\n"
        "Wilful defaulter: not declared.\n"
        "Trade Receivables ageing schedule as at 31 March 2026\n"
        "Current Ratio 1.85 1.72\n"
    ),
]

# Same company shape, but receivables exploding vs revenue and an adverse CARO clause.
AR_PAGES_DIRTY = [
    (
        "XYZ TRADING LIMITED — Notes to the Financial Statements (₹ in crore)\n"
        "Note 1: Corporate Information\n"
        "Note 9: Trade Receivables 210.0 100.0\n"
        "Note 10: Inventories 92.0 90.0\n"
        "Revenue from operations 1,050.0 1,000.0\n"
        "Note 30: RELATED PARTY DISCLOSURES\n"
    ),
    (
        "INDEPENDENT AUDITOR'S REPORT\n"
        "Key Audit Matters: revenue recognition.\n"
        "Related party: certain transactions with promoter entities.\n"
        "Annexure A — CARO 2020\n"
        "(ix) The Company has made default in repayment of loans from banks during the year.\n"
        "(xi) No fraud has been noticed or reported.\n"
    ),
]


def _pdf_bytes(tag: str) -> bytes:
    return f"%PDF-1.7 fake payload {tag}".encode()


def test_full_chain_clean_manufacturer_passes(tmp_path):
    # ---- 1. archive: real BSE annual-report fixture -> dated Filing rows -----------------------
    payload = json.loads((FIXTURES / "bse_annual_reports_reliance.json").read_text())
    filings = parse_annual_reports(payload)
    assert filings and all(f.grade == "A" for f in filings)
    latest = max(filings, key=lambda f: f.published_at)
    assert latest.published_at <= AS_OF                       # point-in-time honest (Law 3)

    # primary-first policy: an audited AR satisfies a grade-A requirement
    assert assess_sourcing([latest], required_grade="A").secondary_only is False

    # ---- 2. bronze: immutable, content-addressed, resumable ------------------------------------
    store = BronzeStore(tmp_path / "bronze")
    res = backfill_filings(store, [latest], lambda url: _pdf_bytes("clean"), fetched_at=AS_OF)
    assert res.complete and len(res.archived) == 1
    record = res.archived[0]
    assert store.read_payload(record) == _pdf_bytes("clean")
    # re-run resumes without refetching
    again = backfill_filings(store, [latest], lambda url: (_ for _ in ()).throw(AssertionError("refetched!")),
                             fetched_at=AS_OF)
    assert again.skipped_existing == [latest.doc_id]

    # ---- 3. extraction: text layer sufficient -> no OCR needed ---------------------------------
    extracted = extract_document(
        b"", text_layer_fn=lambda _: AR_PAGES_CLEAN, min_chars_per_page=100,
    )
    assert extracted.complete and extracted.method == "text_layer"
    pages = extracted.pages

    # ---- 4. provenance-locked figures ----------------------------------------------------------
    recv = find_row(pages, ["trade receivables"], exclude=["ageing"])
    rev = find_row(pages, ["revenue from operations"])
    inv = find_row(pages, ["inventories"])
    assert recv is not None and rev is not None and inv is not None
    assert recv.locator == "p.1 l.4" and recv.unit_hint == "INR_cr"   # bound to source (Law 2)
    recv_curr, recv_prior = recv.values[0], recv.values[1]
    rev_curr, rev_prior = rev.values[0], rev.values[1]
    inv_curr, inv_prior = inv.values[0], inv.values[1]

    # ---- 5. notes-walk: enumerate -> disposition -> coverage gate ------------------------------
    notes = enumerate_notes(pages)
    numbers = {n.number for n in notes}
    assert {1, 2, 9, 10, 29, 30} <= numbers
    cov, missing = coverage(notes, [NoteDisposition(n.label, "clean", "reviewed") for n in notes])
    assert cov == 1.0 and missing == []                              # publishable

    # mandated disclosures present -> no gap
    sections = forensic_sections("\n".join(pages))
    assert disclosure_gaps(sections) == ([], False)
    sched = scan_schedule_iii(pages)
    sched_missing, sched_flag = schedule_iii_gaps(sched)
    assert "benami_property" not in sched_missing and "struck_off_companies" not in sched_missing

    # CARO: standard clean answers must NOT flag
    caro = parse_caro_clauses("\n".join(pages))
    assert set(caro) >= {"i", "ii", "xi"} and caro_candidate_flags(caro) == []

    # ---- 6. model detection -> playbook --------------------------------------------------------
    shape = StatementShape(inventory_to_assets=0.12, ppe_to_assets=0.45, gross_margin=0.32)
    models = detect_models(shape, model_detection_thresholds())
    assert models == [BusinessModel.MANUFACTURER]
    pb = build_playbook(models, model_playbooks())
    assert pb.runs("receivables_divergent") and not pb.runs("gnpa_drift")

    # ---- 7. screen: only playbook-selected checks feed the verdict -----------------------------
    ut = universal_forensic_thresholds()
    _, _, recv_flag = stock_flow_divergence(recv_curr, recv_prior, rev_curr, rev_prior,
                                            ut["receivables_flow_gap"])
    _, _, inv_flag = stock_flow_divergence(inv_curr, inv_prior, rev_curr, rev_prior,
                                           ut["inventory_flow_gap"])
    verdict = forensic_screen(
        SectorClass.NON_FINANCIAL,
        ForensicMetrics(
            cumulative_cfo_pat=1.15,
            receivables_divergent=recv_flag and pb.runs("receivables_divergent"),
            inventory_divergent=inv_flag and pb.runs("inventory_divergent"),
            disclosure_gap=sched_flag and False,   # gaps here are the optional rows only
        ),
        forensic_thresholds(),
    )
    assert verdict.verdict is ForensicVerdict.PASS and verdict.flags == []


def test_full_chain_flags_manipulated_company(tmp_path):
    """Same chain, worse company: receivables +110% on +5% revenue, and an adverse CARO clause."""
    # image-only filing -> OCR fallback recovers it (and the chain continues)
    class _Ocr:
        name = "stub"

        def pages_to_text(self, pdf_bytes: bytes) -> list[str]:
            return AR_PAGES_DIRTY

    extracted = extract_document(
        b"", text_layer_fn=lambda _: ["", ""], ocr_backend=_Ocr(), min_chars_per_page=100,
    )
    assert extracted.complete and extracted.method == "ocr"     # recovered, not silently blank
    pages = extracted.pages

    recv = find_row(pages, ["trade receivables"])
    rev = find_row(pages, ["revenue from operations"])
    ut = universal_forensic_thresholds()
    rg, fg, recv_flag = stock_flow_divergence(recv.values[0], recv.values[1],
                                              rev.values[0], rev.values[1],
                                              ut["receivables_flow_gap"])
    assert rg > 1.0 and fg < 0.10 and recv_flag is True         # the channel-stuffing tell

    # mandated disclosure missing -> gap flagged (never a silent blank)
    sections = forensic_sections("\n".join(pages))
    missing, gap_flag = disclosure_gaps(sections)
    assert gap_flag is True and "contingent_liabilities" in missing

    # Schedule III rows absent entirely -> flagged
    sched_missing, sched_flag = schedule_iii_gaps(scan_schedule_iii(pages))
    assert sched_flag is True and "benami_property" in sched_missing

    # adverse CARO clause surfaces for the forensic agent (triage, with the clause quoted)
    caro = parse_caro_clauses("\n".join(pages))
    hits = dict(caro_candidate_flags(caro))
    assert hits.get("ix") == "default in repayment"
    assert "xi" not in hits                                     # clean fraud answer still ignored

    # trader shape -> trader playbook -> revenue_inflation is in scope
    models = detect_models(
        StatementShape(gross_margin=0.02, revenue_to_assets=3.5), model_detection_thresholds()
    )
    assert models == [BusinessModel.TRADER]
    pb = build_playbook(models, model_playbooks())
    assert pb.runs("revenue_inflation") and pb.runs("receivables_divergent")
    # inventory_divergent is UNIVERSAL since the PC Jeweller run (a trader holds inventory too);
    # only models that legitimately hold none (LENDER/BANK/SERVICES_IT) suppress it.
    assert pb.runs("inventory_divergent")

    verdict = forensic_screen(
        SectorClass.NON_FINANCIAL,
        ForensicMetrics(
            receivables_divergent=recv_flag and pb.runs("receivables_divergent"),
            revenue_inflation=pb.runs("revenue_inflation"),
            disclosure_gap=gap_flag or sched_flag,
        ),
        forensic_thresholds(),
    )
    names = {f.name for f in verdict.flags}
    assert {"receivables_divergent", "revenue_inflation", "disclosure_gap"} == names
    assert verdict.verdict is ForensicVerdict.HARD_FAIL         # two HIGH flags
    assert verdict.hard_fail is True
