from __future__ import annotations

import json

from pipeline.generate.draft.temporal import (
    ACTIVE_STORYLINE_OUTCOME,
    AMBIGUOUS_TEMPORAL,
    ENTRY_STATE,
    EXCLUDED_NONCANON,
    HISTORY_BACKGROUND,
    HISTORY_EXCLUDED_OUTCOME,
    HISTORY_EXCLUDED_POST_ACTIVE,
    HISTORY_SETUP_BRIDGE,
    POST_ACTIVE_LORE,
    PRE_ENTRY_HISTORY,
    enrich_evidence_temporal_metadata,
)


def _row(
    field_name: str,
    snippet: str,
    raw_role: str,
    *,
    source_id: str = "src-zone",
    subject_id: str = "zone-example",
    subject_type: str = "zone",
    build_meta: dict | None = None,
) -> dict:
    meta = {
        "run_id": "test",
        "source_id": source_id,
        "raw_section_role": raw_role,
    }
    if build_meta:
        meta.update(build_meta)
    return {
        "subject_id": subject_id,
        "subject_type": subject_type,
        "field_name": field_name,
        "build_meta": meta,
        "evidence_items": [
            {
                "source_url": "https://example.test",
                "source_title": "Example Zone",
                "snippet": snippet,
                "section_role": "history",
                "raw_section_role": raw_role,
                "confidence": 1.0,
            }
        ],
    }


def _scope(row: dict, item_index: int = 0) -> str:
    return row["evidence_items"][item_index]["temporal_scope"]


def _history_eligibility(row: dict, item_index: int = 0) -> str:
    return row["evidence_items"][item_index]["history_eligibility"]


def _prompt_items(kwargs: dict) -> list[dict]:
    return json.loads(kwargs["user_prompt"])["items"]


def _classification_for_prompt_item(
    item: dict,
    *,
    temporal_scope: str,
    history_eligibility: str,
    rationale: str,
    history_rationale: str,
    event_label: str = "",
) -> dict:
    return {
        "canonical_evidence_id": item["canonical_evidence_id"],
        "temporal_scope": temporal_scope,
        "history_eligibility": history_eligibility,
        "rationale": rationale,
        "history_rationale": history_rationale,
        "event_label": event_label,
    }


def test_boundary_uses_early_quest_records_not_late_outcomes(monkeypatch) -> None:
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")
    rows = [
        _row(
            "questline_pool",
            "The first scouts ask for help near the road.",
            "quest",
            build_meta={"cluster_id": "cluster-1", "quest_node_id": "q1"},
        ),
        _row(
            "questline_pool",
            "The commander claims victory after the battle.",
            "quest",
            build_meta={"cluster_id": "cluster-1", "quest_node_id": "q4"},
        ),
    ]

    enriched, temporal_decisions, boundary_decisions = enrich_evidence_temporal_metadata(
        rows,
        fact_packs_by_entity={
            "zone-example": {
                "entity_id": "zone-example",
                "entity_type": "zone",
                "name": "Example Zone",
            }
        },
        questline_card_metadata={
            "cluster-1": {
                "zone_id": "zone-example",
                "display_title": "Road to the Gate",
                "faction": "Alliance",
                "registry_chain_refs": ["q1", "q2", "q3", "q4"],
                "overflow_chain_refs": ["q5"],
            }
        },
        quest_records_by_node={
            "q1": {"node_id": "q1", "description": "Scouts gather supplies before the fighting."},
            "q2": {"node_id": "q2", "description": "A captain asks adventurers to hold the road."},
            "q4": {"node_id": "q4", "description": "The commander claims victory after the battle."},
            "q5": {"node_id": "q5", "description": "A later report names the winners."},
        },
        run_id="test",
        return_boundary_decisions=True,
    )

    assert [_scope(row) for row in enriched] == [ENTRY_STATE, ACTIVE_STORYLINE_OUTCOME]
    assert {row["temporal_scope"] for row in temporal_decisions} == {
        ENTRY_STATE,
        ACTIVE_STORYLINE_OUTCOME,
    }
    digest = boundary_decisions[0]["entry_state_digest"]
    assert "Scouts gather supplies" in digest
    assert "hold the road" in digest
    assert "claims victory" not in digest
    assert "later report" not in digest
    assert boundary_decisions[0]["outcome_hints"]


