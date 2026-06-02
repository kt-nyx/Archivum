from __future__ import annotations

import pytest

from pipeline.discovery.instance_bosses import (
    collect_boss_candidates,
    mine_narrative_character_candidates,
    should_reject_boss_title,
)


def test_collect_boss_candidates_from_structured_links() -> None:
    candidates = collect_boss_candidates(
        section_blocks=[],
        instance_name="Scholomance",
        boss_pool_items=[],
        structured_links=[
            {"href": "/wiki/Darkmaster_Gandling", "label": "Darkmaster Gandling", "section_role": "denizens"},
            {"href": "/wiki/Jandice_Barov", "label": "Jandice Barov", "section_role": "bosses"},
        ],
    )
    names = {row.name for row in candidates}
    assert "Darkmaster Gandling" in names
    assert "Jandice Barov" in names


def test_structured_links_outside_roster_sections_are_ignored() -> None:
    candidates = collect_boss_candidates(
        section_blocks=[],
        instance_name="Scholomance",
        boss_pool_items=[],
        structured_links=[
            {"href": "/wiki/Some_Navbox_Page", "label": "Some Navbox Page", "section_role": "lead"},
            {"href": "/wiki/Patch_3.3.0", "label": "Patch 3.3.0", "section_role": "patch_changes"},
        ],
    )
    assert candidates == []


def test_structured_links_match_via_parent_section_role() -> None:
    candidates = collect_boss_candidates(
        section_blocks=[],
        instance_name="Icecrown Citadel",
        boss_pool_items=[],
        structured_links=[
            {
                "href": "/wiki/The_Lich_King",
                "label": "The Lich King",
                "section_role": "the_frozen_throne",
                "parent_section_role": "dungeon_denizens",
            },
        ],
    )
    names = {row.name for row in candidates}
    assert "The Lich King" in names


def test_collect_boss_candidates_from_encounter_section() -> None:
    section_blocks = [
        {
            "section_role": "adventurers",
            "text": "Bosses include [[/wiki/Archivist_Maelor|Archivist Maelor]] and [[/wiki/Warden_Voss|Warden Voss]].",
        }
    ]
    candidates = collect_boss_candidates(
        section_blocks=section_blocks,
        instance_name="Archive Vault",
        boss_pool_items=[],
    )
    names = {row.name for row in candidates}
    assert "Archivist Maelor" in names
    assert "Warden Voss" in names
    assert all(row.boss_id.startswith("character-") for row in candidates)


def test_boss_pool_items_merge_with_section_blocks() -> None:
    boss_pool_items = [
        {
            "snippet": "Encounter with /wiki/Custodian_Lira who guards the inner vault.",
            "section_role": "encounters",
            "source_id": "src-instance",
        }
    ]
    candidates = collect_boss_candidates(
        section_blocks=[],
        instance_name="Archive Vault",
        boss_pool_items=boss_pool_items,
    )
    assert len(candidates) == 1
    assert candidates[0].name == "Custodian Lira"


def test_profile_pool_matches_boss_slug_in_raw_html() -> None:
    from pipeline.discovery.instance_bosses import _profile_pool_for_boss

    html = '<table><tr><td><a href="/wiki/Darkmaster_Gandling"></a></td></tr></table>'
    pool = _profile_pool_for_boss(
        "Darkmaster Gandling",
        boss_pool_items=[
            {
                "snippet": html,
                "section_role": "scholomance_faculty",
                "source_id": "src-instance",
            }
        ],
        section_blocks=[],
    )
    assert len(pool) == 1
    assert pool[0]["source_id"] == "src-instance"


def test_rejects_geography_and_instance_self_titles() -> None:
    assert should_reject_boss_title("Archive Vault", instance_name="Archive Vault")
    assert should_reject_boss_title("Eastern Kingdoms", instance_name="Archive Vault")


def test_faculty_and_denizens_section_roles_match() -> None:
    from pipeline.discovery.instance_bosses import is_boss_section_role

    assert is_boss_section_role("scholomance_faculty")
    assert is_boss_section_role("denizens")
    assert is_boss_section_role("dungeon_journal")
    assert is_boss_section_role("dungeon_layout")
    assert is_boss_section_role("walkthrough")
    assert not is_boss_section_role("getting_there")


