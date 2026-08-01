"""Reading a note's TABLE: inventories, borrowings, contingent liabilities (ADR-0040).

Every test here is a REFUSAL or a distinction, because the failure mode of a note reader is never a
slightly wrong number — it is a confident wrong one carrying the filing's grade-A locator, or a "clean"
that means "we could not read it".

The fixtures are the real filings' layout, not a tidied version: headings with a trailing unit marker, a
lettered sub-note, amounts printed inside labels, "-" for nil, and a running page footer. A fixture that
was easier to parse than the documents would be testing a parser we do not have.
"""

from __future__ import annotations

from pytest import approx

from firm.adapters.india.notes_content import (
    borrowings_summary,
    contingent_liabilities_summary,
    find_note_bodies,
    inventory_summary,
    note_lines,
    related_party_summary,
)

#: Alkyl Amines FY26 note 9, verbatim. Lettered component rows, a Sub-Total, a bracketed provision, and
#: the running footer that parses as a ₹20.25cr row if nothing filters it.
INVENTORY_PAGE = """9 INVENTORIES ` In Lakhs
Particulars As at
March 31, 2026
As at
March 31, 2025
(a) Raw Materials  4,434.83  5,915.82
(b) Packing Materials  184.57  213.22
(c) Work-in-Progress (refer note 9b)  709.65  867.10
(d) Finished Goods (refer note 9b)  5,440.22  8,115.71
(e) Stores and Spares  837.02  970.50
(f) Others  674.27  453.48
Sub- Total  12,280.56  16,535.83
Less: Provisions for Inventories  (67.49)  (57.75)
Total  12,213.07  16,478.08
Annual Report 2025-2026Website: www.alkylamines.com  120
10 INVESTMENTS ` In Lakhs
"""

#: Alkyl Amines FY26 note 23. The nil column is a bare "-", and the year it belongs to is the point.
BORROWINGS_PAGE = """23 SHORT TERM BORROWINGS  (At Amortised Cost) ` In Lakhs
Particulars As At
March 31, 2026
As At
March 31, 2025
Secured
From Banks
Cash Credit repayable on demand (refer note below)  -    360.45
Total   -    360.45
Cash Credits are secured by hypothecation of Trade receivables,  Inventories, Cash & Bank Balance and
Current Assets of the Company, both present and future, as well as by the second mortgage of the
specified immovable properties of the Company, as referred in note no 3.2. ROI 7.97% p.a.
24 TRADE PAYABLES ` In Lakhs
"""

#: Alkyl Amines FY26 note 36a — a LETTERED sub-note, which the enumerator could not see before ADR-0040,
#: with footnote prose carrying amounts printed after the total.
CONTINGENT_PAGE = """36a CONTINGENT LIABILITIES AND COMMITMENTS ` in Lakhs
Particulars  For the year ended
 March 31, 2026
 For the year ended
 March 31,2025
 Claims against the Company not acknowledged as debt
i.   Disputed liabilities towards labour matters  45.00  41.80
ii.  Disputed liabilities in respect of Income tax demand  1,018.04  1,018.04
iii. Disputed liabilities in respect of Excise duty*  1,216.03  1,260.77
iv. Disputed liabilities in respect of  Custom duty**  1,405.22  1,297.57
Total  3,684.29  3,618.18
*  Includes ` 21.07 lakhs deposited with Custom Excise and Service Tax Appellate Tribunal (CESTAT)
** Includes ` 250 lakhs deposited with Commissioner of Customs, Mumbai Port.
37 EARNINGS PER SHARE ` in Lakhs
"""


# --------------------------------------------------------------------------------------------------
# 1. The row reader, and the four ways a note table lies to a naive one.
# --------------------------------------------------------------------------------------------------


