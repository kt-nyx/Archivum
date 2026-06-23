"""Tests for the content_role provenance taxonomy (Option A)."""

from __future__ import annotations

import pytest

from pipeline.common.content_role import CONTENT_ROLES, classify_content_role


@pytest.mark.parametrize(
    ("raw", "section_role", "parent", "expected"),
    [
        # Lead / identity prose.
        ("lead", "other", "", "lead"),
        ("introduction", "other", "", "lead"),
        # History narrative, including unrecognized subsections that must inherit
        # their parent section role (Fix B parity).
        ("history", "history", "", "lore_history"),
        ("background", "history", "", "lore_history"),
        ("background_edit", "history", "", "lore_history"),
        ("the_scourging", "other", "history", "lore_history"),
        ("fall_of_lilian_voss", "other", "background", "lore_history"),
        # A section literally named "Story" is narrative, not quest text.
        ("story", "other", "", "lore_history"),
        # Quest / storyline prose wins over the bare "story" marker.
        ("western_plaguelands_storyline", "quests_or_storyline", "", "quest_text"),
        ("questline", "quests_or_storyline", "", "quest_text"),
        # Encounter / boss mechanics.
        ("bosses", "instances_or_dungeons", "", "mechanics"),
        ("adventure_guide", "instances_or_dungeons", "", "mechanics"),
        ("strategy", "other", "", "mechanics"),
        # Descriptive prose.
        ("overview", "other", "", "description"),
        ("notable_characters", "notable_characters", "", "description"),
        ("geography", "maps_subregions", "", "description"),
        # RPG content stays quarantined regardless of inner header.
        ("in_the_rpg_history", "in_the_rpg", "", "in_the_rpg"),
        ("history", "history", "in_the_rpg", "in_the_rpg"),
        # Routing-enum fallback when the raw header is uninformative.
        ("", "instances_or_dungeons", "", "description"),
        ("", "maps_subregions", "", "description"),
        ("", "quests_or_storyline", "", "quest_text"),
        ("", "history", "", "lore_history"),
        ("", "other", "", "other"),
    ],
)
def test_classify_content_role(raw: str, section_role: str, parent: str, expected: str) -> None:
    result = classify_content_role(raw, section_role, parent)
    assert result == expected
    assert result in CONTENT_ROLES


def test_classifier_only_emits_known_roles() -> None:
    # Random-ish headers should never escape the controlled vocabulary.
    for raw in ("", "trivia", "patch_changes", "gallery", "references", "notes_and_trivia"):
        assert classify_content_role(raw, "other", "") in CONTENT_ROLES
