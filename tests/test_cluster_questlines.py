from __future__ import annotations

from pipeline.generate.draft.pages import build_zone_page
from pipeline.generate.draft.pages.questlines import _group_v3_clusters, _majority_faction


def test_group_v3_clusters_aggregates_quest_nodes() -> None:
    rows = [
        {
            "node_type": "quest",
            "cluster_id": "part-1",
            "cluster_title": "Part 1",
            "cluster_order": 1,
            "order_in_cluster": 1,
            "node_id": "quest-a",
            "title": "Quest A",
            "faction_binding": "alliance",
            "source_link": "/wiki/Quest_A",
        },
        {
            "node_type": "quest",
            "cluster_id": "part-1",
            "cluster_title": "Part 1",
            "cluster_order": 1,
            "order_in_cluster": 2,
            "node_id": "quest-b",
            "title": "Quest B",
            "faction_binding": "alliance",
            "source_link": "/wiki/Quest_B",
        },
    ]
    grouped = _group_v3_clusters(rows)
    assert len(grouped) == 1
    assert grouped[0]["cluster_title"] == "Part 1"
    assert len(grouped[0]["quests"]) == 2


def test_majority_faction_tie_returns_shared() -> None:
    assert _majority_faction(["alliance", "horde"]) == "shared"
    assert _majority_faction(["alliance", "alliance", "horde"]) == "alliance"


def test_majority_faction_maps_neutral_to_shared() -> None:
    assert _majority_faction(["neutral", "neutral"]) == "shared"


def test_build_zone_page_skips_cluster_without_lore_evidence() -> None:
    zone_id = "zone-example"
    questline_rows = [
        {
            "zone_id": zone_id,
            "node_type": "quest",
            "cluster_id": "part-empty",
            "cluster_title": "Empty Arc",
            "cluster_order": 1,
            "order_in_cluster": 1,
            "node_id": "quest-empty",
            "title": "Quest Empty",
            "faction_binding": "shared",
            "source_link": "/wiki/Quest_Empty",
        },
        {
            "zone_id": zone_id,
            "node_type": "quest",
            "cluster_id": "part-1",
            "cluster_title": "Part 1 - Example Arc",
            "cluster_order": 2,
            "order_in_cluster": 1,
            "node_id": "quest-a",
            "title": "Quest A",
            "faction_binding": "alliance",
            "source_link": "/wiki/Quest_A",
        },
    ]
    evidence_rows = [
        {
            "subject_id": zone_id,
            "subject_type": "zone",
            "field_name": "quest_cluster_lore",
            "evidence_items": [
                {
                    "source_url": "https://warcraft.wiki.gg/wiki/Quest_A",
                    "source_title": "Quest A",
                    "snippet": "Crusaders push back undead forces along the ruined road.",
                    "section_role": "description",
                    "confidence": 1.0,
                }
            ],
            "build_meta": {
                "source_id": "src-quest-a",
                "cluster_id": "part-1",
                "subject_zone_id": zone_id,
            },
        }
    ]
    draft = build_zone_page(
        {
            "entity_id": zone_id,
            "name": "Example Zone",
            "source_ids": ["src-zone", "src-quest-a"],
            "revision_ids": ["mw:1", "mw:2"],
            "source_urls": {
                "src-zone": "https://warcraft.wiki.gg/wiki/Example_Zone",
                "src-quest-a": "https://warcraft.wiki.gg/wiki/Quest_A",
            },
        },
        evidence_rows,
        questline_rows,
        [],
        [],
        {},
        {},
        {"final_decision": "include"},
    )
    assert len(draft["major_questlines"]) == 1
    assert draft["major_questlines"][0]["id"] == "ql-part-1"


def test_build_zone_page_emits_cluster_cards() -> None:
    zone_id = "zone-example"
    questline_rows = [
        {
            "zone_id": zone_id,
            "node_type": "quest",
            "cluster_id": "part-1",
            "cluster_title": "Part 1 - Example Arc",
            "cluster_order": 1,
            "order_in_cluster": 1,
            "node_id": "quest-a",
            "title": "Quest A",
            "faction_binding": "alliance",
            "source_link": "/wiki/Quest_A",
        }
    ]
    evidence_rows = [
        {
            "subject_id": zone_id,
            "subject_type": "zone",
            "field_name": "quest_cluster_lore",
            "evidence_items": [
                {
                    "source_url": "https://warcraft.wiki.gg/wiki/Quest_A",
                    "source_title": "Quest A",
                    "snippet": "Crusaders push back undead forces along the ruined road.",
                    "section_role": "description",
                    "confidence": 1.0,
                }
            ],
            "build_meta": {
                "source_id": "src-quest-a",
                "cluster_id": "part-1",
                "subject_zone_id": zone_id,
            },
        }
    ]
    draft = build_zone_page(
        {
            "entity_id": zone_id,
            "name": "Example Zone",
            "source_ids": ["src-zone", "src-quest-a"],
            "revision_ids": ["mw:1", "mw:2"],
            "source_urls": {
                "src-zone": "https://warcraft.wiki.gg/wiki/Example_Zone",
                "src-quest-a": "https://warcraft.wiki.gg/wiki/Quest_A",
            },
        },
        evidence_rows,
        questline_rows,
        [],
        [],
        {},
        {},
        {"final_decision": "include"},
    )
    assert len(draft["major_questlines"]) == 1
    card = draft["major_questlines"][0]
    assert card["title"] == "Part 1 - Example Arc"
    assert card["id"] == "ql-part-1"
    assert card["wiki_refs"] == ["/wiki/Quest_A"]
    assert draft["provenance"]["major_questlines_alliance"]
    assert draft["provenance"]["major_questlines_alliance"][card["id"]]


