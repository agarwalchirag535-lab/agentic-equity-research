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
