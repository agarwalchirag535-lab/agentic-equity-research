"""Schedule III ageing schedules (ADR-0038).

The tests that matter here are the refusals. A misread ageing table is not a small error: it carries the
filing's grade-A locator, so a bucket read one column left says a two-year-old receivable is current.
"""
from __future__ import annotations

from pytest import approx

from firm.adapters.india.ageing import parse_ageing_table

CWIP_PAGE = """3.3a. Ageing of Capital Work in progress as on March 31, 2026 ` In Lakhs
Particulars Amounts in capital work-in-progress for a period of
Less than 1 year 1-2 years 2-3 years More than 3 years Total
Projects in progress  9,585.08  1,195.46  280.17  358.25  11,418.96
Projects temporarily suspended  13.33  292.11  1,256.54  67.18  1,629.16
Total  9,598.41  1,487.57  1,536.71  425.43  13,048.12
"""

RECEIVABLES_PAGE = """11 TRADE RECEIVABLES- UNSECURED (At Amortized Cost) ` In Lakhs
Particulars Outstanding for following periods from due date of payment as at March 31, 2026
Unbilled Not due Less than
6 months
1-2 years 2-3 years Total
i) Undisputed Trade receivable-
considered good  83.07  20,463.14  2,501.01  1.02  1.26  23,049.50
iv) Disputed Trade Receivables-
considered good  -    -    -    -    -    -
"""


def test_cwip_ageing_reads_every_bucket_and_reconciles_to_its_own_total():
    table = parse_ageing_table((CWIP_PAGE,), "cwip")
    assert table.located and table.aligned
    assert table.total == approx(130.4812)                       # 13,048.12 lakh -> crore
    assert table.suspended == approx(16.2916)
    # The forensic quantity: capital sitting in the >1yr buckets rather than commissioning.
    assert round(table.long_dated, 4) == round((1195.46 + 280.17 + 358.25 + 292.11 + 1256.54 + 67.18) / 100, 4)


def test_a_dash_is_a_zero_and_does_not_shift_the_columns():
    """The defect this guards: dropping '-' shifts every later figure one column left, so a 2-3 year
    balance is published as current. The disputed row here is all dashes."""
    table = parse_ageing_table((RECEIVABLES_PAGE,), "receivables")
    good = table.rows[0]
    assert good.buckets[0] == approx(0.8307) and good.buckets[1] == approx(204.6314)
    disputed = [r for r in table.rows if r.is_disputed]
    assert disputed and all(b == 0.0 for b in disputed[0].buckets)
    assert table.disputed == 0.0


def test_the_row_label_keeps_the_prefix_that_classifies_it():
    """`Undisputed`/`Disputed` arrives on the line ABOVE the figures. Losing it to the header would make
    every disputed balance read as undisputed — a false clean on the one column that matters."""
    table = parse_ageing_table((RECEIVABLES_PAGE,), "receivables")
    assert any("Undisputed" in r.label for r in table.rows)
    assert any(r.is_disputed for r in table.rows)


def test_misaligned_rows_withhold_their_buckets_rather_than_guess():
    broken = """3.3a. Ageing of Capital Work in progress as on March 31, 2026 ` In Lakhs
Less than 1 year 1-2 years 2-3 years More than 3 years Total
Projects in progress  9,585.08  1,195.46  11,418.96
"""
    table = parse_ageing_table((broken,), "cwip")
    assert table.located
    assert not table.aligned            # buckets do not sum to the printed total
    assert table.long_dated is None     # so the bucket-level figure is refused, not estimated
    assert table.rows[0].total == approx(114.1896)   # the row total is still usable
    assert "columns" in table.reason


def test_a_missing_schedule_is_distinguishable_from_an_empty_one():
    absent = parse_ageing_table(("nothing relevant here",), "receivables")
    assert not absent.located and absent.total == 0.0 and "no receivables ageing" in absent.reason


def test_occurrence_selects_the_current_year_table_not_the_comparative():
    doubled = CWIP_PAGE + CWIP_PAGE.replace("13,048.12", "5,191.34").replace("2026", "2025")
    current = parse_ageing_table((doubled,), "cwip", occurrence=0)
    prior = parse_ageing_table((doubled,), "cwip", occurrence=1)
    assert current.total == approx(130.4812)
    assert prior.total == approx(51.9134)
