from __future__ import annotations

from pipeline.common.text_sim import token_jaccard
from pipeline.generate.draft.prose_lint import (
    AT_A_GLANCE_CURRENTLY_OVERLAP_THRESHOLD,
    lint_at_a_glance,
    lint_currently,
    lint_history_sections,
    trim_words,
    word_count,
)


def test_trim_words_under_budget_is_unchanged() -> None:
    text = "A short clean sentence about the academy."
    assert trim_words(text, 40) == text


def test_trim_words_keeps_whole_sentences_over_budget() -> None:
    # Three sentences (7 + 7 + 11 regex words); only the first two fit a 15-word cap. The
    # trimmer must drop the whole third sentence, not chop it mid-phrase to "...Caer Darrow
    # secretly." (the overview truncation defect).
    text = (
        "The Barovs struck a bargain with Kel'Thuzad. "
        "The manor became a school of necromancy. "
        "The once opulent keep of Caer Darrow secretly fell to ruin."
    )
    result = trim_words(text, 15, ensure_terminal_punct=True)
    assert result == "The Barovs struck a bargain with Kel'Thuzad. The manor became a school of necromancy."
    assert "secretly" not in result
    assert result.endswith("necromancy.")
    assert word_count(result) <= 15


def test_trim_words_falls_back_to_hard_trim_for_single_runon() -> None:
    # A single punctuation-free run-on cannot be split on a sentence boundary, so the cap is
    # still enforced (and terminal punctuation added) rather than dropping the field to empty.
    text = " ".join(["plague"] * 30)
    result = trim_words(text, 12, ensure_terminal_punct=True)
    assert word_count(result) <= 12
    assert result.endswith(".")


def test_trim_words_does_not_double_punctuate_sentence_run() -> None:
    text = "First sentence here. Second sentence here. Third sentence trails on much longer than the cap allows."
    result = trim_words(text, 8, ensure_terminal_punct=True)
    assert result == "First sentence here. Second sentence here."
    assert not result.endswith("..")


def test_at_a_glance_rejects_dominant_present() -> None:
    text = (
        "Western Plaguelands is a blighted region where the Argent Crusade maintains outposts "
        "and continues to heal the soil while factions clash over Andorhal."
    )
    assert any("dominant present tense" in issue for issue in lint_at_a_glance(text))


def test_at_a_glance_requires_past_or_historical_framing() -> None:
    text = "Western Plaguelands remains a contested frontier between crusaders and undead forces."
    assert any("lacks past-tense" in issue for issue in lint_at_a_glance(text))


def test_at_a_glance_allows_short_present_without_past() -> None:
    text = "A blighted frontier zone."
    assert not lint_at_a_glance(text)


def test_at_a_glance_accepts_past_zone_flavor() -> None:
    text = (
        "Once the breadbasket of Lordaeron, these lands were consumed by the Scourge and left blighted "
        "for years before recovery efforts began after the Cataclysm."
    )
    assert not lint_at_a_glance(text)


def test_history_rejects_short_present_body_with_historical_framing() -> None:
    sections = [
        {
            "heading": "Third War",
            "body": "During the Third War the Crusade maintains hold.",
        }
    ]
    assert any("dominant present tense" in issue for issue in lint_history_sections(sections))


def test_history_rejects_maintains_despite_framing() -> None:
    sections = [
        {
            "heading": "Scarlet era",
            "body": (
                "During the Third War, the region fell to the Scourge. The Scarlet Crusade maintains "
                "fortified holdings across the zone and continues to struggle against undead remnants."
            ),
        }
    ]
    assert any("dominant present tense" in issue for issue in lint_history_sections(sections))


def test_history_accepts_clean_past_body() -> None:
    sections = [
        {
            "heading": "Third War",
            "body": (
                "During the Third War, the Scourge under Arthas overran Western Plaguelands, ending "
                "Lordaeron's hold over its farmlands. Villages fell to plague and grain production collapsed."
            ),
        }
    ]
    assert not lint_history_sections(sections)


def test_history_accepts_past_body_outside_irregular_whitelist() -> None:
    # Legitimate past-tense narration that avoids the small irregular-verb list (razed, slaughtered,
    # fled, perished) must be recognized via generic -ed/-en morphology, not rejected for framing.
    sections = [
        {
            "heading": "Scourging",
            "body": (
                "The Scourge razed Andorhal and slaughtered its people. Survivors fled west as the "
                "plague perished crops and abandoned farmsteads dotted the ruined countryside."
            ),
        }
    ]
    assert not lint_history_sections(sections)


def test_history_flags_present_body_even_with_ed_adjective() -> None:
    # An -ed adjective ("sacred") satisfies the framing signal, but a genuinely present-dominant
    # section is still caught — now by the dominant-present check rather than the framing check.
    sections = [
        {
            "heading": "Now",
            "body": (
                "The sacred academy stands today and the Scourge controls its halls, where acolytes "
                "study dark arts and necromancers raise the dead to serve their masters."
            ),
        }
    ]
    assert any("dominant present tense" in issue for issue in lint_history_sections(sections))


def test_currently_requires_present_markers() -> None:
    text = "Formerly the grain heartland of the kingdom before the plague arrived years ago during the Third War."
    assert any("present-tense" in issue for issue in lint_currently(text))


def test_currently_accepts_present_zone_flavor() -> None:
    text = (
        "The Argent Crusade and Cenarion Circle work to heal the blighted soil while Horde and Alliance "
        "forces contest control of Andorhal."
    )
    assert not lint_currently(text)


def test_currently_allows_landmarks_but_rejects_location_dump() -> None:
    # Present-state lore legitimately names a couple of landmarks; it must not be rejected as a
    # "geography hub" the way it was (which dropped the real currently line to a canned fallback).
    lore = (
        "The Argent Crusade still holds Hearthglen, while Caer Darrow remains a school of necromancy "
        "under the Cult of the Damned."
    )
    assert not lint_currently(lore)
    # An actual comma-separated location dump is still rejected.
    dump = "Andorhal, Hearthglen, Darrowshire, Sorrowmill, and Felstone stand in ruin."
    assert any("location list dump" in issue for issue in lint_currently(dump))


def test_currently_rescue_stub_has_present_tense_markers() -> None:
    stub = (
        "Example Zone remains a contested frontier where crusaders and rival factions "
        "continue to clash over ruined strongholds."
    )
    assert not lint_currently(
        stub,
        zone_name="Example Zone",
        at_a_glance="Once a fertile region that was blighted during the Third War.",
    )


def test_currently_rejects_at_a_glance_overlap() -> None:
    at_a_glance = (
        "Once the breadbasket of Lordaeron, these lands were consumed by the Scourge and left blighted "
        "for years before recovery efforts began after the Cataclysm."
    )
    currently = (
        "Once the breadbasket of Lordaeron, these lands were consumed by the Scourge and left blighted "
        "for years before recovery efforts began after the Cataclysm and crusaders work to heal them."
    )
    overlap = token_jaccard(at_a_glance, currently)
    assert overlap >= AT_A_GLANCE_CURRENTLY_OVERLAP_THRESHOLD
    assert any(
        "overlaps at_a_glance" in issue
        for issue in lint_currently(currently, at_a_glance=at_a_glance)
    )
