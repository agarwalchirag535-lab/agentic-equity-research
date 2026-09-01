"""Enumerating adverse events from the exchange's register (ADR-0062). Offline: `fetch` is injected."""

from __future__ import annotations

import json
from datetime import date

import pytest

from firm.adapters.india.register import (
    EVENT_SUBCATEGORIES,
    AdverseEvent,
    adverse_events,
    announcement_url,
    deduplicate,
)


def _row(day: str, code: str, name: str, headline: str = "Resignation", attach: str = "a.pdf"):
    return {"NEWS_DT": f"{day}T10:00:00", "SCRIP_CD": code, "SLONGNAME": name,
            "HEADLINE": headline, "ATTACHMENTNAME": attach}


def test_a_window_wider_than_a_month_is_split():
    """The endpoint returns nothing for a range much wider than a month, and a silent empty page reads as
    'no events' — the one answer an enumeration must never invent."""
    urls: list[str] = []

    def fetch(url: str) -> str:
        urls.append(url)
        return json.dumps({"Table": []})

    adverse_events(date(2022, 1, 1), date(2022, 3, 31), fetch=fetch)
    assert len(urls) == 3, "one request per calendar month"
    assert "strPrevDate=20220101" in urls[0] and "strToDate=20220131" in urls[0]
    assert "strPrevDate=20220301" in urls[2] and "strToDate=20220331" in urls[2]


def test_a_partial_month_keeps_the_caller_s_bounds():
    urls: list[str] = []
    adverse_events(date(2022, 1, 15), date(2022, 2, 10),
                   fetch=lambda u: (urls.append(u), json.dumps({"Table": []}))[1])
    assert "strPrevDate=20220115" in urls[0] and "strToDate=20220131" in urls[0]
    assert "strPrevDate=20220201" in urls[1] and "strToDate=20220210" in urls[1]


def test_events_carry_a_citable_source():
    """A label with no citation is an assertion. The filed PDF is the citation."""
    events = adverse_events(
        date(2023, 8, 1), date(2023, 8, 31),
        fetch=lambda u: json.dumps({"Table": [_row("2023-08-15", "534809", "PC Jeweller Ltd",
                                                   "Change in Statutory Auditors", "abc.pdf")]}))
    assert len(events) == 1
    event = events[0]
    assert event.kind == "auditor_resignation" and event.on == date(2023, 8, 15)
    assert event.scrip_code == "534809" and event.company == "PC Jeweller Ltd"
    assert event.source.endswith("/abc.pdf")


def test_an_announcement_with_no_attachment_has_no_source():
    events = adverse_events(date(2023, 8, 1), date(2023, 8, 31),
                            fetch=lambda u: json.dumps({"Table": [_row("2023-08-15", "1", "X", "h", "")]}))
    assert events[0].source == ""


def test_deduplicate_keeps_the_earliest_filing_per_company():
    """A company files a corrigendum or announces twice. The set cares when the market FIRST learned,
    because that is the date an `as_of` has to precede."""
    events = [
        AdverseEvent("auditor_resignation", date(2022, 1, 28), "530461", "Saboo", "h", "s"),
        AdverseEvent("auditor_resignation", date(2022, 1, 31), "530461", "Saboo", "corrigendum", "s"),
        AdverseEvent("auditor_resignation", date(2022, 2, 2), "999999", "Other", "h", "s"),
    ]
    kept = deduplicate(events)
    assert [(e.scrip_code, e.on) for e in kept] == [("530461", date(2022, 1, 28)),
                                                    ("999999", date(2022, 2, 2))]


def test_the_subcategory_is_the_exchange_s_own_wording():
    """Paraphrasing it into our words would make the enumeration unreproducible against the source."""
    assert EVENT_SUBCATEGORIES["auditor_resignation"] == (
        "Company Update", "Resignation of Statutory Auditors")
    category, subcategory = EVENT_SUBCATEGORIES["auditor_resignation"]
    assert "Resignation+of+Statutory+Auditors" in announcement_url(
        subcategory, (date(2022, 1, 1), date(2022, 1, 31)), category=category
    ).replace("%20", "+")


def test_a_kind_outside_company_update_queries_its_own_category():
    """The API's subcategory filter matches only inside its parent category — `strCat=-1` with a
    subcategory returns NOTHING, so a kind that ships the wrong category silently enumerates zero
    events, which reads as 'no defaults happened'."""
    urls: list[str] = []
    adverse_events(date(2023, 8, 1), date(2023, 8, 31), kinds=("loan_default",),
                   fetch=lambda u: (urls.append(u), json.dumps({"Table": []}))[1])
    assert len(urls) == 1 and "strCat=Others" in urls[0]


def test_the_cirp_subcategory_keeps_the_exchange_s_double_space():
    """The exchange's own string carries two spaces before '(CIRP)'. 'Fixing' the typography would make
    the filter match nothing (the ADR-0060 orthography lesson, on the enumeration side)."""
    assert "  (CIRP)" in EVENT_SUBCATEGORIES["cirp_update"][1]


