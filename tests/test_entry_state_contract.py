from __future__ import annotations

import json

import pytest

from pipeline.contracts.models import ZonePage
from pipeline.discovery.questline_card_polish import (
    load_questline_card_metadata,
    questline_card_metadata_artifact,
)
from pipeline.generate.draft.temporal import build_entry_state_contracts
from pipeline.validate.rules.structure import validate_structural_rules


def _row(
    field_name: str,
    snippet: str,
    raw_role: str,
    *,
    subject_id: str,
    subject_type: str,
    source_id: str = "src-example",
) -> dict:
    return {
        "subject_id": subject_id,
        "subject_type": subject_type,
        "field_name": field_name,
        "build_meta": {
            "run_id": "test",
            "source_id": source_id,
            "raw_section_role": raw_role,
        },
        "evidence_items": [
            {
                "source_url": "https://example.test",
                "source_title": "Example",
                "snippet": snippet,
                "section_role": raw_role,
                "raw_section_role": raw_role,
                "confidence": 1.0,
            }
        ],
    }


def test_zone_entry_state_contract_uses_setup_records_not_late_outcomes() -> None:
    contracts, decisions = build_entry_state_contracts(
        [
            _row(
                "history_digest",
                "A Fourth War report describes distant later activity.",
                "history",
                subject_id="zone-example",
                subject_type="zone",
            )
        ],
        fact_packs_by_entity={
            "zone-example": {
                "entity_id": "zone-example",
                "entity_type": "zone",
                "name": "Example Zone",
            }
        },
        source_snapshots=[],
        questline_card_metadata={
            "andorhal": {
                "zone_id": "zone-example",
                "display_title": "Andorhal Campaign",
                "faction": "alliance",
                "start_anchor": "Hero's Call",
                "chain_refs": ["q1", "q2", "q3", "q4"],
            },
            "hearthglen": {
                "zone_id": "zone-example",
                "display_title": "Hearthglen Muster",
                "faction": "shared",
                "start_anchor": "An Audience with the Highlord",
                "chain_refs": ["h1"],
            },
            "gahrrons": {
                "zone_id": "zone-example",
                "display_title": "The Renewed Plague",
                "faction": "shared",
                "start_anchor": "Gahrron's Withering Cauldron",
                "chain_refs": ["g1", "g2"],
            },
        },
        quest_records_by_node={
            "q1": {
                "node_id": "q1",
                "title": "Hero's Call",
                "description": "Alliance forces are staging at Andorhal.",
                "start_npc": "Hero's Call Board",
            },
            "q2": {
                "node_id": "q2",
                "title": "Scourge First",
                "description": "The first push targets Scourge lines before the faction battle resolves.",
                "end_npc": "Thassarian",
            },
            "q4": {
                "node_id": "q4",
                "title": "Final Report",
                "description": "A commander claims victory after the battle.",
            },
            "h1": {
                "node_id": "h1",
                "title": "An Audience with the Highlord",
                "description": "Report to Hearthglen and meet the Argent Crusade.",
            },
            "g1": {
                "node_id": "g1",
                "title": "Gahrron's Withering Cauldron",
                "description": "Investigate the renewed plague at Gahrron's Withering.",
            },
        },
        run_id="test",
    )

    contract = contracts["zone-example"].to_dict()
    entry_state_text = json.dumps(
        {
            "anchors": contract["source_anchor_refs"],
            "objectives": contract["current_objectives"],
            "storylines": contract["active_storylines"],
        },
        ensure_ascii=True,
    )
    outcome_text = json.dumps(contract["excluded_outcome_hints"], ensure_ascii=True)

    assert decisions[0]["contract_id"].startswith("entry-state-zone-example-")
    assert "Andorhal Campaign" in entry_state_text
    assert "Hearthglen" in entry_state_text
    assert "Gahrron's Withering" in entry_state_text
    assert "A commander claims victory after the battle" not in entry_state_text
    assert "Fourth War report" not in entry_state_text
    assert "A commander claims victory after the battle" in outcome_text


