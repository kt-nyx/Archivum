from __future__ import annotations

from pipeline.common.text_sim import token_jaccard
from pipeline.generate.draft.prose_lint import (
    AT_A_GLANCE_CURRENTLY_OVERLAP_THRESHOLD,
    has_player_directive,
    has_player_meta_reference,
    lint_at_a_glance,
    lint_currently,
    lint_history_sections,
    split_sentences,
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


def test_at_a_glance_accepts_atmospheric_essence_gold_shape() -> None:
    # The target register: an all-participle essence caption with no finite past-tense narration.
    # Its history lives in adjectives ("plague-scarred", "fallen", "ruined", "haunted", "rotted").
    text = (
        "The plague-scarred heartland of fallen Lordaeron, where ruined farms and haunted towns bear "
        "the legacy of the Scourge, even as life slowly returns to the rotted land."
    )
    assert not lint_at_a_glance(text)


def test_at_a_glance_allows_present_dominant() -> None:
    text = (
        "The Western Plaguelands is a blighted but reclaimed frontier where the Argent Crusade holds "
        "the line against the lingering Scourge."
    )
    assert not lint_at_a_glance(text)


def test_at_a_glance_rejects_past_tense_narration() -> None:
    # A caption whose verb spine narrates the past ("were consumed", "left blighted") reads as a
    # history blurb, not an essence caption.
    text = (
        "Once the breadbasket of Lordaeron, these lands were consumed by the Scourge and left blighted "
        "for years before recovery efforts began after the Cataclysm."
    )
    assert any("past-tense narration" in issue for issue in lint_at_a_glance(text))


def test_at_a_glance_allows_short_present_without_past() -> None:
    text = "A blighted frontier zone."
    assert not lint_at_a_glance(text)


def test_at_a_glance_accepts_present_identity_with_past_context() -> None:
    # A light "once X, it is now Y" pivot is still fine — mixed tense (not past-dominant) passes.
    text = (
        "Once a fertile heartland, the region is now a slowly healing frontier still marked by old "
        "scars of war."
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


def test_history_final_section_may_be_present_state_bridge() -> None:
    # The final section of a multi-section history is the present-state bridge: it may narrate the
    # zone's current, ongoing condition in present tense while earlier sections stay past.
    sections = [
        {
            "heading": "Scourging",
            "body": (
                "During the Third War, the Scourge razed Andorhal and the Plague of Undeath spread "
                "across the farmlands, and the dead rose to serve the Lich King."
            ),
        },
        {
            "heading": "Cataclysm Renewal",
            "body": (
                "The plague is largely dispelled and life returns to the region, yet war still rages "
                "in Andorhal and Gahrron's Withering, where the countryside remains contested."
            ),
        },
    ]
    assert not lint_history_sections(sections)


def test_history_present_bridge_rejects_player_meta_reference() -> None:
    # Regression (test-run-wpl-16): the present-state bridge is exempt from the tense checks but must
    # still stay in-world. A "by the player's arrival" anchor breaks the frame and must be flagged
    # even though it sits in the final, present-tense-allowed section.
    sections = [
        {
            "heading": "Scourging",
            "body": (
                "During the Third War, the Scourge razed Andorhal and the Plague of Undeath spread "
                "across the farmlands, and the dead rose to serve the Lich King."
            ),
        },
        {
            "heading": "Hearthglen Restored",
            "body": (
                "By the player's arrival, the region is still defined by the aftermath of the plague "
                "and the stronghold built in its shadow."
            ),
        },
    ]
    issues = lint_history_sections(sections)
    assert any("in-world frame" in issue and "history_sections[1]" in issue for issue in issues)


def test_history_keeps_canonical_heroes_and_champions() -> None:
    # The in-world guard targets "player" / second person only; heroes, champions, and adventurers
    # are canonical actors and must not be flagged.
    sections = [
        {
            "heading": "Cauldron Disruption",
            "body": (
                "Heroes of the Alliance and Horde, serving the Argent Dawn, defeated the Cauldron "
                "Lords and turned the plague cauldrons against the Scourge."
            ),
        },
        {
            "heading": "Hearthglen Restored",
            "body": (
                "After the war, the Argent Crusade reclaimed Hearthglen and made it a training ground "
                "for the crusaders who followed."
            ),
        },
    ]
    assert not lint_history_sections(sections)


def test_has_player_meta_reference_matches_meta_not_canonical_actors() -> None:
    assert has_player_meta_reference("By the player's arrival, the keep still stands.")
    assert has_player_meta_reference("The Scourge waits for you in the halls.")
    assert not has_player_meta_reference("Champions of the Argent Crusade cleansed the land.")
    assert not has_player_meta_reference("Adventurers and heroes battled the undead here.")


def test_history_non_final_present_section_is_still_flagged() -> None:
    # The present-tense exemption is only for the final section; an earlier present-tense section is
    # still rejected, so background eras can never be present-tensed.
    sections = [
        {
            "heading": "Now",
            "body": (
                "The sacred academy stands today and the Scourge controls its halls, where acolytes "
                "study dark arts and necromancers raise the dead to serve their masters."
            ),
        },
        {
            "heading": "Aftermath",
            "body": (
                "After the war, the Argent Crusade reclaimed the keep and rebuilt its walls over the "
                "years that followed."
            ),
        },
    ]
    issues = lint_history_sections(sections)
    assert any("dominant present tense" in issue and "history_sections[0]" in issue for issue in issues)
    assert not any("history_sections[1]" in issue for issue in issues)


def test_player_directive_catches_imperatives_outside_any_verb_list() -> None:
    # Slice 5: imperative detection is the grammar substrate's clause shape, not an opener
    # whitelist — "purge" and "cleanse" were never in the deleted list. In-universe
    # present-tense prose with the same verbs is not a directive.
    assert has_player_directive(
        "Purge the academy of its necromancers and cleanse the cauldrons of Andorhal."
    )
    assert not has_player_directive("The Argent Crusade cleanses the cauldrons of Andorhal.")
    issues = lint_currently(
        "Purge the academy of its necromancers and cleanse the cauldrons of Andorhal."
    )
    assert any("player-facing quest directive" in issue for issue in issues)


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


def test_split_sentences_respects_abbreviations_and_adp_dates() -> None:
    # Slice 8: model-derived boundaries — the old regex split after every ".", severing
    # abbreviations. Positions are not exposed here; lint/trim paths only need the texts.
    assert split_sentences("The town of St. Albus fell to the Scourge. It never recovered.") == [
        "The town of St. Albus fell to the Scourge.",
        "It never recovered.",
    ]
    assert split_sentences("") == []
