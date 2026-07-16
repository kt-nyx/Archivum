"""Graph-derived questline behavior must be invariant across regression-zone inputs."""

from __future__ import annotations

import pytest

from pipeline.discovery.questline_card_polish import build_zone_questline_card_metadata


def test_questline_cards_are_derived_from_clusters_not_zone_overrides() -> None:
    zone_id = "zone-amber-marsh"
    included = ["arc-lantern-watch"]
    rows = [
        {"zone_id": zone_id, "node_type": "quest", "cluster_id": included[0], "node_id": "quest-lantern-call", "order_in_cluster": 1, "title": "Lantern Call"},
        {"zone_id": zone_id, "node_type": "quest", "cluster_id": included[0], "node_id": "quest-marsh-watch", "order_in_cluster": 2, "title": "Marsh Watch"},
    ]
    summaries = [{"zone_id": zone_id, "cluster_id": included[0], "title": "Lantern Watch", "faction": "shared"}]
    records = [
        {"zone_id": zone_id, "node_id": "quest-lantern-call", "quest_title": "Lantern Call", "description": "Report to the lantern keeper."},
        {"zone_id": zone_id, "node_id": "quest-marsh-watch", "quest_title": "Marsh Watch", "description": "Secure the marsh crossing."},
    ]
    metadata, metrics = build_zone_questline_card_metadata(
        zone_id=zone_id,
        cluster_summaries=summaries,
        v3_rows=rows,
        quest_records=records,
        included_cluster_ids=included,
        arc_candidates_by_id={included[0]: {"base_title": "Lantern Watch", "faction_variant": None, "phase_variant": None}},
        arc_families_by_candidate_id={included[0]: {"family_id": "arc-zone-amber-marsh-lantern"}},
    )
    assert metrics["card_polish_cluster_count"] == len(included)
    assert {row["card_id"] for row in metadata} == {f"ql-{cluster_id}" for cluster_id in included}
    assert all(row["chain_refs"] for row in metadata)
    assert all(row["start_anchor_ref"] in row["chain_refs"] for row in metadata)


def test_selected_cluster_with_missing_quest_record_fails_before_metadata_write() -> None:
    with pytest.raises(ValueError, match="references missing quest records"):
        build_zone_questline_card_metadata(
            zone_id="zone-amber-marsh",
            cluster_summaries=[
                {
                    "zone_id": "zone-amber-marsh",
                    "cluster_id": "arc-lantern-watch",
                    "title": "Lantern Watch",
                    "faction": "shared",
                }
            ],
            v3_rows=[
                {
                    "zone_id": "zone-amber-marsh",
                    "node_type": "quest",
                    "cluster_id": "arc-lantern-watch",
                    "node_id": "quest-unfetched",
                    "order_in_cluster": 1,
                }
            ],
            quest_records=[],
            included_cluster_ids=["arc-lantern-watch"],
            arc_candidates_by_id={"arc-lantern-watch": {"base_title": "Lantern Watch"}},
            arc_families_by_candidate_id={"arc-lantern-watch": {"family_id": "arc-zone-amber-marsh-lantern"}},
        )
