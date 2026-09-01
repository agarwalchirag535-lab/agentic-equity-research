

def test_key_audit_matters_is_owed_from_fy19_not_fy18():
    """SA 701 was deferred to periods beginning on/after 1 April 2018 (first AR: FY19). Symphony's
    Deloitte-audited FY18 report carries no KAM section and is compliant; flagging it charged a real
    company for a disclosure not yet owed (ADR-0055)."""
    from firm.adapters.india.filings import disclosure_gaps

    sections = {"auditors_opinion": "x", "related_party": "x", "contingent_liabilities": "x",
                "key_audit_matters": ""}
    missing_fy18, flagged_fy18 = disclosure_gaps(sections, fiscal_year=2018)
    assert not flagged_fy18 and missing_fy18 == []
    missing_fy19, flagged_fy19 = disclosure_gaps(sections, fiscal_year=2019)
    assert flagged_fy19 and missing_fy19 == ["key_audit_matters"]


def test_schedule_iii_scan_survives_the_orthography_of_real_filings():
    """ADR-0060: three false disclosure charges on one filing, each one character wide.

    Five-Star FY26 prints every one of these tables; the literal substring scan reported all three
    absent — an American spelling, a parenthesis, and a slash. A false 'mandated disclosure absent'
    is a governance accusation against a real company, so the match must survive typography.
    """
    from firm.adapters.india.notes import scan_schedule_iii

    pages = [
        "a) CWIP aging schedule\nProjects in progress  972.24  6,236.10",         # American spelling
        "16.2. Trade payables (Ageing Schedule)\nAs at March 31, 2026",           # parenthesis
        "Debt/Equity Ratio3  Times  1.11 1.26",                                   # slash, not hyphen
    ]
    found = {f.row: f.found for f in scan_schedule_iii(pages)}
    assert found["cwip_ageing"] is True
    assert found["payables_ageing"] is True
    assert found["ratios_disclosure"] is True
    # And the absence claim still works: rows genuinely not on these pages stay not-found.
    assert found["benami_property"] is False
    assert found["struck_off_companies"] is False
