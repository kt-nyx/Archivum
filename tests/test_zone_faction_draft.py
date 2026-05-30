from __future__ import annotations

from pipeline.generate.draft.faction_lint import lint_faction_summary
from pipeline.generate.draft.wiki_first import build_zone_page


def _fact_pack(zone_id: str) -> dict[str, object]:
    return {
        "entity_id": zone_id,
        "name": "Example Zone",
        "source_ids": ["src-zone", "src-faction-argent", "src-faction-cenarion"],
        "revision_ids": ["mw:1", "mw:2", "mw:3"],
        "source_urls": {
            "src-zone": "https://warcraft.wiki.gg/wiki/Example_Zone",
            "src-faction-argent": "https://warcraft.wiki.gg/wiki/Argent_Crusade",
            "src-faction-cenarion": "https://warcraft.wiki.gg/wiki/Cenarion_Circle",
        },
    }


def _minimal_prose_evidence(zone_id: str) -> list[dict[str, object]]:
    return [
        {
            "subject_id": zone_id,
            "field_name": "at_a_glance_input",
            "evidence_items": [
                {
                    "snippet": (
                        "A contested frontier where crusaders and druids resist undead remnants "
                        "across ruined farmland and broken keeps throughout the region."
                    ),
                    "section_role": "lead",
                }
            ],
            "build_meta": {"source_id": "src-zone", "subject_zone_id": zone_id},
        },
        {
            "subject_id": zone_id,
            "field_name": "currently_input",
            "evidence_items": [
                {
                    "snippet": (
                        "Recovery efforts continue to reshape roads and outposts while crusaders "
                        "and druids push back undead forces along the main road through the zone."
                    ),
                    "section_role": "cataclysm_edit",
                }
            ],
            "build_meta": {"source_id": "src-zone", "subject_zone_id": zone_id},
        },
        {
            "subject_id": zone_id,
            "field_name": "history_digest",
            "evidence_items": [
                {
                    "snippet": (
                        "The region was devastated during the invasion and fell under undead control "
                        "for decades before military campaigns began restoring order across the frontier, "
                        "broken keeps, and scattered villages throughout the zone."
                    ),
                    "section_role": "history",
                },
                {
                    "snippet": (
                        "Crusader expeditions established fortified outposts and slowly reclaimed "
                        "key strongholds from the lingering scourge that had dominated the region for "
                        "many years after the initial collapse across the ruined farmland."
                    ),
                    "section_role": "history_third_war",
                },
                {
                    "snippet": (
                        "After the Cataclysm, recovery efforts reshaped roads and outposts while "
                        "undead remnants were pushed back along the frontier between crusaders and "
                        "broken keeps across the ruined farmland throughout the zone."
                    ),
                    "section_role": "cataclysm_edit",
                },
            ],
            "build_meta": {"source_id": "src-zone", "subject_zone_id": zone_id},
        },
    ]


def _faction_evidence(zone_id: str) -> list[dict[str, object]]:
    argent_snippet = (
        "The Argent Crusade maintains fortified outposts across Example Zone, "
        "coordinating reclamation efforts against undead forces throughout the ruined frontier."
    )
    cenarion_snippet = (
        "The Cenarion Circle sends druids to heal blighted soil in Example Zone and push back corruption "
        "along the frontier while supporting crusader campaigns across the region."
    )
    return [
        {
            "subject_id": zone_id,
            "field_name": "faction_pool",
            "build_meta": {
                "source_id": "src-faction-argent",
                "subject_zone_id": zone_id,
                "faction_id": "faction-argent-crusade",
                "faction_name": "Argent Crusade",
            },
            "evidence_items": [{"snippet": argent_snippet, "section_role": "history"}],
        },
        {
            "subject_id": zone_id,
            "field_name": "faction_pool",
            "build_meta": {
                "source_id": "src-faction-cenarion",
                "subject_zone_id": zone_id,
                "faction_id": "faction-cenarion-circle",
                "faction_name": "Cenarion Circle",
            },
            "evidence_items": [{"snippet": cenarion_snippet, "section_role": "history"}],
        },
        {
            "subject_id": zone_id,
            "field_name": "currently_input",
            "evidence_items": [
                {
                    "snippet": (
                        "Argent Crusade patrols continue to push back undead forces along the main road "
                        "while coordinating with druids from the Cenarion Circle across the frontier."
                    ),
                    "section_role": "quests_edit",
                }
            ],
            "build_meta": {"source_id": "src-zone", "subject_zone_id": zone_id},
        },
    ]


