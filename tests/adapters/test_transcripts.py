"""Parsing an earnings-call transcript into dated, quoted guidance (Phase 3).

Text excerpts are frozen from Alkyl Amines' real Reg-30 submissions — the same discipline as the BSE
fixtures. The risks the tests guard: an analyst's question read as management's guidance, a call
announcement read as a transcript, a stated "FY23-24" read as FY23, and a bare number promoted to a
guidance value it never was.
"""

from __future__ import annotations

from firm.adapters.india.transcripts import _period_from_date, parse_transcript

#: Page 1 as the real May-2025 submission prints it: the letter's own date first, a reference to earlier
#: correspondence (before the call — must not become the cover date), then the held-on sentence.
COVER = (
    "May 16, 2025\n"
    "To,\nBSE Limited\n"
    "Sub.: Submission under Regulation 30 of SEBI (Listing Obligations and Disclosure Requirements) "
    "Regulations, 2015 - Submission of transcript of earnings conference call\n"
    "With reference to our letter dated May 6, 2025, please find enclosed the transcript of the "
    "earnings conference call held on May 12, 2025.\n"
)

TITLE = "Alkyl Amines Chemicals Limited 4QFY2025 Earnings Conference Call\nMay 12, 2025\n"

DIALOGUE = (
    "Moderator:\n"
    "Ladies and gentlemen, good day and welcome.\n"
    "It is around Rs. 150 crores, so that is from carry forward projects from past year also and some "
    "new projects in current year, so around Rs. 150 crores we forecast for next year.\n"
    "So, we expect double digit growth in next year around 10% to 15% which we have been maintaining.\n"
    "Do we expect to improve to around 21% on net in the next financial year?\n"
    "Page 10 of 15\n"
)


def test_a_real_transcript_yields_dates_period_and_quoted_guidance():
    s = parse_transcript((COVER, TITLE, DIALOGUE))
    assert s.located
    assert s.call_date == "2025-05-12"          # from "held on", not the letter date
    assert s.cover_date == "2025-05-16"         # the letter's own date, not the May 6 reference
    assert s.period == "Q4FY25"
    assert s.period_basis == "stated"

    statements = [g for g in s.guidance if g.kind == "statement"]
    questions = [g for g in s.guidance if g.kind == "question"]
    assert len(statements) == 2 and len(questions) == 1

    capex = next(g for g in statements if "150" in g.quote)
    assert capex.page == 3
    assert [(v.value, v.unit) for v in capex.values] == [(150.0, "inr_cr"), (150.0, "inr_cr")]

    growth = next(g for g in statements if "double digit" in g.quote)
    assert growth.topic == "volume_growth"
    assert [(v.value, v.unit) for v in growth.values] == [(10.0, "pct"), (15.0, "pct")]


def test_an_analysts_question_is_never_managements_guidance():
    """"Do we expect 21%?" is a question. Collapsing it into guidance puts words in management's mouth."""
    s = parse_transcript((COVER, TITLE, DIALOGUE))
    question = next(g for g in s.guidance if g.kind == "question")
    assert "21" in question.quote


def test_an_ask_without_a_question_mark_is_still_a_question():
    """Real asks trail off without "?" — "just wanted to ask, any guidance regarding this FY 25." """
    pages = (COVER, TITLE,
             "Moderator:\nSir, just wanted to ask, any guidance regarding this FY 25 volume growth.\n")
    ask = next(g for g in parse_transcript(pages).guidance if "wanted to ask" in g.quote)
    assert ask.kind == "question"


def test_a_call_announcement_is_refused_not_skimmed():
    """The May-2022 intimation letter names an earnings call but carries only dial-in numbers."""
    announcement = (
        ("May 16, 2022\nSub: Intimation under Regulation 30\n"
        "We wish to inform you that an earnings conference call is scheduled to be held on "
        "Friday, May 20, 2022 at 3:00 pm (IST).\nUniversal Access: +91 22 6280 1458\n"),
    )
    s = parse_transcript(announcement)
    assert s.located is False
    assert "announcement" in (s.rejected_because or "")


def test_a_document_with_no_call_title_is_refused():
    s = parse_transcript(("Some unrelated filing with a transcript of a board meeting.\n",))
    assert s.located is False
    assert "not a transcript" in (s.rejected_because or "")


def test_a_fiscal_year_range_names_the_end_year():
    """"Q4 FY23-24" is FY24 — the Indian FY is named for the year it ends in. It parsed as FY23."""
    pages = (COVER.replace("May", "May"), "Q4 FY23-24 Earnings Conference Call\nMay 10, 2024\n",
             "Moderator:\ntranscript\n")
    assert parse_transcript(pages).period == "Q4FY24"


def test_a_weekday_in_the_held_on_sentence_still_dates_the_call():
    """Real letters write "held on Thursday, November 7, 2019" — the weekday broke the first pattern."""
    pages = (
        ("November 19, 2019\nSubmission of transcript of earnings conference call\n"
        "please find enclosed the transcript of the earnings conference call held on "
        "Thursday, November 7, 2019.\n"),
        "Moderator:\nWe expect the plant to be commissioned next year with 30% higher capacity.\n",
    )
    s = parse_transcript(pages)
    assert s.call_date == "2019-11-07"
    assert s.cover_date == "2019-11-19"
    # No quarter is stated anywhere, so the period is inferred from the call date and labelled as such.
    assert s.period == "Q2FY20"
    assert s.period_basis == "derived-from-call-date"


def test_bare_numbers_and_years_never_become_guidance_values():
    """Only unit-anchored figures are values; "20:80" ratios and calendar years stay in the quote."""
    pages = (
        COVER, TITLE,
        "Moderator:\nGoing forward we plan 3 debottlenecking projects by 2027.\n",
    )
    s = parse_transcript(pages)
    plan = next(g for g in s.guidance if "debottlenecking" in g.quote)
    assert plan.values == ()
    assert plan.topic == "capacity"


def test_repeated_running_header_sentences_are_recorded_once():
    repeated = "We expect double digit growth in next year around 10% to 15% which we said before.\n"
    s = parse_transcript((COVER, TITLE, "Moderator:\n" + repeated, repeated))
    assert sum("double digit" in g.quote for g in s.guidance) == 1


def test_period_inference_walks_back_to_the_most_recent_quarter_end():
    assert _period_from_date("2025-05-12") == "Q4FY25"   # call after March close
    assert _period_from_date("2025-02-10") == "Q3FY25"   # call after December close
    assert _period_from_date("2019-11-07") == "Q2FY20"   # call after September close
    assert _period_from_date("2026-01-15") == "Q3FY26"   # January: walks into the prior calendar year
