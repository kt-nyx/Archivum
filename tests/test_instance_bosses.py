from __future__ import annotations

from pipeline.discovery.instance_bosses import collect_boss_candidates, should_reject_boss_title


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
