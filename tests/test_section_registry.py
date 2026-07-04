"""Guard the section-label registry data file + the top-level-type + inheritance classifier.

The registry enumerates only recurring top-level section types; nested subsections inherit their
parent's class. These tests lock the inheritance model, the expansion backstop, and — the reason
the registry exists — that substring false-positives are gone (a nested subgroup inherits from its
structural parent, never from a keyword in its own name).
"""

from __future__ import annotations

from pipeline.common.section_registry import (
    is_narrative_section,
    normalize_section_label,
    section_content_class,
    section_temporality,
)


def test_edit_suffix_and_case_normalized() -> None:
    assert normalize_section_label("Cataclysm_edit") == "cataclysm"
    assert normalize_section_label("lead") == "lead"
    assert normalize_section_label("In_The_RPG_History_edit") == "in_the_rpg_history"


def test_top_level_types_classified() -> None:
    assert section_content_class("history_edit") == "narrative"
    assert section_content_class("biography_edit") == "narrative"
    assert section_content_class("organization_edit") == "roster"
    assert section_content_class("geography_edit") == "geography"
    assert section_content_class("abilities_edit") == "gameplay"
    assert section_content_class("external_links_edit") == "meta"
    assert section_content_class("lead") == "narrative"


def test_nested_subsection_inherits_parent() -> None:
    # Unknown event/facet subsections inherit their History/Biology/Organization parent.
    assert section_content_class("the_ashbringer_edit", "history_edit") == "narrative"
    assert section_content_class("nature_of_undeath_edit", "biology_edit") == "narrative"
    assert section_content_class("scarlet_onslaught_edit", "organization_edit") == "roster"


def test_substring_false_positives_are_dead() -> None:
    # These are the exact bugs the registry replaced: a keyword in the label must NOT decide class.
    assert section_content_class("crimson_legion_edit", "organization_edit") == "roster"
    assert section_content_class("lights_wrath_edit", "history_edit") == "narrative"
    assert section_content_class(
        "involvement_of_the_infinite_dragonflight_edit", "history_edit"
    ) == "narrative"


def test_expansion_backstop_classifies_top_level() -> None:
    # Normally nested under History (inherit); enumerated so they still classify when top-level.
    assert section_content_class("cataclysm_edit") == "narrative"
    assert section_content_class("legion_edit") == "narrative"
    assert section_temporality("legion_edit") == "expansion_era"


def test_unknown_with_unknown_parent_defaults_to_meta() -> None:
    assert section_content_class("totally_made_up_section_edit") == "meta"
    assert section_content_class("totally_made_up_edit", "also_unknown_edit") == "meta"


def test_in_the_rpg_prefix_is_non_canon() -> None:
    assert section_content_class("in_the_rpg_history_edit") == "non_canon"
    assert not is_narrative_section("in_the_rpg_history_edit")


def test_is_narrative_section_matches_class() -> None:
    assert is_narrative_section("cataclysm_edit", "biography_edit")
    assert not is_narrative_section("abilities_edit")
    assert not is_narrative_section("members_edit")  # roster is lore, but not narrative prose
