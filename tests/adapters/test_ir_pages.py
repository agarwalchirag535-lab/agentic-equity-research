"""Discovering annual reports on any listed company's IR page (ADR-0026).

The behaviour that matters is what gets REJECTED: the wrong document type, an undateable file, and above all
an upload date that cannot credibly be a publication date.
"""

from __future__ import annotations

from datetime import date

from firm.adapters.india.ir_pages import discover_filings

BASE = "https://example-chem.com/wp-content/uploads"


def page(*links: str) -> str:
    return "".join(f'<a href="{href}">report</a>' for href in links)


def test_recognises_annual_reports_and_reads_the_fiscal_year_they_cover():
    found = discover_filings(page(
        f"{BASE}/2026/06/Annual-Report-FY-2025-26.pdf",
        f"{BASE}/2023/06/Annual-Report-FY-2022-2023.pdf",
    ), "TESTCO")

    assert [c.period for c in found] == ["FY26", "FY23"]          # newest fiscal year first
    assert found[0].prior_period == "FY25"
    assert found[0].suggested_file == "TESTCO-AR-FY26.pdf"


def test_an_upload_month_inside_the_statutory_window_is_treated_as_evidence():
    """FY26 closes 31 March 2026 and the AGM deadline is 30 September; a June upload is the real thing."""
    found = discover_filings(page(f"{BASE}/2026/06/Annual-Report-FY-2025-26.pdf"), "TESTCO")
    assert found[0].published_at == date(2026, 6, 1)
    assert found[0].published_at_basis == "upload-path"


def test_a_bulk_reupload_falls_back_to_the_statutory_deadline():
    """On the real Alkyl Amines site the FY17-FY21 reports all live under /2022/03/ — a site migration.

    Believing that URL would date the FY17 report five years late and tell a historical replay it did not
    exist until 2022, silently deleting five years of point-in-time evidence.
    """
    found = discover_filings(page(f"{BASE}/2022/03/Annual-Report-FY-2016-17_compressed.pdf"), "TESTCO")
    assert found[0].period == "FY17"
    assert found[0].published_at == date(2017, 9, 30)
    assert found[0].published_at_basis == "statutory-proxy"


def test_a_late_filer_within_the_grace_quarter_is_still_believed():
    found = discover_filings(page(f"{BASE}/2025/11/Annual-Report-FY-2024-25.pdf"), "TESTCO")
    assert found[0].published_at == date(2025, 11, 1)
    assert found[0].published_at_basis == "upload-path"


def test_the_annual_return_is_not_an_annual_report():
    """MGT-7 is a statutory filing, not the financial report — matching it would pollute the manifest."""
    assert discover_filings(page(f"{BASE}/2022/03/Annual-Return-FY-2020-21-1.pdf"), "TESTCO") == []
    assert discover_filings(page(f"{BASE}/2024/06/Annual-Secretarial-Report-2023-24.pdf"), "TESTCO") == []


def test_a_report_with_no_readable_fiscal_year_is_dropped_not_guessed():
    """A PDF that cannot be placed in a point-in-time series is worse than absent."""
    assert discover_filings(page(f"{BASE}/2024/06/Annual-Report-latest.pdf"), "TESTCO") == []


def test_one_entry_per_year_preferring_the_evidenced_date():
    found = discover_filings(page(
        f"{BASE}/2022/03/Annual-Report-FY-2021-2022.pdf",     # migration copy
        f"{BASE}/2022/07/Annual-Report-FY-2021-2022.pdf",     # the real upload
    ), "TESTCO")
    assert len(found) == 1
    assert found[0].published_at_basis == "upload-path"
    assert found[0].published_at == date(2022, 7, 1)


def test_quarterly_and_presentation_pdfs_are_ignored():
    assert discover_filings(page(
        f"{BASE}/2025/08/Results-2025-2026-q2.pdf",
        f"{BASE}/2022/03/AACL-Corporate-presentation-26-06-2026.pdf",
    ), "TESTCO") == []