def test_instance_entry_state_contract_uses_roster_and_infobox_not_later_links() -> None:
    contracts, _decisions = build_entry_state_contracts(
        [
            _row(
                "at_a_glance_input",
                "Scholomance is a current school of necromancy beneath Caer Darrow.",
                "lead",
                subject_id="instance-example",
                subject_type="instance",
            )
        ],
        fact_packs_by_entity={
            "instance-example": {
                "entity_id": "instance-example",
                "entity_type": "instance",
                "name": "Scholomance",
            }
        },
        source_snapshots=[
            {
                "entity_id": "instance-example",
                "entity_type": "instance",
                "infobox": {
                    "Location": "Caer Darrow, Western Plaguelands",
                    "Race(s)": "Cultist Scourge",
                    "End boss": "Darkmaster Gandling",
                    "Bosses": "Instructor Chillheart",
                },
                "structured_links": [
                    {"label": "Rattlegore", "section_role": "Bosses"},
                    {"label": "Lilian Voss", "section_role": "Bosses"},
                    {"label": "Shadow Council", "section_role": "Later appearances"},
                ],
            }
        ],
        questline_card_metadata={},
        quest_records_by_node={},
        run_id="test",
    )

    contract = contracts["instance-example"].to_dict()
    current_text = json.dumps(contract, ensure_ascii=True)

    assert "Caer Darrow" in current_text
    assert "Cultist Scourge" in current_text
    assert "Darkmaster Gandling" in current_text
    assert "Rattlegore" in current_text
    assert "Lilian Voss" in current_text
    assert "current school of necromancy" in current_text
    assert "Shadow Council" not in current_text


def test_missing_questline_data_falls_back_to_current_structural_context() -> None:
    contracts, _decisions = build_entry_state_contracts(
        [
            _row(
                "currently_input",
                "Current defenders are gathering at the old tower.",
                "lead",
                subject_id="zone-example",
                subject_type="zone",
            )
        ],
        fact_packs_by_entity={
            "zone-example": {
                "entity_id": "zone-example",
                "entity_type": "zone",
                "name": "Example Zone",
            }
        },
        source_snapshots=[],
        questline_card_metadata={},
        quest_records_by_node={},
        run_id="test",
    )

    contract = contracts["zone-example"]

    assert contract.confidence < 0.5
    assert contract.reason == "fallback_current_structural_evidence"
    assert contract.source_anchor_refs
    assert "Current defenders" in json.dumps(contract.to_dict(), ensure_ascii=True)


def test_entry_profile_metadata_populates_location_and_faction_fields() -> None:
    contracts, _decisions = build_entry_state_contracts(
        [
            {
                "subject_id": "zone-example",
                "subject_type": "zone",
                "field_name": "location_pool",
                "build_meta": {
                    "run_id": "test",
                    "source_id": "src-location",
                    "raw_section_role": "lead",
                    "location_id": "location-hearthglen",
                    "location_name": "Hearthglen",
                },
                "evidence_items": [
                    {
                        "source_url": "https://example.test/location",
                        "source_title": "Hearthglen",
                        "snippet": "Hearthglen is an active Argent Crusade base.",
                        "section_role": "lead",
                        "raw_section_role": "lead",
                        "confidence": 1.0,
                    }
                ],
            },
            {
                "subject_id": "zone-example",
                "subject_type": "zone",
                "field_name": "faction_pool",
                "build_meta": {
                    "run_id": "test",
                    "source_id": "src-faction",
                    "raw_section_role": "lead",
                    "faction_id": "faction-argent-crusade",
                    "faction_name": "Argent Crusade",
                },
                "evidence_items": [
                    {
                        "source_url": "https://example.test/faction",
                        "source_title": "Argent Crusade",
                        "snippet": "The Argent Crusade operates from the area.",
                        "section_role": "lead",
                        "raw_section_role": "lead",
                        "confidence": 1.0,
                    }
                ],
            },
            {
                "subject_id": "zone-example",
                "subject_type": "zone",
                "field_name": "location_pool",
                "build_meta": {
                    "run_id": "test",
                    "source_id": "src-old-location",
                    "raw_section_role": "history",
                    "location_id": "location-old-ruins",
                    "location_name": "Old Ruins",
                },
                "evidence_items": [
                    {
                        "source_url": "https://example.test/old",
                        "source_title": "Old Ruins",
                        "snippet": "Old Ruins mattered in the distant past.",
                        "section_role": "history",
                        "raw_section_role": "history",
                        "confidence": 1.0,
                    }
                ],
            },
        ],
        fact_packs_by_entity={
            "zone-example": {
                "entity_id": "zone-example",
                "entity_type": "zone",
                "name": "Example Zone",
            }
        },
        source_snapshots=[],
        questline_card_metadata={},
        quest_records_by_node={},
        run_id="test",
    )

    contract = contracts["zone-example"].to_dict()

    assert contract["current_locations"] == [
        {
            "label": "Hearthglen",
            "source": "entry_profile_context",
            "location_id": "location-hearthglen",
            "source_id": "src-location",
        }
    ]
    assert contract["current_factions"] == [
        {
            "label": "Argent Crusade",
            "source": "entry_profile_context",
            "faction_id": "faction-argent-crusade",
            "source_id": "src-faction",
        }
    ]


