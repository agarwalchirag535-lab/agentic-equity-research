"""Reading a concall into an attributed, dated conversation (ADR-0037).

These fixtures are written to the two shapes the real Alkyl Amines transcripts actually come in, because
the bug that mattered was a *format* bug, not a logic one: 11 of 14 transcripts are two-column PDFs whose
stream-order text puts every speaker name in one block and every paragraph in another, and the first
parser read 3-10 turns out of a 19-page call and paired no questions with answers at all.
"""

from __future__ import annotations

from datetime import date

from firm.adapters.india.transcripts import parse_transcript

COVER = """\
"Acme Chemicals Limited 2Q and 1HFY24 Earnings Conference Call"

November 08, 2023

MANAGEMENT: MR. KIRAT PATEL — EXECUTIVE DIRECTOR, ACME
CHEMICALS LIMITED
MS. KANCHAN SHINDE — CHIEF FINANCIAL OFFICER,
ACME CHEMICALS LIMITED
MODERATOR: MR. JAIVEER SHEKHAWAT - AMBIT CAPITAL PRIVATE LIMITED
"""

BODY = """\
Moderator: Thank you. We will now begin the question-and-answer session. The first question is from \
the line of Nirav Jamduia from Anvil Research. Please go ahead.
Nirav Jamduia: Sir, on ethylamine, ethanol cost has moved up a lot. Have we been able to pass that on?
Kirat Patel: We expect the alcohol price to remain around this level going forward, and we have not been \
able to pass on all of the increase, which has put pressure on margins.
Moderator: The next question is from the line of Priya Rao from Meridian Capital. Please go ahead.
Priya Rao: Could you give the segment-wise realisation for the quarter?
Kanchan Shinde: We do not disclose realisation by segment, so I cannot share that number with you today.
"""


def test_a_clean_transcript_yields_roles_dates_and_paired_exchanges():
    read = parse_transcript((COVER, BODY), source="acme-2q24.pdf")

    assert read.complete
    assert read.held_on == date(2023, 11, 8)
    assert read.period == "FY24Q2"
    assert read.moderator == "Jaiveer Shekhawat"
    assert {m.name for m in read.management} == {"Kirat Patel", "Kanchan Shinde"}
    assert any(m.is_cfo for m in read.management)

    # the attendance register comes off the moderator's own handovers
    assert read.analysts[:2] == ("Nirav Jamduia", "Priya Rao")

    # every question is paired with the answer it received, on the page it was given
    assert len(read.exchanges) == 2
    first = read.exchanges[0]
    assert first.analyst == "Nirav Jamduia" and first.answered_by == "Kirat Patel"
    assert not first.deflected
    assert read.exchanges[1].deflected, "an explicit 'we do not disclose' is the deflection candidate"


def test_guidance_is_extracted_as_a_quote_and_never_as_a_number():
    """Law 1's most tempting failure: the sentence feels quantitative, so a parser wants to score it."""
    read = parse_transcript((COVER, BODY), source="acme-2q24.pdf")

    guidance = read.guidance
    assert len(guidance) == 1
    quote = guidance[0]
    assert quote.speaker == "Kirat Patel"
    assert quote.page == 2
    # verbatim: the agent gets the words, and any judgment about them is the agent's, on the record
    assert "we expect the alcohol price to remain" in quote.text.lower()
    assert not hasattr(quote, "value")


def test_the_column_flattened_shape_is_the_one_that_used_to_lose_every_speaker():
    """Stream-order extraction of a two-column transcript: names in a block, then paragraphs in a block.

    The parser cannot rescue this — the association is genuinely gone from the text — so what is under
    test is that it says so (no exchanges) instead of inventing an attribution. `read_transcript` is what
    resolves it, by re-reading the PDF with a layout-preserving extractor and keeping the better result.
    """
    flattened = (
        "Moderator:\nNirav Jamduia:\nKirat Patel:\n"
        "Thank you. The first question is from the line of Nirav Jamduia from Anvil Research.\n"
        "Sir, on ethylamine, have we been able to pass on the cost?\n"
        "We expect the alcohol price to remain around this level going forward.\n"
    )
    read = parse_transcript((COVER, flattened), source="flat.pdf")
    assert read.exchanges == ()


def test_an_unreadable_pdf_is_a_signal_and_never_an_exception():
    """An image-only transcript is a coverage gap to report; a parser that raised would kill the run."""
    read = parse_transcript(("", "   "), source="scanned.pdf")
    assert not read.complete
    assert "no text layer" in (read.rejected_because or "")

    no_turns = parse_transcript(("Some cover text with no speakers at all.",), source="odd.pdf")
    assert not no_turns.complete and "Speaker" in (no_turns.rejected_because or "")


def test_an_analysts_employer_does_not_get_him_onto_the_board():
    """`Mr. Kumar Saumya, Ambit Capital` is a broker; `Mr. Kirat Patel, Executive Director` is an officer.

    The host's introduction is the only roster five of the real transcripts carry, so it has to be read —
    and it lists both, one sentence apart, in the same grammatical form.
    """
    host = (
        "Kumar Saumya: Welcome to the call. From the management, we have with us Mr. Kirat Patel, "
        "Executive Director, and Mrs. Kanchan Shinde, Chief Financial Officer. I hand over to Mr. Kumar "
        "Saumya, Ambit Capital.\n"
    )
    read = parse_transcript((host, BODY), source="host-roster.pdf")
    names = {m.name for m in read.management}
    assert "Kirat Patel" in names and "Kanchan Shinde" in names
    assert "Kumar Saumya" not in names
