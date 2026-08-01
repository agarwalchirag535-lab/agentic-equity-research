"""Parsing a SEBI shareholding pattern (ADR-0032).

The signal is promoter stake and pledge. The risk is a plausible-looking wrong stake: 71.96% read as 17.96%
would drive a governance verdict off a cliff and look entirely normal doing it. So the category identity
(promoter + public = 100) is used twice — to repair a welded column, and to refuse anything that will not
reconcile.
"""

from __future__ import annotations

from firm.adapters.india.shareholding import parse_shareholding

CLEAN = (
    "Shareholding Pattern as on 30/09/2024\n"
    "6 Whether any shares held by promoters are pledge or otherwise encumbered? No\n"
    "(A) Promoter & Promoter Group 13 36799268 36799268 71.96 36799268 71.96\n"
    "(B) Public 178995 14336770 14336770 28.04 14336770 28.04\n",
)

#: The same filing as the text layer actually renders it on 14 of Alkyl Amines' 27 quarters: the column
#: separator is lost and the percentage is welded onto the share count.
WELDED = (
    "6 Whether any shares held by promoters are pledge or otherwise encumbered? No\n"
    "(A) Promoter & Promoter Group 13 368372680 0 3683726872.0265 368372680 3683726872.0265\n"
    "(B) Public 149311 143067840 0 1430678427.9735 143067840 1430678427.9735\n",
)


def test_a_clean_filing_yields_promoter_public_and_pledge():
    s = parse_shareholding(CLEAN)
    assert s.located
    assert s.promoter_pct == 71.96
    assert s.public_pct == 28.04
    assert s.promoter_shareholders == 13
    assert s.pledged is False
    assert s.as_on == "2024-09-30"
    assert s.reconciles


def test_a_welded_column_is_repaired_by_the_category_identity():
    """"3683726872.0265" is 36837268 shares + 72.0265 percent, and the token cannot say where to split.

    A greedy regex picked the one-digit split and produced 2.0265. Generating both readings and choosing the
    pair that sums to 100 recovers the truth without guessing.
    """
    s = parse_shareholding(WELDED)
    assert s.located
    assert s.promoter_pct == 72.0265
    assert s.public_pct == 27.9735
    assert s.reconciles


def test_a_stake_that_will_not_reconcile_is_refused_not_reported():
    """The failure this exists to prevent: a wrong stake that looks right."""
    broken = (
        "(A) Promoter & Promoter Group 13 36799268 17.96\n"
        "(B) Public 178995 14336770 28.04\n",
    )
    s = parse_shareholding(broken)
    assert s.located is False
    assert s.promoter_pct is None
    assert "does not reconcile" in (s.rejected_because or "")


def test_pledge_is_tri_state():
    """`False` (read, and no pledge) is a governance finding; `None` (not read) is a refusal to conclude."""
    assert parse_shareholding(CLEAN).pledged is False

    pledged = (
        "6 Whether any shares held by promoters are pledge or otherwise encumbered? Yes\n"
        "(A) Promoter & Promoter Group 13 36799268 71.96\n(B) Public 178995 14336770 28.04\n",
    )
    assert parse_shareholding(pledged).pledged is True

    silent = ("(A) Promoter & Promoter Group 13 36799268 71.96\n(B) Public 178995 14336770 28.04\n",)
    assert parse_shareholding(silent).pledged is None


def test_missing_category_rows_are_reported_as_not_located():
    s = parse_shareholding(("Some unrelated filing text with 12.34 in it\n",))
    assert s.located is False
    assert "not both located" in (s.rejected_because or "")


#: The pre-2023 layout, as the text layer actually renders it: the category LABEL wraps over three lines and
#: the row's figures over a dozen, so no physical line ever holds a whole row. This shape (14 of Alkyl
#: Amines' 27 filings) was refused outright by a line-anchored parser — seven years of the promoter series.
WRAPPED = (
    "4. Share Holding Pattern as on : 31-Mar-2021 \n"
    "5 Whether any shares held by promoters are pledge \nor otherwise encumbered? \nNo \n",
    "A Promoter & \nPromoter \nGroup \n13 1513278\n8 \n0 0 151327\n88 \n74.13 1513\n2788 \n"
    "0 151\n327\n88 \n74.13 0 74.13 0 0 0 0 15132788  \n"
    "B Public 59800  5279923 0 0 527992\n3 \n25.87 5279\n923 \n0 527\n992\n3 \n"
    "25.87 0 25.87 0 0   4924017 \n"
    "C Non \nPromoter- \nNon Public \n0 0 0 0 0  0 0 0 0 0  0 0   0 \n",
    "Table II - Statement showing shareholding pattern of the Promoter and Promoter Group \n"
    "Yogesh M \nKothari \n1 12206\n622 \n59.8 12206622 \n",
)


