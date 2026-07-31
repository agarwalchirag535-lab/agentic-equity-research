"""Shared Phase-2 fixtures: synthetic companies, filings, and scripted agent answers.

Kept here (rather than in each test) so the five acceptance companies in `test_phase2_e2e.py` and the
unit tests exercise the *same* builders — a fixture that drifts from the pipeline it feeds is how a green
suite starts lying. Every company is a plain dict of series, so a test can state exactly the shape of the
statements it wants and nothing is hidden in a helper.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from firm.core.facts.store import Document, FactStore
from firm.core.pipeline.filing import FilingSource

AS_OF = date(2026, 7, 30)
#: The screener snapshot predates the annual report on purpose: it lets a test set an `as_of` between the
#: two and prove the filing is invisible until its own publication date (Law 3).
PUBLISHED = date(2026, 4, 1)
FILING_PUBLISHED = date(2026, 6, 15)

#: A clean-looking annual report: full Schedule III rows, clean CARO answers, notes with figures.
#: The AUDITED statement pages. Kept distinct from the notes page on purpose: `find_statement_row`
#: (ADR-0024) reads balance-sheet metrics only from pages that ARE the balance sheet, because on the real
#: Alkyl Amines filings a document-wide search picked up a cash-flow movement line (negative receivables)
#: and a sentence in the auditor's report. A fixture whose figures live on a notes page does not exercise
#: the path the pipeline actually takes. Note-reference columns ("Trade Receivables 9 118.0") are included
#: so the note-column stripping is exercised too.
def _statement_pages(receivables, inventory, cash, revenue, pbt) -> tuple[str, str]:
    balance_sheet = (
        "Balance Sheet as at March 31, 2026\n"
        "(` in crore)\n"
        f"(a) Inventories 10  {inventory[0]}  {inventory[1]}\n"
        f"(b) (i) Trade Receivables 9  {receivables[0]}  {receivables[1]}\n"
        f"(c) (iii) Cash and Cash Equivalents 11  {cash[0]}  {cash[1]}\n"
        "Total Assets  900.00  800.00\n"
        "Total Equity and Liabilities  900.00  800.00\n"
    )
    profit_and_loss = (
        "Statement of Profit and Loss for the year ended March 31, 2026\n"
        "(` in crore)\n"
        f"Revenue from operations  {revenue[0]}  {revenue[1]}\n"
        f"Total Income  {revenue[0]}  {revenue[1]}\n"
        f"Profit before tax  {pbt[0]}  {pbt[1]}\n"
    )
    return balance_sheet, profit_and_loss


def _ageing_pages(receivables_rows: str, payables_rows: str, cwip_rows: str) -> str:
    """The three Schedule III ageing schedules on one page, in the layout Indian filings actually use.

    These were missing from the fixtures entirely, and their absence was invisible: the filing pages
    carried the schedule *headings* (so the `disclosure_gap` scan was satisfied) with no table beneath
    them. A filing for FY22 or later is legally required to carry all three, so a fixture without them
    was testing a document that could not exist — and it hid the fact that nothing consumed the parser
    (ADR-0039).

    The bucket header is deliberately printed the way the real filings print it, wrapped mid-phrase, so
    the header/first-row boundary logic in `adapters/india/ageing.py` is exercised rather than bypassed.
    """
    return (
        "Notes to the Financial Statements — Schedule III disclosures (` in crore)\n"
        "24 Trade Receivables\n"
        "Particulars Outstanding for following periods from due date of payment as at March 31, 2026\n"
        "Less than\n"
        "6 months\n"
        "6 months-1year 1-2 years 2-3 years More than 3 years Total\n"
        f"{receivables_rows}"
        "25 Trade Payables\n"
        "Particulars Outstanding for following periods from due date of payment as at March 31, 2026\n"
        "Less than 1 year 1-2 years 2-3 years More than 3 years Total\n"
        f"{payables_rows}"
        "26 Ageing of Capital Work in progress as at March 31, 2026\n"
        "Particulars Amounts in capital work-in-progress for a period of\n"
        "Less than 1 year 1-2 years 2-3 years More than 3 years Total\n"
        f"{cwip_rows}"
    )


CLEAN_AR_PAGES: tuple[str, ...] = (
    *_statement_pages(
        ("118.00", "110.00"), ("96.00", "90.00"), ("40.00", "35.00"),
        ("1,050.00", "1,000.00"), ("173.00", "157.00"),
    ),
    (
        "Notes to the Financial Statements (₹ in crore)\n"
        "Note 1: Corporate Information\n"
        "Note 2: Significant Accounting Policies\n"
        "Note 9: Trade Receivables 118.0 110.0\n"
        "Note 10: Inventories 96.0 90.0\n"
        "Note 11: Cash and cash equivalents 40.0 35.0\n"
        "Revenue from operations 1,050.0 1,000.0\n"
        "Note 21: Other Income 12.0 10.0\n"
        "Note 24: Property, Plant and Equipment 700.0 650.0\n"
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
        "Undisclosed income: none surrendered or disclosed.\n"
        "Crypto currency: the Company has not traded in crypto currency.\n"
        "Capital work-in-progress ageing schedule as at 31 March 2026\n"
        "Trade Receivables ageing schedule as at 31 March 2026\n"
        "Trade Payables ageing schedule as at 31 March 2026\n"
        "Loans or advances to promoters: NIL\n"
        "Title deeds of immovable properties are held in the name of the Company.\n"
        "Current Ratio 1.85 1.72\n"
    ),
    # Clean tables: a short receivable tail, nothing disputed, no suspended capex. Both totals tie to the
    # balance sheet (receivables 118.00, CWIP 22.00), so `ageing_reconciliation` passes on real agreement
    # rather than on an absence.
    _ageing_pages(
        receivables_rows=(
            "i) Undisputed Trade receivables - considered good  112.00  4.00  1.50  0.50  -    118.00\n"
            "ii) Disputed Trade Receivables - considered good  -    -    -    -    -    -\n"
            "Total  112.00  4.00  1.50  0.50  -    118.00\n"
        ),
        payables_rows=(
            "i) Undisputed dues of micro and small enterprises  8.00  -    -    -    8.00\n"
            "ii) Undisputed dues of creditors other than micro and small  60.00  2.00  -    -    62.00\n"
            "Total  68.00  2.00  -    -    70.00\n"
        ),
        cwip_rows=(
            "Projects in progress  19.00  3.00  -    -    22.00\n"
            "Projects temporarily suspended  -    -    -    -    -\n"
            "Total  19.00  3.00  -    -    22.00\n"
        ),
    ),
)

#: The same filing shape for a company whose receivables are running away from revenue (+110% vs +5%) —
#: the channel-stuffing / fictitious-sales signature the universal SPEC §5 check exists to catch.
FRAUD_AR_PAGES: tuple[str, ...] = (
    *_statement_pages(
        ("210.00", "100.00"), ("140.00", "90.00"), ("30.00", "28.00"),
        ("1,050.00", "1,000.00"), ("186.00", "166.00"),
    ),
    (
        "Notes to the Financial Statements (₹ in crore)\n"
        "Note 1: Corporate Information\n"
        "Note 9: Trade Receivables 210.0 100.0\n"
        "Note 10: Inventories 140.0 90.0\n"
        "Note 11: Cash and cash equivalents 30.0 28.0\n"
        "Revenue from operations 1,050.0 1,000.0\n"
        "Note 21: Other Income 40.0 12.0\n"
        "Note 30: RELATED PARTY DISCLOSURES\n"
    ),
    (
        "INDEPENDENT AUDITOR'S REPORT\n"
        "Key Audit Matters: revenue recognition and recoverability of trade receivables.\n"
        "Related party: certain transactions with promoter-controlled entities.\n"
        "Contingent Liabilities: corporate guarantees given on behalf of related parties.\n"
        "Annexure A — CARO 2020\n"
        "(ix) The Company has made default in repayment of loans from banks during the year.\n"
        "(xi) No fraud has been noticed or reported.\n"
        "Trade Receivables ageing schedule as at 31 March 2026\n"
        "Current Ratio 0.92 1.10\n"
    ),
    # The same fraud pattern, seen in the ageing table rather than in the stock-flow ratio: a quarter of
    # the book is past a year and the company has itself disputed ₹8cr of it. Capital work in progress is
    # left clean on purpose — a company can be stuffing the channel without touching its capex.
    _ageing_pages(
        receivables_rows=(
            "i) Undisputed Trade receivables - considered good  122.00  30.00  30.00  15.00  5.00  202.00\n"
            "ii) Disputed Trade Receivables - considered good  -    2.00  3.00  2.00  1.00  8.00\n"
            "Total  122.00  32.00  33.00  17.00  6.00  210.00\n"
        ),
        payables_rows=(
            "i) Undisputed dues of micro and small enterprises  12.00  -    -    -    12.00\n"
            "ii) Undisputed dues of creditors other than micro and small  74.00  4.00  -    -    78.00\n"
            "Total  86.00  4.00  -    -    90.00\n"
        ),
        cwip_rows=(
            "Projects in progress  200.00  60.00  -    -    260.00\n"
            "Projects temporarily suspended  -    -    -    -    -\n"
            "Total  200.00  60.00  -    -    260.00\n"
        ),
    ),
)


def clean_series(roic_boost: float = 1.0) -> dict[str, list[float]]:
    """A self-funding manufacturer: profit converts to cash, CWIP commissions, margins hold.

    `roic_boost` shrinks the invested-capital base (reserves) without touching the P&L, which is how a
    test asks for "the same business but at a higher return on capital" — the input the §6.3 feasibility
    gate actually keys off.
    """
    return {
        "pnl:Sales": [600, 700, 800, 900, 1000, 1050],
        "pnl:Net Profit": [60, 72, 85, 100, 118, 130],
        "pnl:Operating Profit": [110, 130, 150, 175, 205, 220],
        "pnl:Depreciation": [20, 22, 24, 26, 28, 30],
        "pnl:Interest": [8, 8, 7, 6, 5, 4],
        "pnl:Tax %": [25, 25, 25, 25, 25, 25],
        "pnl:Other Income": [6, 7, 8, 9, 10, 12],
        "pnl:Profit before tax": [80, 96, 113, 133, 157, 173],
        # Expenses = Sales - Operating Profit, so the margin questions have a cost series to compare.
        "pnl:Expenses": [490, 570, 650, 725, 795, 830],
        # Share count held flat, so EPS tracks PAT exactly: this company did NOT buy its growth with
        # equity, and `dilution_drag` should come out at ~0 (ADR-0022 capital_allocation.capital_dilution).
        "pnl:EPS in Rs": [6.0, 7.2, 8.5, 10.0, 11.8, 13.0],
        "pnl:Dividend Payout %": [20, 20, 20, 20, 20, 20],
        "cashflow:Cash from Operating Activity": [66, 80, 95, 112, 130, 145],
        "cashflow:Free Cash Flow": [40, 50, 60, 70, 85, 95],
        # Investing outflow smaller than cumulative CFO, so `self_funding_ratio` > 1 and the debt
        # questions resolve to "the programme was paid for out of operating cash".
        "cashflow:Cash from Investing Activity": [-40, -45, -50, -60, -100, -110],
        "balance_sheet:Borrowings": [80, 75, 70, 60, 50, 40],
        "balance_sheet:Equity Capital": [10, 10, 10, 10, 10, 10],
        "balance_sheet:Reserves": [v / roic_boost for v in (300, 350, 410, 480, 560, 650)],
        "balance_sheet:CWIP": [20, 22, 18, 25, 20, 22],
        "balance_sheet:Fixed Assets": [420, 450, 480, 520, 600, 700],
        "balance_sheet:Total Assets": [520, 570, 630, 700, 800, 900],
    }


def with_working_capital(series: dict[str, list[float]]) -> dict[str, list[float]]:
    """Add the three working-capital legs to a series (ADR-0038).

    Deliberately NOT folded into `clean_series`: several tests use that fixture precisely because it is
    incomplete — one asserts no business model can be detected while inventory is unknown, another that an
    absent row is not stored. Enriching the shared fixture would have made those tests pass for the wrong
    reason. A company that discloses its whole cycle is a different fixture, so it gets its own.

    Receivables and inventory grow slower than sales and payables track them: a clean, shortening cycle.
    """
    return series | {
        "balance_sheet:Trade Receivables": [90, 100, 110, 120, 130, 133],
        "balance_sheet:Inventories": [60, 68, 76, 84, 92, 95],
        "balance_sheet:Trade Payables": [50, 57, 64, 71, 78, 81],
        "balance_sheet:Cash Equivalents": [30, 38, 47, 58, 70, 85],
    }


def fraud_series() -> dict[str, list[float]]:
    """Profit that never becomes cash: ΣCFO/ΣPAT well under the floor, receivables absorbing the gap.

    Modelled on the pattern the check library was back-tested against (docs/STATUS.md §6): reported profit
    rising while operating cash flow stalls, with the difference parked in receivables.
    """
    return {
        "pnl:Sales": [600, 700, 800, 900, 1000, 1050],
        "pnl:Net Profit": [60, 75, 92, 110, 130, 150],
        "pnl:Operating Profit": [110, 135, 160, 190, 220, 250],
        "pnl:Depreciation": [20, 22, 24, 26, 28, 30],
        "pnl:Interest": [12, 14, 16, 20, 26, 34],
        "pnl:Tax %": [25, 25, 25, 25, 25, 25],
        "pnl:Other Income": [8, 12, 18, 25, 32, 40],
        "pnl:Profit before tax": [78, 97, 120, 145, 166, 186],
        "pnl:Expenses": [490, 565, 640, 710, 780, 800],
        # PAT compounds 20%/yr while EPS compounds ~12%: the share count rose because the cash gap had to
        # be plugged from somewhere. `dilution_drag` should be materially positive — the wedge shareholders
        # funded and did not keep. This is the half of the fraud pattern a cash-only test cannot see.
        "pnl:EPS in Rs": [6.0, 7.0, 8.0, 9.0, 9.8, 10.5],
        "pnl:Dividend Payout %": [10, 10, 8, 5, 5, 0],
        "cashflow:Cash from Operating Activity": [30, 28, 25, 20, 15, 10],
        "cashflow:Free Cash Flow": [-10, -20, -30, -45, -60, -80],
        # Operating cash covers almost none of a large investing programme: the shortfall is exactly what
        # the rising borrowings above are funding, which is what `debt_what_it_funded` should surface.
        "cashflow:Cash from Investing Activity": [-60, -80, -110, -140, -170, -200],
        "balance_sheet:Borrowings": [100, 130, 170, 230, 300, 400],
        "balance_sheet:Equity Capital": [10, 10, 10, 10, 10, 10],
        "balance_sheet:Reserves": [300, 360, 430, 510, 600, 700],
        "balance_sheet:CWIP": [40, 70, 110, 160, 210, 260],
        "balance_sheet:Fixed Assets": [420, 450, 470, 490, 510, 530],
        "balance_sheet:Total Assets": [600, 700, 830, 1000, 1200, 1450],
    }


DEFAULT_PERIODS = ("FY21", "FY22", "FY23", "FY24", "FY25", "FY26")


def seed_store(
    store: FactStore,
    ticker: str,
    series: dict[str, list[float]],
    *,
    periods: tuple[str, ...] = DEFAULT_PERIODS,
    doc_id: str | None = None,
    grade: str = "B",
    published_at: date = PUBLISHED,
) -> str:
    """Load a synthetic company into the fact store as a screener-grade (B) snapshot."""
    doc = doc_id or f"screener-{ticker}"
    store.add_document(Document(
        doc_id=doc, source_url=f"https://example.test/{ticker}", sha256="0" * 8,
        published_at=published_at, fetched_at=published_at, grade=grade,
        extractor_version="screener-parser@1.0.0",
    ))
    for metric, values in series.items():
        for period, value in zip(periods, values):
            store.add_fact(
                fact_id=f"{doc}:{metric}:{period}", doc_id=doc, ticker=ticker, metric=metric,
                period=period, value=float(value), unit="INR_cr", locator=f"{metric} table",
            )
    return doc


def filing_for(ticker: str, pages: tuple[str, ...] = CLEAN_AR_PAGES) -> FilingSource:
    return FilingSource(
        doc_id=f"AR-{ticker}-FY26", source_url=f"https://example.test/{ticker}/ar-fy26.pdf",
        published_at=FILING_PUBLISHED, pages=pages, period="FY26", prior_period="FY25",
        grade="A", sha256="a" * 8,
    )


def cited_claim(
    text: str, fact_id: str, *, kind: str = "observation", grade: str = "B", confidence: float = 0.75
) -> dict:
    """A claim citing one derived metric — the only kind of number an agent is allowed to reference."""
    return {
        "text": text, "kind": kind,
        "citations": [{
            "fact_id": fact_id, "doc_id": "derivation", "locator": "inputs listed in §4",
            "published_at": PUBLISHED.isoformat(), "extractor_version": "core.compute@1.0.0",
            "grade": grade,
        }],
        "confidence": {
            "value": confidence, "evidence_count": 1, "lowest_grade_relied_on": grade,
            "rationale": f"one computed metric at grade {grade}",
        },
    }


def agent_answer(
    agent: str,
    ticker: str,
    extra: dict,
    *,
    as_of: date = AS_OF,
    narrative: str = (
        "The computed table carries the figures; this note interprets them without restating any "
        "number. Cash conversion, returns on capital and the checks that could not run are the three "
        "things a reader should weigh."
    ),
    observations: list[dict] | None = None,
    inferences: list[dict] | None = None,
    open_questions: list[str] | None = None,
    disconfirming: str = (
        "Searched for a cash-conversion break, a CWIP block that never commissions, other-income "
        "dependence and a receivables run-up; recorded what the filed figures show either way."
    ),
    version: str = "1.0.0",
) -> str:
    """A schema-valid agent answer as raw JSON — what a provider would return (Law 4)."""
    body = {
        "agent": agent, "agent_version": version, "ticker": ticker, "as_of": as_of.isoformat(),
        "observations": observations if observations is not None else [
            cited_claim("Cumulative cash conversion sits above the policy floor "
                        "[fact:derived:cum_cfo_pat].", "derived:cum_cfo_pat")],
        "inferences": inferences if inferences is not None else [
            cited_claim("Reported profit has been converting to cash across the cycle "
                        "[fact:derived:cfo_pat_latest].", "derived:cfo_pat_latest", kind="inference",
                        confidence=0.7)],
        "speculations": [],
        "open_questions": open_questions if open_questions is not None else [
            "Receivables ageing beyond the longest disclosed bucket is not broken out by counterparty."],
        "disconfirming_search": disconfirming,
        "narrative": narrative,
    }
    body.update(extra)
    return json.dumps(body)


def clean_answers(ticker: str, **overrides: dict) -> dict[str, str]:
    """Scripted answers for the three Phase-2 agents, all law-abiding (no authored numbers)."""
    base = {
        "business_analyst": {
            "what_it_does": "Manufactures specialty amines sold to pharmaceutical and agrochemical "
                            "formulators; revenue is per-tonne contract pricing, not brand.",
            "moat": "Process know-how plus customer-site regulatory filings; switching costs are real "
                    "but not permanent.",
            "customer_concentration": None,
            "national_relevance": True,
        },
        "financial_statement_analyst": {
            "incremental_roic": None, "cfo_to_ebitda": None, "fcf_to_pat": None,
            "working_capital_days": None,
        },
        "forensic_accountant": {"verdict": "PASS", "flags": [], "veto": False},
    }
    for agent, patch in overrides.items():
        base[agent] = {**base[agent], **patch}
    return {agent: agent_answer(agent, ticker, extra) for agent, extra in base.items()}


@pytest.fixture()
def store() -> FactStore:
    fs = FactStore(":memory:")
    yield fs
    fs.close()
