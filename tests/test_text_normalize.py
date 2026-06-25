from __future__ import annotations

import pytest

from pipeline.common.text_normalize import clean_wiki_snippet


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Space-before-punctuation artifacts from inline-link stripping.
        ("Prior to the Third War , the region", "Prior to the Third War, the region"),
        ("the cauldrons in Andorhal .", "the cauldrons in Andorhal."),
        ("Was it real ? Yes !", "Was it real? Yes!"),
        # Possessive artifacts.
        ("Lordaeron 's northern provinces", "Lordaeron's northern provinces"),
        ("the Barov 's primary residence", "the Barov's primary residence"),
        ("the farmers ' militia", "the farmers' militia"),
        # Must NOT corrupt legitimate text.
        ("It cost 3.14 credits.", "It cost 3.14 credits."),
        ("Gourd-Digger...", "Gourd-Digger..."),
        ("The Farmers' Militia stood firm.", "The Farmers' Militia stood firm."),
    ],
)
def test_clean_wiki_snippet_fixes_link_artifacts(raw: str, expected: str) -> None:
    assert clean_wiki_snippet(raw) == expected


def test_clean_wiki_snippet_strips_citations_and_entities() -> None:
    assert (
        clean_wiki_snippet("Andorhal[1] &amp; the plague , spread.")
        == "Andorhal & the plague, spread."
    )


def test_clean_wiki_snippet_strips_ipa_pronunciation_guides() -> None:
    # The lead pronunciation guide carries non-Latin IPA glyphs that trip the prose
    # script-mixing gate; strip the whole parenthetical (WS regression on Scholomance).
    raw = (
        "The Scholomance ( /ˈskoʊ.loʊ.mæns/ SKOH-loh-mance ), "
        "also known as the School of Necromancy, is a vile academy."
    )
    assert clean_wiki_snippet(raw) == (
        "The Scholomance, also known as the School of Necromancy, is a vile academy."
    )


def test_clean_wiki_snippet_keeps_ordinary_parentheticals_with_slash() -> None:
    # A normal parenthetical that happens to contain a slash is not a pronunciation guide.
    assert clean_wiki_snippet("Testing (A/B variants) here.") == "Testing (A/B variants) here."


def test_clean_wiki_snippet_strips_source_attribution_preamble() -> None:
    # The dungeon "Description" section opens with a Blizzard Community-Site attribution that
    # leaked verbatim into a Scholomance overview. It is not lore and must be stripped.
    raw = (
        "From the World Dungeons page on the official World of Warcraft Community Site: "
        "Individuals seeking to master the powers of undeath know well of Scholomance."
    )
    assert clean_wiki_snippet(raw) == (
        "Individuals seeking to master the powers of undeath know well of Scholomance."
    )


@pytest.mark.parametrize(
    "ordinary",
    [
        "From the ashes of Lordaeron rose the Forsaken, free at last.",
        "From the high walls of Hearthglen, the Argent Crusade watches the plague.",
        "From the start of the Third War, the Scourge spread plague across the land.",
    ],
)
def test_clean_wiki_snippet_keeps_ordinary_from_clauses(ordinary: str) -> None:
    # The attribution strip must not swallow ordinary prose that opens with "From the ...".
    assert clean_wiki_snippet(ordinary) == ordinary


def test_clean_wiki_snippet_handles_empty() -> None:
    assert clean_wiki_snippet("") == ""
    assert clean_wiki_snippet("   ") == ""
