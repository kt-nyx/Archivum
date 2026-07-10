from __future__ import annotations

from pathlib import Path

from pipeline.discovery.instance_bosses import (
    BossCandidate,
    cap_pool_for_llm_prompt,
    classify_character_role,
    collect_boss_candidates,
    collect_character_pool,
    deterministic_pool_order,
    is_high_confidence_boss_section,
    must_include_key_character_names,
    prefilter_character_pool,
    should_reject_boss_title,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "instance"


def test_collect_boss_candidates_from_structured_links() -> None:
    candidates = collect_boss_candidates(
        section_blocks=[],
        instance_name="Scholomance",
        boss_pool_items=[],
        structured_links=[
            {
                "href": "/wiki/Darkmaster_Gandling",
                "label": "Darkmaster Gandling",
                "section_role": "denizens",
            },
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


def test_rejects_only_generic_hygiene_and_instance_self_titles() -> None:
    assert should_reject_boss_title("Archive Vault", instance_name="Archive Vault")
    assert not should_reject_boss_title("Remote Province", instance_name="Archive Vault")


def test_place_like_titles_remain_leads_until_entity_kind_admission() -> None:
    assert not should_reject_boss_title("Example Antechamber")
    assert not should_reject_boss_title("Survey Platform")
    assert not should_reject_boss_title("Named Curator")


def _named_candidate(name: str) -> BossCandidate:
    return BossCandidate(
        boss_id=f"character-{name.lower().replace(' ', '-')}",
        name=name,
        wiki_url=f"https://warcraft.wiki.gg/wiki/{name.replace(' ', '_')}",
        source_section_role="bosses",
    )


def test_prefilter_drops_bare_surname_shared_with_full_name() -> None:
    # #4: "Barov" is a family/surname, not an individual NPC; it must be dropped because a
    # full-name character ("Jandice Barov" / "Lord Alexei Barov") carries that surname.
    pool = [
        _named_candidate("Jandice Barov"),
        _named_candidate("Lord Alexei Barov"),
        _named_candidate("Barov"),
        _named_candidate("Barov family"),
        _named_candidate("Rattlegore"),
    ]
    kept = {c.name for c in prefilter_character_pool(pool, instance_name="Scholomance")}
    assert "Barov" not in kept
    assert "Barov family" not in kept
    # Full-name family members and mononymous bosses survive.
    assert {"Jandice Barov", "Lord Alexei Barov", "Rattlegore"} <= kept


def test_prefilter_keeps_mononym_without_matching_surname() -> None:
    pool = [_named_candidate("Rattlegore"), _named_candidate("Lilian Voss")]
    kept = {c.name for c in prefilter_character_pool(pool, instance_name="Scholomance")}
    assert kept == {"Rattlegore", "Lilian Voss"}


def test_boss_title_gate_uses_source_taxonomy_not_a_curated_title_list() -> None:
    # Slice 1 removed title/race/species denylists. Generic names remain leads
    # until Slice 3's instance-participation + entity-kind admission resolves them.
    assert not should_reject_boss_title("Example Creature Type")
    assert not should_reject_boss_title("Example Landmark")


def test_boss_and_denizens_section_roles_match() -> None:
    from pipeline.discovery.instance_bosses import is_boss_section_role

    # Slice 14: instance-entity detection is structural, never an instance-specific theme word.
    # A school-themed "Faculty" heading is NOT a hardcoded boss token; Scholomance's roster reaches
    # boss_pool via its generic per-dungeon table ("dungeon_scholomance") / adventure guide instead.
    assert not is_high_confidence_boss_section("scholomance_faculty")
    assert not is_boss_section_role("scholomance_faculty")
    assert is_high_confidence_boss_section("dungeon_scholomance")
    assert is_boss_section_role("dungeon_scholomance")
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


def test_direct_participant_presence_requires_roster_shaped_section() -> None:
    from pipeline.discovery.instance_bosses import is_direct_instance_participant_section

    assert is_direct_instance_participant_section("encounters")
    assert is_direct_instance_participant_section("dungeon_journal")
    assert is_direct_instance_participant_section("dungeon_example_vault")
    assert is_direct_instance_participant_section("denizens")
    assert not is_direct_instance_participant_section("adventure_guide")
    assert not is_direct_instance_participant_section("other_interesting_bosses")


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


def test_collect_boss_candidates_from_dungeon_table_html() -> None:
    html = (
        '<table><tr><td><a href="/wiki/Darkmaster_Gandling">Darkmaster Gandling</a></td></tr>'
        '<tr><td><a href="/wiki/Jandice_Barov">Jandice Barov</a></td></tr></table>'
    )
    section_blocks = [{"section_role": "dungeon_scholomance", "text": html}]
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


def test_section_header_links_remain_untyped_leads_until_instance_admission() -> None:
    section_blocks = [
        {
            "section_role": "adventurers",
            "text": "See [[/wiki/Bosses|Bosses]] and [[/wiki/Adventurers|Adventurers]] for details.",
        }
    ]
    candidates = collect_boss_candidates(
        section_blocks=section_blocks,
        instance_name="Archive Vault",
        boss_pool_items=[],
    )
    assert {candidate.name for candidate in candidates} == {"Bosses", "Adventurers"}


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


def test_classify_role_is_always_uncertain_deterministically() -> None:
    # Slice 10 (H-3): role is a semantic LLM judgment. The deterministic classifier no longer
    # keyword-guesses from boss sections or descriptor phrases — even a "final boss of" roster
    # entry or a vendor descriptor stays honestly uncertain, deferred to the LLM classifier.
    for role_section, snippets in (
        ("bosses", ["Loken is the final boss of the instance."]),
        ("denizens", ["Provisioner Stonepath is a merchant and reagent vendor."]),
        ("npcs", ["Captain Helaina must be rescued and then fights alongside adventurers."]),
        ("narrative_fallback", ["Mysterious Figure is mentioned once."]),
    ):
        cand = _candidate("Someone", role_section, snippets)
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


def test_deterministic_pool_order_uses_mention_frequency() -> None:
    pool = [
        BossCandidate(
            boss_id="character-loken",
            name="Loken",
            wiki_url="https://warcraft.wiki.gg/wiki/Loken",
            source_section_role="bosses",
        ),
        BossCandidate(
            boss_id="character-thorim",
            name="Thorim",
            wiki_url="https://warcraft.wiki.gg/wiki/Thorim",
            source_section_role="denizens",
        ),
    ]
    ordered = deterministic_pool_order(
        pool,
        narrative_text="Thorim Thorim speaks while Loken is named once.",
    )
    assert ordered[0] == "Thorim"


def test_deterministic_pool_order_tiebreaks_on_section_weight() -> None:
    pool = [
        BossCandidate(
            boss_id="character-trash",
            name="Trash Mob",
            wiki_url="https://warcraft.wiki.gg/wiki/Trash_Mob",
            source_section_role="denizens",
        ),
        BossCandidate(
            boss_id="character-marquee",
            name="Marquee Boss",
            wiki_url="https://warcraft.wiki.gg/wiki/Marquee_Boss",
            source_section_role="dungeon_journal",
        ),
    ]
    ordered = deterministic_pool_order(pool, narrative_text="")
    assert ordered[0] == "Marquee Boss"


def test_high_confidence_boss_section_tokens() -> None:
    assert is_high_confidence_boss_section("dungeon_journal")
    assert is_high_confidence_boss_section("encounters")
    # Authoritative boss-roster section: the per-dungeon boss table (structural, not a theme word).
    assert is_high_confidence_boss_section("dungeon_scholomance")
    # A school-themed "Faculty" heading is not a hardcoded boss token (Slice 14).
    assert not is_high_confidence_boss_section("faculty")
    assert not is_high_confidence_boss_section("scholomance_faculty")
    # Trash/denizen rosters are never the boss floor (a random skeleton is not a boss).
    assert not is_high_confidence_boss_section("denizens")
    assert not is_high_confidence_boss_section("dungeon_denizens")


def test_collect_character_pool_from_dungeon_table_html() -> None:
    html = (FIXTURES / "scholomance_faculty_section.html").read_text(encoding="utf-8")
    pool = collect_character_pool(
        section_blocks=[{"section_role": "dungeon_scholomance", "text": html}],
        instance_name="Scholomance",
    )
    names = {row.name for row in pool}
    assert "Darkmaster Gandling" in names
    assert "Jandice Barov" in names


def test_collect_character_pool_keeps_untyped_history_links_as_unadmitted_leads() -> None:
    pool = collect_character_pool(
        section_blocks=[],
        instance_name="Scholomance",
        history_pool=[
            {
                "snippet": (
                    "House Barov lingered as [[/wiki/Lord_Alexei_Barov|Lord Alexei Barov]] "
                    "within the academy vaults."
                ),
                "section_role": "history_digest",
                "source_id": "src-instance",
            }
        ],
    )
    names = {row.name for row in pool}
    assert "Lord Alexei Barov" in names


def test_prefilter_character_pool_leaves_entity_kind_to_admission() -> None:
    pool = [
        BossCandidate(
            boss_id="character-caer-darrow",
            name="Caer Darrow",
            wiki_url="https://warcraft.wiki.gg/wiki/Caer_Darrow",
            source_section_role="denizens",
        ),
        BossCandidate(
            boss_id="character-darkmaster-gandling",
            name="Darkmaster Gandling",
            wiki_url="https://warcraft.wiki.gg/wiki/Darkmaster_Gandling",
            source_section_role="bosses",
        ),
    ]
    filtered = prefilter_character_pool(pool, instance_name="Scholomance")
    names = {row.name for row in filtered}
    assert "Caer Darrow" in names
    assert "Darkmaster Gandling" in names


def test_must_include_from_boss_class_boss_pool() -> None:
    boss_pool = [
        {
            "snippet": "Final encounter: /wiki/Darkmaster_Gandling",
            "section_role": "dungeon_journal",
            "source_id": "src-instance",
        }
    ]
    pool = collect_character_pool(
        section_blocks=[],
        instance_name="Scholomance",
        boss_pool_items=boss_pool,
    )
    pool = prefilter_character_pool(pool, instance_name="Scholomance")
    must_include = must_include_key_character_names(
        boss_pool_items=boss_pool,
        pool=pool,
        instance_name="Scholomance",
    )
    assert must_include == ["Darkmaster Gandling"]


def test_must_include_floors_dungeon_table_boss_pool() -> None:
    # The per-dungeon boss table is authoritative, so a boss listed there floors deterministically
    # (this is what makes the full Scholomance boss roster the cast without LLM padding).
    boss_pool = [
        {
            "snippet": "Boss wing: /wiki/Darkmaster_Gandling",
            "section_role": "dungeon_scholomance",
            "source_id": "src-instance",
        }
    ]
    pool = collect_character_pool(
        section_blocks=[],
        instance_name="Scholomance",
        boss_pool_items=boss_pool,
    )
    pool = prefilter_character_pool(pool, instance_name="Scholomance")
    must_include = must_include_key_character_names(
        boss_pool_items=boss_pool,
        pool=pool,
        instance_name="Scholomance",
    )
    assert must_include == ["Darkmaster Gandling"]


def test_must_include_floors_infobox_roster_boss() -> None:
    # Cause 1b: a boss whose only link the section classifier under-labels (it sits in a
    # denizen/trash section) is still floored when the instance infobox's boss roster names it.
    boss_pool = [
        {
            "snippet": "Roaming the halls: /wiki/Rattlegore",
            "section_role": "dungeon_denizens",
            "source_id": "src-instance",
        }
    ]
    pool = collect_character_pool(
        section_blocks=[],
        instance_name="Scholomance",
        boss_pool_items=boss_pool,
    )
    pool = prefilter_character_pool(pool, instance_name="Scholomance")
    # Without the infobox, a denizen-section name is not a boss.
    assert (
        must_include_key_character_names(
            boss_pool_items=boss_pool, pool=pool, instance_name="Scholomance"
        )
        == []
    )
    # The infobox boss roster is authoritative and floors it (matched to a discovered candidate).
    infobox = {
        "Bosses": "Bosses Instructor Chillheart Rattlegore Darkmaster Gandling",
        "Type": "Dungeon",
    }
    floored = must_include_key_character_names(
        boss_pool_items=boss_pool,
        pool=pool,
        instance_name="Scholomance",
        infobox=infobox,
    )
    assert "Rattlegore" in floored


def test_must_include_infobox_never_mints_uncrawled_boss() -> None:
    # The infobox floor only matches names the pool already discovered; a boss named only in the
    # infobox text (never crawled as a candidate) is not conjured into the cast.
    boss_pool = [
        {
            "snippet": "Final encounter: /wiki/Darkmaster_Gandling",
            "section_role": "dungeon_journal",
            "source_id": "src-instance",
        }
    ]
    pool = collect_character_pool(
        section_blocks=[],
        instance_name="Scholomance",
        boss_pool_items=boss_pool,
    )
    pool = prefilter_character_pool(pool, instance_name="Scholomance")
    infobox = {"Bosses": "Bosses Darkmaster Gandling Doctor Theolen Krastinov"}
    floored = must_include_key_character_names(
        boss_pool_items=boss_pool,
        pool=pool,
        instance_name="Scholomance",
        infobox=infobox,
    )
    assert floored == ["Darkmaster Gandling"]  # Krastinov never discovered -> not floored


def test_must_include_excludes_denizen_only_boss_pool() -> None:
    # A name appearing only in the denizens trash roster (a random skeleton) is never floored.
    boss_pool = [
        {
            "snippet": "Roaming the halls: /wiki/Grandmaster_Architect_Holmberg",
            "section_role": "dungeon_denizens",
            "source_id": "src-instance",
        }
    ]
    pool = collect_character_pool(
        section_blocks=[],
        instance_name="Scholomance",
        boss_pool_items=boss_pool,
    )
    pool = prefilter_character_pool(pool, instance_name="Scholomance")
    must_include = must_include_key_character_names(
        boss_pool_items=boss_pool,
        pool=pool,
        instance_name="Scholomance",
    )
    assert must_include == []


def test_must_include_skips_names_not_in_pool() -> None:
    boss_pool = [
        {
            "snippet": "Journal lists /wiki/Rattlegore",
            "section_role": "dungeon_journal",
            "source_id": "src-instance",
        }
    ]
    # Pool candidate has a non-boss-class section role, so neither the boss_pool link
    # (Rattlegore, not in pool) nor the candidate's own role floors anything.
    pool = [
        BossCandidate(
            boss_id="character-darkmaster-gandling",
            name="Darkmaster Gandling",
            wiki_url="https://warcraft.wiki.gg/wiki/Darkmaster_Gandling",
            source_section_role="history_digest",
        ),
    ]
    must_include = must_include_key_character_names(
        boss_pool_items=boss_pool,
        pool=pool,
        instance_name="Scholomance",
    )
    assert must_include == []


def test_must_include_floors_candidate_with_boss_class_section_role() -> None:
    # Source 2: a pool candidate whose own discovery section role is a high-confidence
    # boss-class section is floored even when boss_pool snippets carry no /wiki/ links.
    pool = [
        BossCandidate(
            boss_id="character-darkmaster-gandling",
            name="Darkmaster Gandling",
            wiki_url="https://warcraft.wiki.gg/wiki/Darkmaster_Gandling",
            source_section_role="adventure_guide_edit",
        ),
        BossCandidate(
            boss_id="character-bystander",
            name="Bystander",
            wiki_url="https://warcraft.wiki.gg/wiki/Bystander",
            source_section_role="narrative_fallback",
        ),
    ]
    must_include = must_include_key_character_names(
        boss_pool_items=[{"snippet": "No links here.", "section_role": "other"}],
        pool=pool,
        instance_name="Scholomance",
    )
    assert must_include == ["Darkmaster Gandling"]


def test_cap_pool_for_llm_prompt_includes_must_includes() -> None:
    pool = [
        BossCandidate(
            boss_id=f"character-trash-{index}",
            name=f"Trash Mob {index}",
            wiki_url=f"https://warcraft.wiki.gg/wiki/Trash_Mob_{index}",
            source_section_role="denizens",
        )
        for index in range(50)
    ]
    pool.append(
        BossCandidate(
            boss_id="character-marquee-boss",
            name="Marquee Boss",
            wiki_url="https://warcraft.wiki.gg/wiki/Marquee_Boss",
            source_section_role="bosses",
            profile_pool=[
                {
                    "snippet": "Marquee Boss is the final boss of the instance.",
                    "section_role": "bosses",
                }
            ],
        )
    )
    pool.append(
        BossCandidate(
            boss_id="character-floor-boss",
            name="Floor Boss",
            wiki_url="https://warcraft.wiki.gg/wiki/Floor_Boss",
            source_section_role="dungeon_journal",
        )
    )
    capped = cap_pool_for_llm_prompt(
        pool,
        must_include_names=["Floor Boss", "Marquee Boss"],
        limit=40,
    )
    capped_names = {row.name for row in capped}
    assert "Floor Boss" in capped_names
    assert "Marquee Boss" in capped_names
    assert len(capped) == 40