def test_a_full_page_is_followed_and_a_partial_page_ends_the_month():
    """Stopping at page 1 SAMPLED the busy months while claiming to enumerate them."""
    calls: list[str] = []

    def fetch(url: str) -> str:
        calls.append(url)
        page = int(url.split("pageno=")[1].split("&")[0])
        if page == 1:
            return json.dumps({"Table": [_row("2023-08-01", str(i), f"C{i}") for i in range(50)]})
        return json.dumps({"Table": [_row("2023-08-02", "999", "Last")]})

    events = adverse_events(date(2023, 8, 1), date(2023, 8, 31), fetch=fetch)
    assert len(calls) == 2 and "pageno=2" in calls[1]
    assert len(events) == 51


def test_an_unknown_kind_is_refused_rather_than_silently_skipped():
    with pytest.raises(KeyError):
        adverse_events(date(2022, 1, 1), date(2022, 1, 31), kinds=("made_up",),
                       fetch=lambda u: json.dumps({"Table": []}))


def test_market_cap_is_ltp_times_shares_and_none_without_tradable_equity():
    from firm.adapters.india.register import market_cap_cr

    peer = json.dumps({"Table": [
        {"scrip_cd": 534809, "LTP": 11.01, "Equity": 971.05, "FACE_VALUE": 1.0},
        {"scrip_cd": 500114, "LTP": 5115.8, "Equity": 88.78, "FACE_VALUE": 1.0},
    ]})
    cap = market_cap_cr("534809", lambda u: peer)
    assert cap == pytest.approx(11.01 * 971.05, rel=1e-9)      # the row is matched by scrip, not order
    assert market_cap_cr("111111", lambda u: peer) is None       # absent scrip
    assert market_cap_cr("534809", lambda u: json.dumps({"Table": [
        {"scrip_cd": 534809, "LTP": 0, "Equity": 971.05, "FACE_VALUE": 1.0}]})) is None  # no live price


def test_triage_applies_only_the_band_and_records_every_exclusion():
    """A CIRP company is not excluded for being in CIRP — that is the label, not a defect. Only the
    mcap band moves an event out, and each exclusion carries its reason."""
    from firm.adapters.india.register import triage

    events = [
        AdverseEvent("cirp_update", date(2023, 1, 5), "1", "InBand Ltd", "h", "s"),
        AdverseEvent("cirp_update", date(2023, 1, 6), "2", "TooSmall Ltd", "h", "s"),
        AdverseEvent("cirp_update", date(2023, 1, 7), "3", "TooBig Ltd", "h", "s"),
        AdverseEvent("cirp_update", date(2023, 1, 8), "4", "Suspended Ltd", "h", "s"),
    ]
    caps = {"1": 500.0, "2": 12.0, "3": 90000.0, "4": None}
    candidates, excluded = triage(events, caps.get, floor_cr=300, ceiling_cr=30000)
    assert [c["company"] for c in candidates] == ["InBand Ltd"]
    assert candidates[0]["mcap_cr_today"] == 500.0
    reasons = {e["company"]: e["exclusion"] for e in excluded}
    assert "below the universe floor" in reasons["TooSmall Ltd"]
    assert "provisional" in reasons["TooSmall Ltd"]              # today's-cap bias is named, not hidden
    assert "above the universe ceiling" in reasons["TooBig Ltd"]
    assert "no market cap reported" in reasons["Suspended Ltd"]


def test_triage_fetches_each_scrip_once():
    from firm.adapters.india.register import triage

    calls: list[str] = []

    def mcap(scrip: str) -> float:
        calls.append(scrip)
        return 500.0

    events = [AdverseEvent("loan_default", date(2023, 1, 5), "7", "X", "h", "s"),
              AdverseEvent("loan_default", date(2023, 2, 5), "7", "X", "h2", "s2")]
    triage(events, mcap, floor_cr=300, ceiling_cr=30000)
    assert calls == ["7"]


def test_two_passes_union_what_a_lossy_pass_dropped():
    """Measured live: under sustained load the endpoint returns PARTIAL pages with no error — one
    39-window sweep saw 3 of a month's 10 events. A row present in EITHER pass must survive."""
    seen = {"n": 0}

    def flaky(url: str) -> str:
        seen["n"] += 1
        if seen["n"] == 1:   # first pass drops an event silently
            return json.dumps({"Table": [_row("2021-10-20", "532767", "Gayatri")]})
        return json.dumps({"Table": [_row("2021-10-06", "532767", "Gayatri"),
                                     _row("2021-10-20", "532767", "Gayatri")]})

    events = adverse_events(date(2021, 10, 1), date(2021, 10, 31), fetch=flaky, passes=2)
    assert [str(e.on) for e in events] == ["2021-10-06", "2021-10-20"]
