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
    assert EVENT_SUBCATEGORIES["auditor_resignation"] == "Resignation of Statutory Auditors"
    assert "Resignation+of+Statutory+Auditors" in announcement_url(
        EVENT_SUBCATEGORIES["auditor_resignation"], (date(2022, 1, 1), date(2022, 1, 31))
    ).replace("%20", "+")


def test_an_unknown_kind_is_refused_rather_than_silently_skipped():
    with pytest.raises(KeyError):
        adverse_events(date(2022, 1, 1), date(2022, 1, 31), kinds=("made_up",),
                       fetch=lambda u: json.dumps({"Table": []}))