def test_an_amount_inside_the_label_is_not_the_column():
    """Balaji Amines prints "(includes materials in transit of `2,857.50 lakh)" INSIDE the label.

    Four figures on the line, of which the first two are parenthetical asides. Reading the first two
    reports a ₹28.6cr in-transit disclosure as the ₹138cr raw-material balance.
    """
    page = ("10 Inventories ` In Lakhs\n"
            "Raw materials (includes materials in transit of `2,857.50 lakh; P.Y. `3,322.22 lakh) "
            "13,816.62 13,223.01\n"
            "Total 13,816.62 13,223.01\n"
            "11 Trade receivables ` In Lakhs\n")
    body = find_note_bodies((page,), r"^\s*inventories\s*$")[0]
    row = note_lines(body, (page,))[0]
    assert row.current == approx(138.1662) and row.prior == approx(132.2301)


def test_a_dash_holds_its_column_so_nil_this_year_is_not_last_years_figure():
    """The single most dangerous defect available here, and the exact one this caught on a real filing.

    "Total  -    360.45" is a company that REPAID its borrowings. Drop the dash and one number is left,
    which is then read as the current year — publishing ₹3.60cr of debt, grade A, against a company that
    has none.
    """
    summary = borrowings_summary((BORROWINGS_PAGE,))
    assert summary.located
    assert summary.total_cr == approx(0.0)


def test_the_running_footer_is_not_a_row():
    """"Annual Report 2025-2026Website: www.alkylamines.com 120" parses as (2025, 2026, 120)."""
    summary = inventory_summary((INVENTORY_PAGE,))
    assert summary.reconciled
    assert summary.gross_cr == approx(122.8056)
    assert all(v < 100 for v in summary.components.values())     # no ₹20.25cr phantom row


def test_the_table_ends_at_its_own_total_so_footnote_amounts_are_not_balances():
    """"* Includes ` 21.07 lakhs deposited with CESTAT" is a footnote, not a fifth claim.

    Read as a row it is both a phantom ₹0.21cr balance and a guaranteed reconciliation failure — which
    would then be reported as a finding against the company, caused entirely by our reading past the end
    of the table.
    """
    summary = contingent_liabilities_summary((CONTINGENT_PAGE,))
    assert summary.total_cr == approx(36.8429)
    assert summary.reconciled
    assert sum(summary.buckets.values()) == approx(36.8429)


# --------------------------------------------------------------------------------------------------
# 2. What each reader is FOR.
# --------------------------------------------------------------------------------------------------


def test_the_inventory_note_answers_what_the_stock_is_made_of():
    """The balance sheet gives one number; only the note says whether it is inputs or unsold output."""
    summary = inventory_summary((INVENTORY_PAGE,))
    assert summary.locator == "note 9 p.1"
    assert summary.components["finished_goods"] == approx(54.4022)
    assert summary.components["raw_materials"] == approx(44.3483)
    assert summary.finished_goods_share == approx(54.4022 / 122.8056)
    # The comparative column is read too: the forensic question is about the CHANGE in the mix.
    assert summary.prior_components["finished_goods"] == approx(81.1571)
    assert summary.prior_gross_cr == approx(165.3583)
    # The write-down is read separately from the components, because its ABSENCE is the finding.
    assert summary.provision_cr == approx(0.6749)
    assert summary.provision_share == approx(0.6749 / 122.8056)


def test_the_borrowings_note_yields_the_rate_and_the_security():
    """A balance says how much; only the note says at what price and against what.

    The disclosed rate is what makes a cost of debt a measurement instead of Interest ÷ Borrowings, which
    ADR-0025 showed becomes an artefact of rounding the moment borrowings are small.
    """
    summary = borrowings_summary((BORROWINGS_PAGE,))
    assert summary.disclosed_rates == (7.97,)
    assert summary.highest_disclosed_rate == approx(0.0797)
    assert summary.security_given and "hypothecation" in summary.security_text
    assert summary.repayable_on_demand


def test_the_contingent_note_sizes_what_the_company_says_it_will_not_pay():
    summary = contingent_liabilities_summary((CONTINGENT_PAGE,))
    assert summary.note_label == "36a"                       # the lettered sub-note is found at all
    assert summary.buckets["income_tax"] == approx(10.1804)
    assert summary.buckets["indirect_tax"] == approx(12.1603 + 14.0522)
    assert summary.buckets["labour"] == approx(0.45)
    # ...and reports that no guarantee was given, which is a finding rather than an absence.
    assert summary.guarantees_given is False
    assert summary.guarantees_for_related_party is False