def test_optional_llm_distillation_cannot_add_invented_contract_labels(monkeypatch) -> None:
    monkeypatch.setenv("WOW_LORE_ENTRY_STATE_CONTRACT_LLM", "1")
    monkeypatch.setattr(
        "pipeline.generate.draft.temporal._llm_temporal_adjudication_disabled",
        lambda: False,
    )

    def fake_llm_json_with_retry(**_kwargs):
        return {
            "contract_fields": {
                "current_locations": [],
                "current_factions": [],
                "current_threats": ["Scourge", "Invented Legion", "a"],
                "active_conflicts": [],
                "current_objectives": [],
                "active_storylines": [],
                "current_inhabitants": [],
                "current_controller": [],
                "active_encounters": [],
            }
        }

    monkeypatch.setattr(
        "pipeline.generate.draft.temporal.llm_json_with_retry",
        fake_llm_json_with_retry,
    )

    contracts, _decisions = build_entry_state_contracts(
        [],
        fact_packs_by_entity={
            "instance-example": {
                "entity_id": "instance-example",
                "entity_type": "instance",
                "name": "Scholomance",
            }
        },
        source_snapshots=[
            {
                "entity_id": "instance-example",
                "entity_type": "instance",
                "infobox": {
                    "Race(s)": "Scourge",
                    "End boss": "Darkmaster Gandling",
                },
            }
        ],
        questline_card_metadata={},
        quest_records_by_node={},
        run_id="test",
    )

    contract = contracts["instance-example"].to_dict()

    assert contract["current_threats"] == [
        {"label": "Scourge", "source": "llm_contract_distillation"}
    ]


