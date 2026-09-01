"""Daily closes from the exchange (ADR-0062). Offline: the fetcher is injected."""

from __future__ import annotations

import json
from datetime import date

from firm.adapters.india.prices import (
    Close,
    close_on_or_before,
    fetch_closes,
    parse_closes,
    price_url,
)


def _payload(rows: list[tuple[str, str, str]]) -> str:
    """The endpoint's shape: JSON whose `Data` member is itself a JSON STRING."""
    return json.dumps({"Scripname": "X", "Data": json.dumps(
        [{"dttm": d, "vale1": p, "vole": v} for d, p, v in rows])})


def test_the_double_encoded_payload_is_parsed_to_a_dated_series():
    closes = parse_closes(_payload([
        ("Mon Jan 01 2018 00:00:00", "262.66", "636"),
        ("Tue Jan 02 2018 00:00:00", "265.10", "700"),
    ]))
    assert [(c.on, c.price, c.volume) for c in closes] == [
        (date(2018, 1, 1), 262.66, 636.0), (date(2018, 1, 2), 265.10, 700.0)]


def test_rows_that_cannot_be_parsed_are_dropped_not_guessed():
    """A gap is visible through `close_on_or_before` (it returns an older close, with its real date).
    An invented price is visible to nothing."""
    closes = parse_closes(_payload([
        ("Mon Jan 01 2018 00:00:00", "262.66", "636"),
        ("garbage", "265.10", "700"),                      # unparseable date
        ("Wed Jan 03 2018 00:00:00", "not-a-number", "1"),  # unparseable price
        ("Thu Xxx 04 2018 00:00:00", "1.0", "1"),           # unknown month
        ("Fri Jan 05 2018 00:00:00", "0", "1"),             # a zero close is not a price
    ]))
    assert [c.on for c in closes] == [date(2018, 1, 1)]


def test_a_malformed_payload_is_an_empty_series_not_an_exception():
    assert parse_closes("not json") == []
    assert parse_closes(json.dumps({"Data": "not json either"})) == []
    assert parse_closes(json.dumps({})) == []


def test_the_series_comes_back_oldest_first_whatever_order_it_arrived_in():
    closes = parse_closes(_payload([
        ("Wed Jan 03 2018 00:00:00", "3", "1"),
        ("Mon Jan 01 2018 00:00:00", "1", "1"),
    ]))
    assert [c.on.day for c in closes] == [1, 3]


def test_close_on_or_before_never_looks_past_as_of():
    """LAW 3, at the single easiest place in the system to leak the future: one careless series[-1]
    in a replay of 2019 values the company at today's price and the whole backtest is a fantasy."""
    closes = [Close(date(2019, 1, 29), 299.5, 1.0),
              Close(date(2021, 6, 30), 3598.85, 1.0),
              Close(date(2026, 8, 28), 2044.4, 1.0)]
    assert close_on_or_before(closes, date(2019, 12, 31)).price == 299.5
    assert close_on_or_before(closes, date(2021, 6, 30)).price == 3598.85
    # A weekend/holiday `as_of` resolves to the last SETTLED close, and carries its real date so the
    # citation says which day it is.
    got = close_on_or_before(closes, date(2026, 8, 30))
    assert got.price == 2044.4 and got.on == date(2026, 8, 28)
    # Before the series begins there is no price — not a zero, not the earliest.
    assert close_on_or_before(closes, date(2017, 1, 1)) is None
    assert close_on_or_before([], date(2026, 1, 1)) is None


def test_the_url_names_the_daily_close_series_and_the_window():
    url = price_url("506767", date(2018, 1, 1), date(2026, 8, 31))
    assert "scripcode=506767" in url and "flag=1" in url        # flag=1 is daily; flag=0 is intraday
    assert "fromdate=20180101" in url and "todate=20260831" in url


def test_fetch_closes_passes_the_built_url_to_the_injected_fetcher():
    seen: list[str] = []
    closes = fetch_closes("506767", date(2018, 1, 1), date(2018, 1, 2),
                          lambda u: (seen.append(u), _payload([("Mon Jan 01 2018 00:00:00", "1", "2")]))[1])
    assert len(seen) == 1 and "scripcode=506767" in seen[0]
    assert closes[0].price == 1.0