def test_expanded_roster_section_roles_match() -> None:
    from pipeline.discovery.instance_bosses import is_boss_section_role

    assert is_boss_section_role("inhabitants")
    assert is_boss_section_role("notable_characters")
    assert is_boss_section_role("npcs_bosses_and_monsters")
    assert is_boss_section_role("monsters")
    assert not is_boss_section_role("loot")
    assert not is_boss_section_role("related_achievements")


def test_section_block_matches_via_parent_section_role() -> None:
    section_blocks = [
        {
            "section_role": "the_rampart_of_skulls",
            "parent_section_role": "dungeon_denizens",
            "text": "Patrolling here: [[/wiki/Morgan_Dayblaze|Morgan Dayblaze]].",
        }
    ]
    candidates = collect_boss_candidates(
        section_blocks=section_blocks,
        instance_name="Icecrown Citadel",
        boss_pool_items=[],
    )
    names = {row.name for row in candidates}
    assert "Morgan Dayblaze" in names
    assert candidates[0].source_section_role == "dungeon_denizens"


def test_collect_boss_candidates_from_faculty_html_table() -> None:
    html = (
        '<table><tr><td><a href="/wiki/Darkmaster_Gandling">Darkmaster Gandling</a></td></tr>'
        '<tr><td><a href="/wiki/Jandice_Barov">Jandice Barov</a></td></tr></table>'
    )
    section_blocks = [{"section_role": "scholomance_faculty", "text": html}]
    candidates = collect_boss_candidates(
        section_blocks=section_blocks,
        instance_name="Scholomance",
        boss_pool_items=[],
    )
    names = {row.name for row in candidates}
    assert "Darkmaster Gandling" in names
    assert "Jandice Barov" in names


def test_wikitext_pipe_links_extract_boss_names() -> None:
    section_blocks = [
        {
            "section_role": "denizens",
            "text": "Faculty: [[Darkmaster_Gandling|Darkmaster Gandling]] and [[/wiki/Jandice_Barov|Jandice Barov]].",
        }
    ]
    candidates = collect_boss_candidates(
        section_blocks=section_blocks,
        instance_name="Scholomance",
        boss_pool_items=[],
    )
    names = {row.name for row in candidates}
    assert "Darkmaster Gandling" in names
    assert "Jandice Barov" in names


def test_rejects_section_header_link_titles() -> None:
    section_blocks = [
        {
            "section_role": "adventurers",
            "text": 'See [[/wiki/Bosses|Bosses]] and [[/wiki/Adventurers|Adventurers]] for details.',
        }
    ]
    candidates = collect_boss_candidates(
        section_blocks=section_blocks,
        instance_name="Archive Vault",
        boss_pool_items=[],
    )
    assert candidates == []


@pytest.mark.parametrize(
    "instance_name,role",
    [
        ("Razorfen Kraul", "razorfen_kraul"),  # plain eponymous lead bucket
        ("Gruul's Lair", "gruul_s_lair"),  # apostrophe normalization
        ("Aberrus, the Shadowed Crucible", "aberrus_the_shadowed_crucible"),  # comma
        ("The Culling of Stratholme", "culling_of_stratholme"),  # leading article dropped
    ],
)
def test_narrative_fallback_mines_eponymous_lead_bucket(instance_name: str, role: str) -> None:
    """The MediaWiki <h1> title is slugified into a section role equal to the page
    name; that lead bucket (where many pages list bosses/lore) must be mined by the
    narrative fallback even across apostrophe/comma/"The " normalization differences."""
    blocks = [
        {
            "section_role": role,
            "parent_section_role": role,
            "text": (
                "The instance is ruled by [[/wiki/Warlord_Ramtusk|Warlord Ramtusk]], "
                "who commands the defenders. Warlord Ramtusk is the marquee threat here."
            ),
        }
    ]
    candidates = mine_narrative_character_candidates(
        blocks, instance_name=instance_name, max_count=10
    )
    names = {row.name for row in candidates}
    assert "Warlord Ramtusk" in names, f"{instance_name}: eponymous lead not mined ({names})"


def test_valid_boss_names_from_pool_items() -> None:
    from pipeline.discovery.instance_bosses import valid_boss_names_from_pool_items

    items = [
        {
            "snippet": "Encounter /wiki/Darkmaster_Gandling in the faculty wing.",
            "section_role": "scholomance_faculty",
            "source_id": "src-instance",
        }
    ]
    names = valid_boss_names_from_pool_items(items, instance_name="Scholomance")
    assert "darkmaster gandling" in names