def test_mixed_valid_rpg_categories_do_not_drop_current_retail_source(monkeypatch) -> None:
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")
    rows = [
        _row("currently_input", "The current defenders hold the road.", "lead"),
        _row(
            "location_pool",
            "A current village acts as a road watch.",
            "lead",
            source_id="src-mixed-location",
        ),
        _row(
            "location_pool",
            "An RPG-only village appears here.",
            "in_the_rpg",
            source_id="src-rpg-location",
        ),
    ]
    enriched, _temporal, _boundary = enrich_evidence_temporal_metadata(
        rows,
        fact_packs_by_entity={
            "zone-example": {"entity_id": "zone-example", "entity_type": "zone"}
        },
        source_snapshots=[
            {
                "source_id": "src-mixed-location",
                "categories": ["Villages", "World of Warcraft: The Roleplaying Game"],
            },
            {
                "source_id": "src-rpg-location",
                "categories": ["World of Warcraft: The Roleplaying Game"],
            },
        ],
        run_id="test",
        return_boundary_decisions=True,
    )

    assert _scope(enriched[0]) == ENTRY_STATE
    assert _scope(enriched[1]) == ENTRY_STATE
    assert _scope(enriched[2]) == EXCLUDED_NONCANON


def test_history_defaults_to_ambiguous_without_llm(monkeypatch) -> None:
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")
    rows = [
        _row("history_digest", "The old empire fought a terrible ancient war.", "history"),
    ]

    enriched, decisions, _boundary = enrich_evidence_temporal_metadata(
        rows,
        fact_packs_by_entity={
            "zone-example": {"entity_id": "zone-example", "entity_type": "zone"}
        },
        run_id="test",
        return_boundary_decisions=True,
    )

    assert _scope(enriched[0]) == AMBIGUOUS_TEMPORAL
    assert "history_digest" in decisions[0]["temporal_structural_hint"]


def test_boundary_llm_classifies_unregistered_war_names(monkeypatch) -> None:
    monkeypatch.setattr(
        "pipeline.generate.draft.temporal._llm_temporal_adjudication_disabled",
        lambda: False,
    )

    def fake_llm_json_with_retry(**kwargs):
        assert kwargs["response_schema_name"] == "wiki_first_temporal_boundary_classification"
        assert "War of the Ancients" in kwargs["user_prompt"]
        assert "war against the Lich King" in kwargs["user_prompt"]
        items = _prompt_items(kwargs)
        return {
            "classifications": [
                _classification_for_prompt_item(
                    items[0],
                    temporal_scope=PRE_ENTRY_HISTORY,
                    history_eligibility=HISTORY_BACKGROUND,
                    rationale="This is ancient background before the page entry state.",
                    history_rationale="This belongs in history as background.",
                    event_label="War of the Ancients",
                ),
                _classification_for_prompt_item(
                    items[1],
                    temporal_scope=ENTRY_STATE,
                    history_eligibility=HISTORY_SETUP_BRIDGE,
                    rationale="This describes the setup the player is walking into.",
                    history_rationale="This bridges history into the current setup.",
                    event_label="war against the Lich King",
                ),
            ]
        }

    monkeypatch.setattr("pipeline.generate.draft.temporal.llm_json_with_retry", fake_llm_json_with_retry)

    row = _row(
        "history_digest",
        "During the War of the Ancients, the lake became sacred.",
        "history",
    )
    row["evidence_items"].append(
        {
            "source_url": "https://example.test",
            "source_title": "Example Zone",
            "snippet": "During the war against the Lich King, soldiers gather at the gate.",
            "section_role": "history",
            "raw_section_role": "history",
            "confidence": 1.0,
        }
    )

    enriched, decisions, _boundary = enrich_evidence_temporal_metadata(
        [row],
        fact_packs_by_entity={
            "zone-example": {"entity_id": "zone-example", "entity_type": "zone"}
        },
        questline_card_metadata={
            "cluster-1": {
                "zone_id": "zone-example",
                "display_title": "Hold the Gate",
                "registry_chain_refs": ["q1"],
            }
        },
        quest_records_by_node={
            "q1": {"node_id": "q1", "description": "Soldiers gather at the gate."}
        },
        run_id="test",
        return_boundary_decisions=True,
    )

    assert [_scope(enriched[0], 0), _scope(enriched[0], 1)] == [
        PRE_ENTRY_HISTORY,
        ENTRY_STATE,
    ]
    assert [_history_eligibility(enriched[0], 0), _history_eligibility(enriched[0], 1)] == [
        HISTORY_BACKGROUND,
        HISTORY_SETUP_BRIDGE,
    ]
    assert decisions[0]["temporal_fallback_mode"] == "llm_boundary"
    assert decisions[1]["history_eligibility"] == HISTORY_SETUP_BRIDGE
    assert decisions[1]["temporal_event_label"] == "war against the Lich King"


