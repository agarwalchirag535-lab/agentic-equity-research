

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
