"""Slice 14: section/heading classification migrated onto the section + expansion registries.

Pins the registry-derived replacements for the retired keyword/deny/allow lists and the two
maintainer constraints: no pilot theme words ("faculty") in shared code, and quest objectives/
description staying page-type lore.
"""

from __future__ import annotations

from pipeline.common.draft_vocab import era_section_role_tokens, expansion_release_order
from pipeline.common.retail import is_non_retail_title
from pipeline.common.section_registry import (
    expansion_era_display_names,
    is_bare_history_container,
    is_generic_history_heading,
    is_media_section,
    section_content_class,
    section_narrative_kind,
)
from pipeline.common.wiki_evidence_filters import (
    evidence_item_content_class,
    is_named_history_section,
)
from pipeline.discovery.instance_bosses import is_high_confidence_boss_section
from pipeline.discovery.quest_lore import _is_lore_section
from pipeline.generate.draft import temporal


def test_media_class_labels_excluded_from_lore() -> None:
    for label in ("exploring_azeroth", "novel", "comic", "manga", "later_appearances"):
        assert section_content_class(label) == "media"
        assert is_media_section(label)


def test_registry_extension_labels() -> None:
    assert section_content_class("maps_subregions") == "geography"
    assert section_content_class("resources") == "gameplay"
    assert section_narrative_kind("lore") == "history"
    assert section_narrative_kind("story") == "history"


def test_is_generic_history_heading_covers_containers_expansions_and_media() -> None:
    for generic in ("History", "Lore", "Background", "Overview", "Introduction", "Historical era"):
        assert is_generic_history_heading(generic)
    # Every expansion display name is generic, with or without the leading article.
    for expansion in ("Cataclysm", "Wrath of the Lich King", "Burning Crusade", "War Within"):
        assert is_generic_history_heading(expansion)
    assert is_generic_history_heading("Exploring Azeroth")  # media
    assert is_generic_history_heading("")
    # A distinctive event/thematic title is NOT generic.
    assert not is_generic_history_heading("The Scourging")
    assert not is_generic_history_heading("Battle for Andorhal")


def test_is_bare_history_container_keeps_expansions_distinct() -> None:
    assert is_bare_history_container("history")
    assert is_bare_history_container("background")
    # Expansion eras name a specific era, so they are not bare containers (usable as headings).
    assert not is_bare_history_container("cataclysm")
    assert not is_bare_history_container("the_scourging")


def test_is_named_history_section_uses_parent_inheritance() -> None:
    assert is_named_history_section("cataclysm_edit")
    assert not is_named_history_section("history_edit")  # bare container
    assert not is_named_history_section("geography_edit")
    # A distinctive subsection inherits narrative from its History parent.
    assert is_named_history_section("the_scourging_edit", "history")
    # ...but an adaptation subsection keeps its own media class and is not named history.
    assert not is_named_history_section("exploring_azeroth_edit", "history")


def test_evidence_item_content_class_inherits_via_canonical_role() -> None:
    scourging = {"raw_section_role": "scourging_of_lordaeron_edit", "section_role": "history"}
    assert evidence_item_content_class(scourging) == "narrative"
    exploring = {"raw_section_role": "exploring_azeroth_edit", "section_role": "history"}
    assert evidence_item_content_class(exploring) == "media"


def test_era_tokens_single_homed_on_expansion_release_order() -> None:
    assert era_section_role_tokens() == expansion_release_order()
    # The stale omissions are gone: newer expansions are now recognized as era sections.
    assert {"warlords", "midnight"} <= set(era_section_role_tokens())


def test_retail_parenthetical_derived_from_expansion_labels() -> None:
    assert "cataclysm" in expansion_era_display_names()
    assert is_non_retail_title("Scholomance (Classic)")
    assert is_non_retail_title("Foo (Burning Crusade)")
    assert is_non_retail_title("Foo (The Burning Crusade)")
    # "World of Warcraft" names the game, not a legacy variant.
    assert not is_non_retail_title("Bar (World of Warcraft)")


def test_quest_lore_keeps_journal_text_drops_apparatus() -> None:
    for role in ("description_edit", "objectives_edit", "quest_text_edit", "lead", "history_edit"):
        assert _is_lore_section(role)
    for role in ("rewards_edit", "quest_log_edit", "quest_progression_edit", "loot_edit", "notes_edit"):
        assert not _is_lore_section(role)


def test_temporal_entry_role_is_structural_not_a_theme_word() -> None:
    assert temporal._is_entry_role("lead")  # identity narrative
    assert temporal._is_entry_role("adventure_guide_edit")
    assert temporal._is_entry_role("dungeon_scholomance_edit")
    # "faculty" is a Scholomance-specific theme word, never a generic entry marker.
    assert not temporal._is_entry_role("scholomance_faculty_edit")
    assert not is_high_confidence_boss_section("scholomance_faculty")


def test_temporal_post_lore_is_media_and_classic_is_not_excluded_by_role() -> None:
    assert temporal._is_post_lore_role("exploring_azeroth_edit")
    assert temporal._is_excluded_role("in_the_rpg_history_edit")  # non_canon
    # Retail-era exclusion (Classic) moved to the category signal; the registry classes Classic as
    # narrative expansion-era prose, so a "classic" section role is not excluded here.
    assert not temporal._is_excluded_role("classic_edit")
