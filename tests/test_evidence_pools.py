from __future__ import annotations



from pipeline.discovery.enrich import _build_evidence_packs



ZONE_ID = "zone-example"

ZONE_NAME = "Example Zone"





def _example_zone_snapshots() -> list[dict]:

    seed_blocks = []

    for index in range(40):

        seed_blocks.append(

            {

                "section_role": "history",

                "text": f"Historical arc detail paragraph {index} about reclamation and crusader campaigns.",

            }

        )

    seed_blocks.append({"section_role": "lead", "text": "Example Zone overview lead paragraph."})

    seed_blocks.append({"section_role": "lead", "text": "Second lead paragraph for at-a-glance context."})

    seed_blocks.append({"section_role": "quests_edit", "text": "Current quest activity around the capital district."})

    seed_blocks.append(

        {"section_role": "cataclysm_edit", "text": "Cataclysm recovery efforts continue across the zone."}

    )

    seed_blocks.append({"section_role": "geography_edit", "text": "Geography should not appear in history digest."})



    auxiliary_other_blocks = [

        {"section_role": "other", "text": f"Auxiliary noise snippet {index} from quest page fetch."}

        for index in range(60)

    ]



    return [

        {

            "entity_id": ZONE_ID,

            "entity_type": "zone",

            "name": ZONE_NAME,

            "source_id": "src-zone",

            "url": "https://warcraft.wiki.gg/wiki/Example_Zone",

            "section_blocks": seed_blocks,

            "auxiliary_role": "",

        },

        {

            "entity_id": ZONE_ID,

            "entity_type": "zone",

            "name": ZONE_NAME,

            "source_id": "src-storyline",

            "url": "https://warcraft.wiki.gg/wiki/Example_Zone_storyline",

            "section_blocks": [{"section_role": "part_1", "text": "Storyline overview for the zone arc."}],

            "auxiliary_role": "storyline",

            "page_title": "Example Zone storyline",

        },

        {

            "entity_id": ZONE_ID,

            "entity_type": "zone",

            "name": ZONE_NAME,

            "source_id": "src-quest-1",

            "url": "https://warcraft.wiki.gg/wiki/Quest_Alpha",

            "section_blocks": auxiliary_other_blocks,

            "auxiliary_role": "quest",

            "page_title": "Quest Alpha",

        },

    ]





def test_scoped_evidence_pools_exclude_auxiliary_other_from_prose_fields() -> None:

    packs = _build_evidence_packs(_example_zone_snapshots(), "run-test")

    field_names = {str(row.get("field_name", "")) for row in packs}

    assert "history_digest" in field_names

    assert "at_a_glance_input" in field_names

    assert "currently_input" in field_names

    assert "questline_pool" in field_names



    history_packs = [row for row in packs if row.get("field_name") == "history_digest"]

    assert history_packs

    assert all(

        (row.get("build_meta") or {}).get("source_kind") == "seed"

        for row in history_packs

    )

    assert all(

        (row.get("build_meta") or {}).get("subject_zone_id") == ZONE_ID

        for row in history_packs

    )

    history_snippets = [

        item["snippet"]

        for row in history_packs

        for item in row.get("evidence_items", [])

    ]

    assert not any("Geography should not appear" in snippet for snippet in history_snippets)

    assert not any("Auxiliary noise snippet" in snippet for snippet in history_snippets)

    questline_packs = [row for row in packs if row.get("field_name") == "questline_pool"]

    questline_snippets = [

        item["snippet"]

        for row in questline_packs

        for item in row.get("evidence_items", [])

    ]

    assert not any("Auxiliary noise snippet" in snippet for snippet in questline_snippets)



    glance_packs = [row for row in packs if row.get("field_name") == "at_a_glance_input"]

    glance_items = sum(len(row.get("evidence_items", [])) for row in glance_packs)

    assert glance_items <= 50

    assert glance_items >= 42

    assert all(

        (row.get("build_meta") or {}).get("source_kind") == "seed"

        for row in glance_packs

    )



    currently_packs = [row for row in packs if row.get("field_name") == "currently_input"]

    currently_snippets = [

        item["snippet"]

        for row in currently_packs

        for item in row.get("evidence_items", [])

    ]

    assert any("capital district" in snippet for snippet in currently_snippets)

    assert any("Cataclysm recovery" in snippet for snippet in currently_snippets)