def test_build_zone_page_replaces_parent_zone_cluster_title_with_entry_anchor() -> None:
    zone_id = "zone-example"
    questline_rows = [
        {
            "zone_id": zone_id,
            "node_type": "quest",
            "cluster_id": "entry",
            "cluster_title": "Example Zone",
            "cluster_order": 1,
            "order_in_cluster": 1,
            "node_id": "quest-entry",
            "title": "A New Threat",
            "faction_binding": "shared",
            "source_link": "/wiki/A_New_Threat",
        }
    ]
    evidence_rows = [
        {
            "subject_id": zone_id,
            "subject_type": "zone",
            "field_name": "quest_cluster_lore",
            "evidence_items": [
                {
                    "source_url": "https://warcraft.wiki.gg/wiki/A_New_Threat",
                    "source_title": "A New Threat",
                    "snippet": "A new threat gathers beyond the ridge.",
                    "section_role": "description",
                    "confidence": 1.0,
                }
            ],
            "build_meta": {
                "source_id": "src-entry",
                "cluster_id": "entry",
                "subject_zone_id": zone_id,
            },
        }
    ]
    draft = build_zone_page(
        {
            "entity_id": zone_id,
            "name": "Example Zone",
            "source_ids": ["src-entry"],
            "revision_ids": ["mw:1"],
            "source_urls": {"src-entry": "https://warcraft.wiki.gg/wiki/A_New_Threat"},
        },
        evidence_rows,
        questline_rows,
        [],
        [],
        {},
        {},
        {"final_decision": "include"},
    )
    assert draft["major_questlines"][0]["title"] == "A New Threat"


def test_build_zone_page_filters_excluded_clusters_by_ranking() -> None:
    zone_id = "zone-example"
    questline_rows = [
        {
            "zone_id": zone_id,
            "node_type": "quest",
            "cluster_id": "included-arc",
            "cluster_title": "Included Arc",
            "cluster_order": 1,
            "order_in_cluster": 1,
            "node_id": "quest-a",
            "title": "Quest A",
            "faction_binding": "shared",
            "source_link": "/wiki/Quest_A",
        },
        {
            "zone_id": zone_id,
            "node_type": "quest",
            "cluster_id": "excluded-arc",
            "cluster_title": "Excluded Arc",
            "cluster_order": 2,
            "order_in_cluster": 1,
            "node_id": "quest-b",
            "title": "Quest B",
            "faction_binding": "shared",
            "source_link": "/wiki/Quest_B",
        },
    ]
    evidence_rows = [
        {
            "subject_id": zone_id,
            "subject_type": "zone",
            "field_name": "quest_cluster_lore",
            "evidence_items": [
                {
                    "source_url": "https://warcraft.wiki.gg/wiki/Quest_A",
                    "source_title": "Quest A",
                    "snippet": "Included arc lore snippet.",
                    "section_role": "description",
                    "confidence": 1.0,
                }
            ],
            "build_meta": {
                "source_id": "src-a",
                "cluster_id": "included-arc",
                "subject_zone_id": zone_id,
            },
        },
        {
            "subject_id": zone_id,
            "subject_type": "zone",
            "field_name": "quest_cluster_lore",
            "evidence_items": [
                {
                    "source_url": "https://warcraft.wiki.gg/wiki/Quest_B",
                    "source_title": "Quest B",
                    "snippet": "Excluded arc lore snippet.",
                    "section_role": "description",
                    "confidence": 1.0,
                }
            ],
            "build_meta": {
                "source_id": "src-b",
                "cluster_id": "excluded-arc",
                "subject_zone_id": zone_id,
            },
        },
    ]
    draft = build_zone_page(
        {
            "entity_id": zone_id,
            "name": "Example Zone",
            "source_ids": ["src-zone", "src-a", "src-b"],
            "revision_ids": ["mw:1", "mw:2", "mw:3"],
            "source_urls": {
                "src-zone": "https://warcraft.wiki.gg/wiki/Example_Zone",
                "src-a": "https://warcraft.wiki.gg/wiki/Quest_A",
                "src-b": "https://warcraft.wiki.gg/wiki/Quest_B",
            },
        },
        evidence_rows,
        questline_rows,
        [],
        [],
        {},
        {},
        {"final_decision": "include"},
        included_cluster_ids=["included-arc"],
        questline_cluster_decision_map={
            "included-arc": {"final_decision": "include", "reason_codes": ["score_threshold_met"]},
            "excluded-arc": {"final_decision": "exclude", "reason_codes": ["local_side_content"]},
        },
    )
    assert len(draft["major_questlines"]) == 1
    assert draft["major_questlines"][0]["id"] == "ql-included-arc"
    assert draft["major_questlines"][0]["reason_codes"] == ["score_threshold_met"]