def test_current_field_from_history_section_requires_boundary_llm(monkeypatch) -> None:
    monkeypatch.setattr(
        "pipeline.generate.draft.temporal._llm_temporal_adjudication_disabled",
        lambda: False,
    )

    def fake_llm_json_with_retry(**kwargs):
        assert kwargs["response_schema_name"] == "wiki_first_temporal_boundary_classification"
        assert "absent from the current roster/setup anchors" in kwargs["system_prompt"]
        items = _prompt_items(kwargs)
        return {
            "classifications": [
                _classification_for_prompt_item(
                    items[0],
                    temporal_scope=POST_ACTIVE_LORE,
                    history_eligibility=HISTORY_EXCLUDED_POST_ACTIVE,
                    rationale="The visiting cabal and book objective are absent from the current roster.",
                    history_rationale="This is later off-screen lore, not entry setup history.",
                    event_label="off-screen cabal visit",
                )
            ]
        }

    monkeypatch.setattr("pipeline.generate.draft.temporal.llm_json_with_retry", fake_llm_json_with_retry)

    rows = [
        _row(
            "at_a_glance_input",
            "A later cabal visited the school to seize an old spellbook.",
            "later_cabal_edit",
            subject_id="instance-example",
            subject_type="instance",
            build_meta={"content_role": "lore_history"},
        )
    ]

    enriched, decisions, _boundary = enrich_evidence_temporal_metadata(
        rows,
        fact_packs_by_entity={
            "instance-example": {
                "entity_id": "instance-example",
                "entity_type": "instance",
                "name": "Example Instance",
            }
        },
        source_snapshots=[
            {
                "entity_id": "instance-example",
                "entity_type": "instance",
                "infobox": {"Bosses": "Headmaster Example", "Type": "Dungeon"},
            }
        ],
        run_id="test",
        return_boundary_decisions=True,
    )

    assert _scope(enriched[0]) == POST_ACTIVE_LORE
    assert "current_field_historical_section" in decisions[0]["temporal_structural_hint"]
    assert decisions[0]["history_eligibility"] == "history_not_applicable"


def test_history_setup_bridge_can_feed_history_without_being_background(monkeypatch) -> None:
    monkeypatch.setattr(
        "pipeline.generate.draft.temporal._llm_temporal_adjudication_disabled",
        lambda: False,
    )

    def fake_llm_json_with_retry(**kwargs):
        assert "classify it as entry_state with history_setup_bridge" in kwargs["system_prompt"]
        items = _prompt_items(kwargs)
        return {
            "classifications": [
                _classification_for_prompt_item(
                    items[0],
                    temporal_scope=ENTRY_STATE,
                    history_eligibility=HISTORY_SETUP_BRIDGE,
                    rationale="The paragraph explains the current ruler and occupants.",
                    history_rationale="It bridges older history into the playable entry state.",
                    event_label="current holdout setup",
                )
            ]
        }

    monkeypatch.setattr("pipeline.generate.draft.temporal.llm_json_with_retry", fake_llm_json_with_retry)
    rows = [
        _row(
            "history_digest",
            "After the kingdom fell, the headmaster kept control of the last holdout.",
            "cataclysm_edit",
            subject_id="instance-example",
            subject_type="instance",
            build_meta={"content_role": "lore_history"},
        )
    ]

    enriched, decisions, _boundary = enrich_evidence_temporal_metadata(
        rows,
        fact_packs_by_entity={
            "instance-example": {
                "entity_id": "instance-example",
                "entity_type": "instance",
                "name": "Example Instance",
            }
        },
        source_snapshots=[
            {
                "entity_id": "instance-example",
                "entity_type": "instance",
                "infobox": {"Bosses": "Headmaster Example", "Type": "Dungeon"},
            }
        ],
        run_id="test",
        return_boundary_decisions=True,
    )

    assert _scope(enriched[0]) == ENTRY_STATE
    assert _history_eligibility(enriched[0]) == HISTORY_SETUP_BRIDGE
    assert decisions[0]["history_eligibility"] == HISTORY_SETUP_BRIDGE