def test_selected_metadata_round_trips_into_entry_state_setup_evidence(
    tmp_path, monkeypatch
) -> None:
    """The discovery artifact, not graph reconstruction, owns entry-state setup evidence."""
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")
    metadata_path = tmp_path / "zone_questline_card_metadata.json"
    metadata_path.write_text(
        json.dumps(
            questline_card_metadata_artifact(
                [
                    {
                        "metadata_id": "metadata-ql-arc-lantern-watch",
                        "zone_id": "zone-amber-marsh",
                        "cluster_id": "arc-lantern-watch",
                        "source_arc_id": "arc-lantern-watch",
                        "card_id": "ql-arc-lantern-watch",
                        "display_title": "Lantern Watch",
                        "faction": "shared",
                        "start_anchor": "Lantern Call",
                        "start_anchor_ref": "quest-lantern-call",
                        "chain_refs": ["quest-lantern-call", "quest-marsh-watch"],
                        "source_refs": ["/wiki/Lantern_Call"],
                        "evidence_refs": ["quest-lantern-call", "quest-marsh-watch"],
                        "algorithm_version": "test",
                    }
                ]
            )
        ),
        encoding="utf-8",
    )
    metadata = load_questline_card_metadata(metadata_path)

    contracts, decisions = build_entry_state_contracts(
        [],
        fact_packs_by_entity={
            "zone-amber-marsh": {
                "entity_id": "zone-amber-marsh",
                "entity_type": "zone",
                "name": "Amber Marsh",
            }
        },
        source_snapshots=[],
        questline_card_metadata=metadata,
        quest_records_by_node={
            "quest-lantern-call": {
                "node_id": "quest-lantern-call",
                "title": "Lantern Call",
                "description": "Meet the watch captain at the marsh lantern.",
                "start_npc": "Watch Captain",
            },
            "quest-marsh-watch": {
                "node_id": "quest-marsh-watch",
                "title": "Marsh Watch",
                "description": "Secure the crossing before nightfall.",
            },
        },
        run_id="test",
    )

    setup = decisions[0]["source_anchor_refs"][0]
    assert setup["metadata_id"] == "metadata-ql-arc-lantern-watch"
    assert setup["setup_quest_refs"]
    assert setup["setup_snippets"]
    assert setup["setup_npcs"] == [
        {
            "role": "start_npc",
            "label": "Watch Captain",
            "quest_ref": "quest-lantern-call",
        }
    ]
    active_expansion = contracts["zone-amber-marsh"].active_expansion
    assert active_expansion is not None
    assert active_expansion["status"] == "unknown"
    assert active_expansion["fallbacks"] == ["active_expansion_adjudication_unavailable"]
    assert [row["quest_ref"] for row in active_expansion["source_evidence"]] == [
        "quest-lantern-call",
        "quest-marsh-watch",
    ]
    assert all(
        row["metadata_id"] == "metadata-ql-arc-lantern-watch"
        for row in active_expansion["source_evidence"]
    )


@pytest.mark.parametrize(
    "metadata",
    [
        {
            "metadata_id": "metadata-ql-broken",
            "zone_id": "zone-amber-marsh",
            "cluster_id": "arc-broken",
            "source_arc_id": "arc-broken",
            "card_id": "ql-broken",
            "display_title": "Broken Arc",
            "faction": "shared",
            "start_anchor": "Missing Start",
            "start_anchor_ref": "quest-missing",
            "chain_refs": ["quest-entry"],
            "algorithm_version": "test",
        },
        {
            "metadata_id": "metadata-ql-order",
            "zone_id": "zone-amber-marsh",
            "cluster_id": "arc-order",
            "source_arc_id": "arc-order",
            "card_id": "ql-order",
            "display_title": "Order Arc",
            "faction": "shared",
            "start_anchor": "Entry",
            "start_anchor_ref": "quest-entry",
            "chain_refs": ["quest-entry", "quest-entry"],
            "algorithm_version": "test",
        },
    ],
)
def test_invalid_metadata_artifact_fails_fast(tmp_path, metadata: dict) -> None:
    path = tmp_path / "zone_questline_card_metadata.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "questline_card_metadata.v1",
                "producer": "discovery.questline_card_polish",
                "metadata": [metadata],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="questline_card_metadata reader"):
        load_questline_card_metadata(path)


def test_release_rejects_confident_currently_when_active_expansion_is_unknown() -> None:
    page = ZonePage.model_validate(
        {
            "zone_id": "zone-amber-marsh",
            "name": "Amber Marsh",
            "wiki_url": "https://example.test/amber-marsh",
            "parent_continent": "example-continent",
            "expansion_context": "retail",
            "at_a_glance": "A wetland frontier with a fortified crossing.",
            "currently": "Wardens patrol the crossing while raiders threaten the causeway.",
            "history_sections": [{"heading": "Earlier settlement", "body": "The marsh was settled long ago."}],
            "provenance": {},
        }
    )
    issues = validate_structural_rules(
        "zone_page",
        page,
        validation_context={
            "release_gate": True,
            "entry_state_active_expansion": {"status": "unknown", "confidence": 0.0},
        },
    )
    assert any(issue.code == "structure.zone_page_currently_active_state_unknown" for issue in issues)