def _faction_targets(zone_id: str) -> list[dict[str, str]]:
    return [
        {
            "zone_id": zone_id,
            "faction_id": "faction-argent-crusade",
            "name": "Argent Crusade",
            "source_link": "/wiki/Argent_Crusade",
        },
        {
            "zone_id": zone_id,
            "faction_id": "faction-cenarion-circle",
            "name": "Cenarion Circle",
            "source_link": "/wiki/Cenarion_Circle",
        },
        {
            "zone_id": zone_id,
            "faction_id": "faction-alliance",
            "name": "Alliance",
            "source_link": "/wiki/Alliance",
        },
    ]


def test_build_zone_page_emits_ranked_faction_cards_without_llm(monkeypatch) -> None:
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")
    zone_id = "zone-example"
    evidence = _minimal_prose_evidence(zone_id) + _faction_evidence(zone_id)
    draft = build_zone_page(
        _fact_pack(zone_id),
        evidence,
        [],
        [],
        [],
        {},
        {},
        None,
        faction_profile_targets=_faction_targets(zone_id),
    )
    factions = draft.get("major_factions") or []
    assert len(factions) >= 2
    ids = [str(row.get("id", "")) for row in factions]
    assert "faction-argent-crusade" in ids
    assert "faction-cenarion-circle" in ids
    assert "faction-alliance" not in ids
    for card in factions:
        summary = str(card.get("summary", ""))
        assert summary
        assert not lint_faction_summary(summary, zone_name="Example Zone")


def test_build_zone_page_alliance_included_with_quest_bindings(monkeypatch) -> None:
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")
    zone_id = "zone-example"
    evidence = _minimal_prose_evidence(zone_id)
    alliance_snippet = (
        "Alliance forces coordinate reclamation patrols along the main road in Example Zone while securing "
        "supply lines and outposts across the contested frontier throughout the region."
    )
    evidence.append(
        {
            "subject_id": zone_id,
            "field_name": "faction_pool",
            "build_meta": {
                "source_id": "src-faction-alliance",
                "subject_zone_id": zone_id,
                "faction_id": "faction-alliance",
                "faction_name": "Alliance",
            },
            "evidence_items": [{"snippet": alliance_snippet, "section_role": "history"}],
        }
    )
    questline_rows = [
        {
            "zone_id": zone_id,
            "node_type": "quest",
            "cluster_id": "part-1",
            "faction_binding": "alliance",
            "title": "Alliance Quest A",
            "source_link": "/wiki/Quest_A",
        },
        {
            "zone_id": zone_id,
            "node_type": "quest",
            "cluster_id": "part-1",
            "faction_binding": "alliance",
            "title": "Alliance Quest B",
            "source_link": "/wiki/Quest_B",
        },
    ]
    draft = build_zone_page(
        _fact_pack(zone_id),
        evidence,
        questline_rows,
        [],
        [],
        {},
        {},
        None,
        faction_profile_targets=[
            {
                "zone_id": zone_id,
                "faction_id": "faction-alliance",
                "name": "Alliance",
                "source_link": "/wiki/Alliance",
            }
        ],
    )
    ids = [str(row.get("id", "")) for row in draft.get("major_factions") or []]
    assert "faction-alliance" in ids
