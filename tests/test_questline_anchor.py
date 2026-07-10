from __future__ import annotations

from pipeline.discovery.questline_anchor import resolve_cluster_start_anchor


def test_resolve_cluster_start_anchor_prefers_graph_head() -> None:
    rows = [
        {"node_id": "quest-later", "title": "The Next Step", "order_in_cluster": 2},
        {"node_id": "quest-entry", "title": "A Call to Action", "order_in_cluster": 1},
    ]
    records = {
        "quest-entry": {"title": "A Call to Action", "previous": [], "has_questbox": True},
        "quest-later": {"title": "The Next Step", "previous": ["quest-entry"]},
    }
    assert resolve_cluster_start_anchor(
        cluster_id="example", ordered_quest_rows=rows, records_by_node=records
    ) == "A Call to Action"
