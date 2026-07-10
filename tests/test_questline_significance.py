from __future__ import annotations

from pipeline.discovery.questline_significance import score_zone_questline_clusters


def _score(summary: dict) -> dict:
    records = [
        {"zone_id": "zone-example", "node_id": node_id, "has_questbox": True, "previous": [], "start_npc": "Guide"}
        for node_id in summary["quest_node_ids"]
    ]
    rows = [
        {"zone_id": "zone-example", "node_type": "quest", "node_id": node_id, "cluster_id": summary["cluster_id"], "cluster_order": 1, "order_in_cluster": index}
        for index, node_id in enumerate(summary["quest_node_ids"], start=1)
    ]
    decisions, _ = score_zone_questline_clusters(
        zone_id="zone-example", cluster_summaries=[summary], v3_rows=rows, quest_records=records, run_id="test"
    )
    return next(row for row in decisions if row.get("subject_type") == "questline_cluster")


def test_structural_criteria_sum_to_inclusion_score() -> None:
    row = _score({"zone_id": "zone-example", "cluster_id": "main", "title": "Main Story", "faction": "shared", "quest_count": 4, "quest_node_ids": ["q1", "q2", "q3", "q4"], "reputation_orgs": []})
    features = row["features"]
    assert sum(value for key, value in features.items() if key.startswith("criterion_")) == features["inclusion_score"]
    assert row["final_decision"] in {"include", "exclude"}
    assert row["reason_codes"][0] in {
        "score_threshold_met", "borderline_adjudicated", "below_exclusion_threshold",
        "structural_fallback_top_cluster",
    }


def test_borderline_decision_is_explainable_without_zone_data() -> None:
    row = _score({"zone_id": "zone-example", "cluster_id": "patrol", "title": "Patrol", "faction": "shared", "quest_count": 3, "quest_node_ids": ["q1", "q2", "q3"], "reputation_orgs": []})
    assert row["reason_codes"][0] in {
        "score_threshold_met", "borderline_adjudicated", "below_exclusion_threshold",
        "structural_fallback_top_cluster",
    }
