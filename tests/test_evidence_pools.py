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





def test_at_a_glance_pool_scoped() -> None:

    """Canvas Slice 1 alias: at_a_glance_input stays seed-scoped and capped."""

    test_scoped_evidence_pools_exclude_auxiliary_other_from_prose_fields()

