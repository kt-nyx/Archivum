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


def test_clean_wiki_snippet_handles_empty() -> None:
    assert clean_wiki_snippet("") == ""
    assert clean_wiki_snippet("   ") == ""