def test_zone_history_duplicate_uses_current_entry_state_as_setup_bridge(monkeypatch) -> None:
    monkeypatch.setattr(
        "pipeline.generate.draft.temporal._llm_temporal_adjudication_disabled",
        lambda: False,
    )

    def fake_llm_json_with_retry(**kwargs):
        assert "current quest hubs" in kwargs["system_prompt"]
        items = _prompt_items(kwargs)
        assert len(items) == 1
        assert set(items[0]["appearance_field_names"]) == {
            "at_a_glance_input",
            "currently_input",
            "history_digest",
        }
        return {
            "classifications": [
                _classification_for_prompt_item(
                    items[0],
                    temporal_scope=ENTRY_STATE,
                    history_eligibility=HISTORY_SETUP_BRIDGE,
                    rationale="The paragraph explains the current hub the player enters.",
                    history_rationale="This shared paragraph bridges into current setup.",
                    event_label="current base setup",
                )
            ]
        }

    monkeypatch.setattr("pipeline.generate.draft.temporal.llm_json_with_retry", fake_llm_json_with_retry)
    snippet = (
        "After the northern war, the old stronghold was reclaimed by its former lord. "
        "The fortified town became the main base of operations and training ground for the order."
    )
    rows = [
        _row(
            "history_digest",
            snippet,
            "current_setup_edit",
            build_meta={"content_role": "lore_history", "source_id": "src-zone"},
        ),
        _row(
            "currently_input",
            snippet,
            "current_setup_edit",
            build_meta={"content_role": "lore_history", "source_id": "src-zone"},
        ),
        _row(
            "at_a_glance_input",
            snippet,
            "current_setup_edit",
            build_meta={"content_role": "lore_history", "source_id": "src-zone"},
        ),
    ]

    enriched, decisions, _boundary = enrich_evidence_temporal_metadata(
        rows,
        fact_packs_by_entity={
            "zone-example": {
                "entity_id": "zone-example",
                "entity_type": "zone",
                "name": "Example Zone",
            }
        },
        questline_card_metadata={
            "cluster-1": {
                "zone_id": "zone-example",
                "display_title": "Hold the Town",
                "registry_chain_refs": ["q1"],
            }
        },
        quest_records_by_node={
            "q1": {"node_id": "q1", "description": "Report to the order's reclaimed town."}
        },
        run_id="test",
        return_boundary_decisions=True,
    )

    assert [_scope(row) for row in enriched] == [ENTRY_STATE, ENTRY_STATE, ENTRY_STATE]
    assert _history_eligibility(enriched[0]) == HISTORY_SETUP_BRIDGE
    assert decisions[0]["temporal_fallback_mode"] == "llm_boundary"
    assert (
        enriched[0]["evidence_items"][0]["canonical_evidence_id"]
        == enriched[1]["evidence_items"][0]["canonical_evidence_id"]
        == enriched[2]["evidence_items"][0]["canonical_evidence_id"]
    )


def test_history_outcome_is_not_history_eligible(monkeypatch) -> None:
    monkeypatch.setattr(
        "pipeline.generate.draft.temporal._llm_temporal_adjudication_disabled",
        lambda: False,
    )

    def fake_llm_json_with_retry(**kwargs):
        items = _prompt_items(kwargs)
        return {
            "classifications": [
                _classification_for_prompt_item(
                    items[0],
                    temporal_scope=ACTIVE_STORYLINE_OUTCOME,
                    history_eligibility=HISTORY_EXCLUDED_OUTCOME,
                    rationale="The paragraph describes the boss defeat by adventurers.",
                    history_rationale="Dungeon completion outcomes stay out of history.",
                    event_label="dungeon outcome",
                )
            ]
        }

    monkeypatch.setattr("pipeline.generate.draft.temporal.llm_json_with_retry", fake_llm_json_with_retry)
    rows = [
        _row(
            "history_digest",
            "Adventurers defeated the headmaster and freed the prisoner.",
            "mists_of_pandaria_edit",
            subject_id="instance-example",
            subject_type="instance",
            build_meta={"content_role": "lore_history"},
        )
    ]

    enriched, decisions, _boundary = enrich_evidence_temporal_metadata(
        rows,
        fact_packs_by_entity={
            "instance-example": {
                "entity_id": "instance-example",
                "entity_type": "instance",
                "name": "Example Instance",
            }
        },
        run_id="test",
        return_boundary_decisions=True,
    )

    assert _scope(enriched[0]) == ACTIVE_STORYLINE_OUTCOME
    assert _history_eligibility(enriched[0]) == HISTORY_EXCLUDED_OUTCOME
    assert decisions[0]["history_eligibility"] == HISTORY_EXCLUDED_OUTCOME