def test_geography_input_and_rpg_exclusion() -> None:
    snapshots = [
        {
            "entity_id": ZONE_ID,
            "entity_type": "zone",
            "name": ZONE_NAME,
            "source_id": "src-zone",
            "url": "https://warcraft.wiki.gg/wiki/Example_Zone",
            "section_blocks": [
                {"section_role": "geography_edit", "text": "Example Zone sits on the Eastern Kingdoms continent."},
                {
                    "section_role": "in_the_rpg_geography_edit",
                    "text": "The Western Plaguelands is a flat country dotted with abandoned farms in Lordaeron.",
                },
                {
                    "section_role": "in_the_rpg_history",
                    "text": "This section contains information from the Warcraft RPG and is non-canon.",
                },
                {
                    "section_role": "history",
                    "text": (
                        "The region suffered catastrophic collapse before long-term military campaigns "
                        "began restoring order across the ruined frontier and broken keeps."
                    ),
                },
            ],
            "auxiliary_role": "",
        }
    ]
    packs = _build_evidence_packs(snapshots, "run-test")
    field_names = {str(row.get("field_name", "")) for row in packs}
    assert "geography_input" in field_names
    history_snippets = [
        item["snippet"]
        for row in packs
        if row.get("field_name") == "history_digest"
        for item in row.get("evidence_items", [])
    ]
    assert history_snippets
    assert not any("Warcraft RPG" in snippet for snippet in history_snippets)
    geography_snippets = [
        item["snippet"]
        for row in packs
        if row.get("field_name") == "geography_input"
        for item in row.get("evidence_items", [])
    ]
    assert any("Eastern Kingdoms" in snippet for snippet in geography_snippets)
    assert not any("abandoned farms" in snippet for snippet in geography_snippets)


def test_at_a_glance_pool_scoped() -> None:

    """Canvas Slice 1 alias: at_a_glance_input stays seed-scoped and capped."""

    test_scoped_evidence_pools_exclude_auxiliary_other_from_prose_fields()


def test_quest_lore_evidence_fields() -> None:
    snapshots = [
        {
            "entity_id": ZONE_ID,
            "entity_type": "zone",
            "name": ZONE_NAME,
            "source_id": "src-quest-a",
            "url": "https://warcraft.wiki.gg/wiki/Quest_Alpha",
            "auxiliary_role": "quest",
            "page_title": "Quest Alpha",
            "cluster_id": "cluster-alpha",
            "quest_node_id": "quest-alpha",
            "quest_lore_blocks": [
                {"section_role": "description", "text": "Alpha quest narrative about reclaiming the district."}
            ],
            "section_blocks": [],
        }
    ]
    v3_rows = [
        {
            "zone_id": ZONE_ID,
            "node_type": "quest",
            "cluster_id": "cluster-alpha",
            "node_id": "quest-alpha",
            "source_link": "/wiki/Quest_Alpha",
        }
    ]
    packs = _build_evidence_packs(snapshots, "run-test", v3_rows=v3_rows)
    field_names = {str(row.get("field_name", "")) for row in packs}
    assert "quest_lore" in field_names
    assert "quest_cluster_lore" in field_names