def test_a_guarantee_given_for_a_related_party_is_recognised_and_kept_separate():
    """Balaji Amines FY25 discloses one inside a GST sentence, with no separate figure.

    Both facts matter and they are different: the exposure exists (so `guarantees_given` is True) and it
    cannot be sized (so no amount). An unquantified off-balance-sheet obligation is a weaker disclosure
    than a large quantified one, and the reader has to be told which they are looking at.
    """
    page = CONTINGENT_PAGE.replace(
        "iv. Disputed liabilities in respect of  Custom duty**  1,405.22  1,297.57",
        "iv. GST on know-how and corporate guarantee extended on behalf of the subsidiary company  "
        "1,405.22  1,297.57")
    summary = contingent_liabilities_summary((page,))
    assert summary.guarantees_given is True
    assert summary.guarantees_for_related_party is True
    assert summary.guarantees_cr is None                      # disclosed, not sized


def test_an_accounting_policy_sentence_about_guarantees_is_not_a_guarantee():
    """Every filing says it measures financial guarantee contracts at fair value. None of them mean it
    as a disclosure that a guarantee exists, and a reader that counts policy boilerplate as exposure
    will report one against every company it ever reads."""
    page = CONTINGENT_PAGE.replace(
        "Total  3,684.29  3,618.18",
        "The Company recognises financial guarantee contracts initially at fair value.\n"
        "Total  3,684.29  3,618.18")
    assert contingent_liabilities_summary((page,)).guarantees_given is False


# --------------------------------------------------------------------------------------------------
# 3. The distinctions that stop a false clean.
# --------------------------------------------------------------------------------------------------


def test_not_found_is_distinguishable_from_found_and_empty():
    for summary in (inventory_summary(("nothing here",)),
                    borrowings_summary(("nothing here",)),
                    contingent_liabilities_summary(("nothing here",))):
        assert summary.located is False
        assert summary.reason, "a reader that found nothing must say why"


def test_a_split_that_does_not_add_up_withholds_the_split_and_keeps_the_total():
    """The ageing schedules' alignment contract (ADR-0038), applied to note tables.

    A composition that does not reconcile means a row was missed or picked up from outside the table, so
    every share computed from it is wrong in an unknown direction.
    """
    broken = INVENTORY_PAGE.replace("(a) Raw Materials  4,434.83  5,915.82", "")
    summary = inventory_summary((broken,))
    assert summary.located and not summary.reconciled
    assert summary.total_cr == approx(122.1307)               # the total survives
    assert summary.finished_goods_share is None              # the share does not
    assert "do not add up" in summary.reason


def test_a_note_whose_page_declares_no_unit_yields_nothing_rather_than_assuming_crore():
    """ADR-0024's rule: a wrong scale is indistinguishable from a wrong number once it carries grade A."""
    unitless = INVENTORY_PAGE.replace(" ` In Lakhs", "")
    summary = inventory_summary((unitless,))
    assert summary.located and summary.gross_cr is None
    assert "no unit" in summary.reason


def test_the_related_party_reader_is_unchanged_by_the_shared_heading_matcher():
    """ADR-0040 replaced this module's private heading pattern with the enumerator's. The related-party
    reader is the one caller that already worked, so it is the regression guard for that swap."""
    page = ("41 RELATED PARTY DISCLOSURES ` In Lakhs\n"
            "Directors' Remuneration/ Commission & Sitting Fees:\n"
            "Yogesh Kothari *  1,360.50\n"
            " (1,398.06)\n"
            "Kirat Patel *  609.04\n"
            "42 EARNINGS PER SHARE ` In Lakhs\n")
    summary = related_party_summary((page,))
    assert summary.located and summary.only_remuneration
    assert summary.remuneration_cr == approx((1360.50 + 609.04) / 100)
    assert summary.has_promoter_lending is False