def test_a_row_wrapped_across_lines_is_read_whole():
    s = parse_shareholding(WRAPPED)
    assert s.located
    assert (s.promoter_pct, s.public_pct) == (74.13, 25.87)
    assert s.promoter_shareholders == 13
    assert s.as_on == "2021-03-31"      # "31-Mar-2021": a month NAME, which no all-digit pattern reads
    assert s.pledged is False           # the question wraps too, and its answer is on a third line
    assert s.page == 2


def test_table_ii_percentages_never_reach_the_category_row():
    """The promoter breakdown by name follows Table I. Yogesh Kothari's 59.8% is not the category's."""
    s = parse_shareholding(WRAPPED)
    assert s.promoter_pct != 59.8


#: The same filing under LAYOUT-mode extraction: the figures land on one line and the label's own words
#: are pushed onto the continuation lines beside the wrapped digits. Requiring the full "Promoter &
#: Promoter Group" phrase found this row in reading-order mode and silently lost it here.
LAYOUT = (
    "4. Share Holding Pattern as on : 31-Mar-2021\n"
    "5 Whether any shares held by promoters are pledge or otherwise encumbered? No\n",
    "  A  Promoter &  13  1513278  0  0  151327  74.13  1513  0  151  74.13  0  0  15132788\n"
    "  Promoter  8  88  2788  327\n"
    "  Group  88\n"
    "  B  Public  59800  5279923  0  0  527992  25.87  5279  0  527  25.87  0  0  4924017\n"
    "  3  923  992\n"
    "  C  Non  0  0  0  0  0  0  0  0  0  0  0\n  Promoter-\n  Non Public\n",
)


def test_the_row_is_found_when_layout_extraction_splits_the_label():
    s = parse_shareholding(LAYOUT)
    assert s.located
    assert (s.promoter_pct, s.public_pct) == (74.13, 25.87)
    assert s.promoter_shareholders == 13


def test_ordinary_prose_about_a_promoter_is_not_read_as_the_category_row():
    """`A\\s+promoter` alone would match "held by a promoter" — the conjunction is what keeps it strict."""
    prose = (
        "Any shares held by a promoter are disclosed below at 55.5 per cent of the total.\n"
        "(B) Public 178995 14336770 28.04\n",
    )
    assert parse_shareholding(prose).located is False


def test_a_whole_number_percentage_is_read_when_the_filing_rounds():
    """Some quarters print "72" and "28" rather than 72.05/27.95. The decimal discriminator rejects an
    integer by construction, so these two filings were refused until the identity got a second reading."""
    rounded = (
        "As on : 31-12-2024\n"
        "6 Whether any shares held by promoters are pledge or otherwise encumbered? No\n"
        "(A) Promoter & Promoter Group 13 36819268 36819268 72 36819268 36819268 72 72 36819268\n"
        "(B) Public 174914 14316770 14316770 28 14316770 14316770 28 28 13959250\n"
        "Total 174927 51136038 51136038 100\n",
    )
    s = parse_shareholding(rounded)
    assert s.located
    assert (s.promoter_pct, s.public_pct) == (72.0, 28.0)
    assert s.promoter_shareholders == 13


def test_the_shareholder_count_is_never_mistaken_for_the_stake():
    """13 holders and a 72% stake are both small integers. Only the identity separates them, and a
    reading that paired the count with the public stake would sum to 41, not 100."""
    assert parse_shareholding((
        "(A) Promoter & Promoter Group 13 36819268 72\n(B) Public 174914 14316770 28\n",
    )).promoter_pct == 72.0


def test_the_2025_pledge_question_is_read_in_its_new_wording():
    """SEBI split one pledge question into three (Pledged / NDU / other). The old single-question pattern
    matched none of them, so the newest filings reported pledge UNKNOWN while the page answered "No"."""
    revised = (
        'As on : 31-03-2026\n'
        '7 Whether any shares held by promoters are encumbered under "Pledged"? No\n'
        '8 Whether any shares held by promoters are encumbered under "Non-Disposal Undertaking"? Yes\n'
        '9 Whether any shares held by promoters are encumbered, other than by way of Pledge or NDU, '
        'if any? Yes\n'
        "(A) Promoter & Promoter Group 13 36799268 71.96\n(B) Public 178995 14336770 28.04\n",
    )
    s = parse_shareholding(revised)
    # The PLEDGE answer, not the NDU answer beside it: SEBI separates the instruments and so do we.
    assert s.pledged is False
