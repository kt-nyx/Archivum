from __future__ import annotations

from pipeline.discovery.questline_promotion_gate import (
    QuestlineRunArtifacts,
    check_questline_promotion,
)


def _artifacts(cards: list[dict]) -> QuestlineRunArtifacts:
    return QuestlineRunArtifacts(
        zone_id="zone-example",
        cards=cards,
        included_cluster_ids=["main-story"],
        metadata_by_cluster={
            "main-story": {
                "card_id": "ql-main-story",
                "chain_refs": ["quest-entry", "quest-next", "quest-final"],
            }
        },
        card_id_to_cluster_id={"ql-main-story": "main-story"},
        excluded_cluster_ids=set(),
        v3_quest_rows=[
            {"zone_id": "zone-example", "node_type": "quest", "cluster_id": "main-story", "node_id": "quest-entry", "order_in_cluster": 1},
            {"zone_id": "zone-example", "node_type": "quest", "cluster_id": "main-story", "node_id": "quest-next", "order_in_cluster": 2},
            {"zone_id": "zone-example", "node_type": "quest", "cluster_id": "main-story", "node_id": "quest-final", "order_in_cluster": 3},
        ],
    )


def test_graph_derived_primary_and_segment_cards_pass() -> None:
    cards = [
        {"id": "ql-main-story", "title": "Main Story", "include_decision": "include", "chain_refs": ["quest-entry", "quest-next"]},
        {"id": "ql-main-story-segment-2", "title": "Main Story", "include_decision": "include", "chain_refs": ["quest-final"]},
    ]
    assert not check_questline_promotion(_artifacts(cards), require_rankings=True)


def test_graph_validation_rejects_title_ids_and_out_of_cluster_refs() -> None:
    cards = [{"id": "ql-main-story", "title": "Main Story", "include_decision": "include", "chain_refs": ["outside"]}]
    errors = check_questline_promotion(_artifacts(cards), require_rankings=True)
    assert any("outside its cluster" in error for error in errors)


def test_graph_validation_rejects_metadata_chain_order_that_reverses_the_graph() -> None:
    artifacts = _artifacts(
        [
            {
                "id": "ql-main-story",
                "title": "Main Story",
                "include_decision": "include",
                "chain_refs": ["quest-next", "quest-entry"],
            }
        ]
    )
    errors = check_questline_promotion(artifacts, require_rankings=True)
    assert any("out of graph order" in error for error in errors)
