from __future__ import annotations

from pipeline.discovery.instance_bosses import (
    BossCandidate,
    classify_character_role,
    collect_boss_candidates,
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


def _candidate(name: str, role: str, snippets: list[str]) -> BossCandidate:
    cand = BossCandidate(
        boss_id=f"character-{name.lower().replace(' ', '-')}",
        name=name,
        wiki_url=f"https://warcraft.wiki.gg/wiki/{name.replace(' ', '_')}",
        source_section_role=role,
    )
    cand.profile_pool = [{"snippet": text} for text in snippets]
    return cand


def test_classify_role_enemy_from_boss_section() -> None:
    cand = _candidate("Loken", "bosses", ["Loken is the final boss of the instance."])
    role, reason = classify_character_role(cand, instance_name="Halls of Lightning")
    assert role == "enemy"
    assert reason


def test_classify_role_neutral_from_vendor_descriptor() -> None:
    # Listed in a denizens roster but the evidence marks them as a vendor.
    cand = _candidate(
        "Provisioner Stonepath",
        "denizens",
        ["Provisioner Stonepath is a merchant and reagent vendor stationed at the entrance."],
    )
    role, _reason = classify_character_role(cand, instance_name="Some Instance")
    assert role == "neutral"


def test_classify_role_ally_from_rescue_descriptor() -> None:
    cand = _candidate(
        "Captain Helaina",
        "npcs",
        ["Captain Helaina must be rescued and then fights alongside the adventurers."],
    )
    role, _reason = classify_character_role(cand, instance_name="Some Instance")
    assert role == "ally"


def test_classify_role_uncertain_without_signal() -> None:
    cand = _candidate(
        "Mysterious Figure", "narrative_fallback", ["Mysterious Figure is mentioned once."]
    )
    role, reason = classify_character_role(cand, instance_name="Some Instance")
    assert role == "uncertain"
    assert reason == "no_signal"


def test_significance_orders_bosses_ahead_of_trash() -> None:
    section_blocks = [
        {
            "section_role": "bosses",
            "text": '<a href="/wiki/Marquee_Boss">Marquee Boss</a>',
        },
        {
            "section_role": "dungeon_denizens",
            "text": '<a href="/wiki/Trash_Mob">Trash Mob</a>',
        },
    ]
    boss_pool_items = [
        {
            "snippet": "Marquee Boss is the final boss. Marquee Boss commands the keep.",
            "section_role": "bosses",
            "source_id": "src",
        }
    ]
    candidates = collect_boss_candidates(
        section_blocks=section_blocks,
        instance_name="Test Keep",
        boss_pool_items=boss_pool_items,
    )
    names = [c.name for c in candidates]
    assert names[0] == "Marquee Boss"
    assert candidates[0].significance > candidates[-1].significance


def test_redirect_alias_links_collapse_to_one_candidate() -> None:
    # Two roster links (a redirect alias and its canonical) carry the same
    # canonical_path from ingest resolution and must collapse into one entry.
    structured_links = [
        {
            "href": "/wiki/Razuvious",
            "label": "Razuvious",
            "section_role": "bosses",
            "canonical_path": "Instructor_Razuvious",
            "page_id": 4242,
        },
        {
            "href": "/wiki/Instructor_Razuvious",
            "label": "Instructor Razuvious",
            "section_role": "bosses",
            "canonical_path": "Instructor_Razuvious",
            "page_id": 4242,
        },
    ]
    candidates = collect_boss_candidates(
        section_blocks=[],
        instance_name="Naxxramas",
        boss_pool_items=[],
        structured_links=structured_links,
    )
    assert len(candidates) == 1
    assert candidates[0].name == "Instructor Razuvious"