def test_duplicate_restrictive_scope_is_classified_once_across_fields(monkeypatch) -> None:
    monkeypatch.setattr(
        "pipeline.generate.draft.temporal._llm_temporal_adjudication_disabled",
        lambda: False,
    )

    def fake_llm_json_with_retry(**kwargs):
        items = _prompt_items(kwargs)
        assert len(items) == 1
        assert set(items[0]["appearance_field_names"]) == {"at_a_glance_input", "history_digest"}
        return {
            "classifications": [
                _classification_for_prompt_item(
                    items[0],
                    temporal_scope=POST_ACTIVE_LORE,
                    history_eligibility=HISTORY_EXCLUDED_POST_ACTIVE,
                    rationale="Synthetic duplicate canonical classification.",
                    history_rationale="Synthetic duplicate canonical history classification.",
                    event_label="duplicate event",
                )
            ]
        }

    monkeypatch.setattr("pipeline.generate.draft.temporal.llm_json_with_retry", fake_llm_json_with_retry)
    snippet = "A later cabal visited the school to seize an old spellbook."
    rows = [
        _row(
            "history_digest",
            snippet,
            "later_cabal_edit",
            subject_id="instance-example",
            subject_type="instance",
            build_meta={"content_role": "lore_history", "source_id": "src-instance"},
        ),
        _row(
            "at_a_glance_input",
            snippet,
            "later_cabal_edit",
            subject_id="instance-example",
            subject_type="instance",
            build_meta={"content_role": "lore_history", "source_id": "src-instance"},
        ),
    ]

    enriched, decisions, _boundary, canonical = enrich_evidence_temporal_metadata(
        rows,
        fact_packs_by_entity={
            "instance-example": {
                "entity_id": "instance-example",
                "entity_type": "instance",
                "name": "Example Instance",
            }
        },
        run_id="test",
        return_boundary_decisions=True,
        return_canonical_decisions=True,
    )

    assert [_scope(row) for row in enriched] == [POST_ACTIVE_LORE, POST_ACTIVE_LORE]
    assert decisions[1]["temporal_fallback_mode"] == "llm_boundary"
    assert decisions[0]["history_eligibility"] == HISTORY_EXCLUDED_POST_ACTIVE
    assert decisions[1]["history_eligibility"] == HISTORY_EXCLUDED_POST_ACTIVE
    assert len(canonical) == 1
    assert canonical[0]["appearance_count"] == 2


def test_different_paragraphs_from_same_source_are_separate_canonical_records(monkeypatch) -> None:
    monkeypatch.setenv("WOW_LORE_WIKI_FIRST_NO_LLM", "1")
    row = _row(
        "history_digest",
        "The first paragraph describes an old battlefield.",
        "history",
        source_id="src-zone",
    )
    row["evidence_items"].append(
        {
            "source_url": "https://example.test",
            "source_title": "Example Zone",
            "snippet": "The second paragraph describes a later fortress.",
            "section_role": "history",
            "raw_section_role": "history",
            "confidence": 1.0,
        }
    )

    enriched, _decisions, _boundary, canonical = enrich_evidence_temporal_metadata(
        [row],
        fact_packs_by_entity={
            "zone-example": {"entity_id": "zone-example", "entity_type": "zone"}
        },
        run_id="test",
        return_boundary_decisions=True,
        return_canonical_decisions=True,
    )

    ids = [
        item["canonical_evidence_id"]
        for item in enriched[0]["evidence_items"]
    ]
    assert len(set(ids)) == 2
    assert len(canonical) == 2
