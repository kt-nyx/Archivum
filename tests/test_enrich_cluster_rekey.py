from __future__ import annotations

from pipeline.discovery.enrich import _build_evidence_packs, _v3_cluster_index


def test_build_evidence_packs_prefers_post_layer_cluster_id() -> None:
    zone_id = "zone-example"
    v3_rows = [
        {
            "zone_id": zone_id,
            "node_type": "quest",
            "cluster_id": "part-1-alliance",
            "node_id": "quest-a",
            "source_link": "/wiki/Quest_A",
        }
    ]
    snapshots = [
        {
            "entity_id": zone_id,
            "entity_type": "zone",
            "auxiliary_role": "quest",
            "source_id": "src-quest-a",
            "url": "https://warcraft.wiki.gg/wiki/Quest_A",
            "name": "Quest A",
            "page_title": "Quest A",
            "cluster_id": "cluster-main",
            "quest_node_id": "quest-a",
            "quest_lore_blocks": [{"text": "Alliance scouts push back undead patrols.", "section_role": "description"}],
            "section_blocks": [],
        }
    ]
    packs = _build_evidence_packs(snapshots, "run-test", v3_rows=v3_rows)
    cluster_packs = [row for row in packs if row.get("field_name") == "quest_cluster_lore"]
    assert cluster_packs
    assert all(
        str((row.get("build_meta") or {}).get("cluster_id", "")) == "part-1-alliance"
        for row in cluster_packs
    )


def test_v3_cluster_index_maps_source_links() -> None:
    rows = [
        {
            "zone_id": "zone-example",
            "node_type": "quest",
            "cluster_id": "part-2-horde",
            "node_id": "quest-b",
            "source_link": "/wiki/Quest_B",
        }
    ]
    index = _v3_cluster_index(rows)
    assert index["zone-example|/wiki/quest_b"]["cluster_id"] == "part-2-horde"