def test_faction_profile_pack_includes_faction_id_in_build_meta() -> None:
    snapshots = [
        {
            "entity_id": ZONE_ID,
            "entity_type": "zone",
            "name": ZONE_NAME,
            "source_id": "src-faction-argent",
            "url": "https://warcraft.wiki.gg/wiki/Argent_Crusade",
            "section_blocks": [
                {
                    "section_role": "lead",
                    "text": (
                        "The Argent Crusade coordinates reclamation efforts against undead forces "
                        "across contested frontiers throughout the eastern kingdoms."
                    ),
                }
            ],
            "auxiliary_role": "faction_profile",
            "auxiliary_target_id": "faction-argent-crusade",
            "page_title": "Argent Crusade",
        }
    ]
    packs = _build_evidence_packs(snapshots, "run-test")
    faction_packs = [row for row in packs if row.get("field_name") == "faction_pool"]
    assert faction_packs
    build_meta = faction_packs[0].get("build_meta") or {}
    assert build_meta.get("faction_id") == "faction-argent-crusade"
    assert build_meta.get("faction_name") == "Argent Crusade"
    assert build_meta.get("subject_zone_id") == ZONE_ID


def test_location_profile_pack_includes_location_id_in_build_meta() -> None:
    snapshots = [
        {
            "entity_id": ZONE_ID,
            "entity_type": "zone",
            "name": ZONE_NAME,
            "source_id": "src-location-hearthglen",
            "url": "https://warcraft.wiki.gg/wiki/Hearthglen",
            "section_blocks": [
                {
                    "section_role": "lead",
                    "text": (
                        "Hearthglen is a fortified city in the Western Plaguelands that serves as a "
                        "major crusader stronghold and regional command post for reclamation efforts."
                    ),
                }
            ],
            "auxiliary_role": "location_profile",
            "auxiliary_target_id": "location-hearthglen",
            "page_title": "Hearthglen",
        }
    ]
    packs = _build_evidence_packs(snapshots, "run-test")
    location_packs = [row for row in packs if row.get("field_name") == "location_pool"]
    assert location_packs
    build_meta = location_packs[0].get("build_meta") or {}
    assert build_meta.get("location_id") == "location-hearthglen"
    assert build_meta.get("location_name") == "Hearthglen"
    assert build_meta.get("subject_zone_id") == ZONE_ID


INSTANCE_ID = "instance-example"
INSTANCE_NAME = "Example Instance"


def test_instance_seed_evidence_fields() -> None:
    snapshots = [
        {
            "entity_id": INSTANCE_ID,
            "entity_type": "instance",
            "name": INSTANCE_NAME,
            "source_id": "src-instance",
            "url": "https://warcraft.wiki.gg/wiki/Example_Instance",
            "section_blocks": [
                {"section_role": "lead", "text": "Example Instance lead paragraph for at-a-glance."},
                {"section_role": "history", "text": "Historical arc about the academy beneath the blighted hills."},
                {
                    "section_role": "adventurers",
                    "text": "Bosses include /wiki/Archivist_Maelor and /wiki/Warden_Voss.",
                },
            ],
            "auxiliary_role": "",
        }
    ]
    packs = _build_evidence_packs(snapshots, "run-test")
    field_names = {str(row.get("field_name", "")) for row in packs}
    assert "at_a_glance_input" in field_names
    assert "history_digest" in field_names
    assert "boss_pool" in field_names
    boss_packs = [row for row in packs if row.get("field_name") == "boss_pool"]
    assert boss_packs
    assert all((row.get("build_meta") or {}).get("source_kind") == "seed" for row in boss_packs)


def test_instance_lore_routes_to_instance_lore_pool() -> None:
    snapshots = [
        {
            "entity_id": INSTANCE_ID,
            "entity_type": "instance",
            "name": INSTANCE_NAME,
            "source_id": "src-instance-lore",
            "url": "https://warcraft.wiki.gg/wiki/Example_Instance_(lore)",
            "section_blocks": [
                {"section_role": "history", "text": "Lore page history about the academy's founding era."}
            ],
            "auxiliary_role": "instance_lore",
            "auxiliary_target_id": INSTANCE_ID,
            "page_title": "Example Instance (lore)",
        }
    ]
    packs = _build_evidence_packs(snapshots, "run-test")
    lore_packs = [row for row in packs if row.get("field_name") == "instance_lore_pool"]
    assert lore_packs
    build_meta = lore_packs[0].get("build_meta") or {}
    assert build_meta.get("instance_id") == INSTANCE_ID

