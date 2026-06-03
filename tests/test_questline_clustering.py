from __future__ import annotations

import json
from pathlib import Path

from pipeline.discovery.questline_clustering import (
    apply_cluster_layers,
    infer_hub_titles,
    split_by_faction,
    split_by_level_band,
)
from pipeline.discovery.storyline_html import parse_storyline_html

WPL_FIXTURE = Path("tests/fixtures/storyline/western_plaguelands_storyline.html")


def _sample_rows() -> list[dict]:
    return [
        {
            "zone_id": "zone-example",
            "node_type": "quest",
            "cluster_id": "cluster-main",
            "cluster_title": "Main storylines",
            "cluster_order": 1,
            "order_in_cluster": index,
            "node_id": f"quest-{index}",
            "title": f"Quest {index}",
            "faction_binding": binding,
            "level_range": level,
            "source_link": f"/wiki/Quest_{index}",
        }
        for index, (binding, level) in enumerate(
            [
                ("alliance", "[35-40]"),
                ("alliance", "[35-40]"),
                ("horde", "[35-40]"),
                ("horde", "[35-40]"),
                ("shared", "[41-45]"),
                ("shared", "[41-45]"),
            ],
            start=1,
        )
    ]


def test_infer_hub_titles_uses_storyline_headings() -> None:
    html = WPL_FIXTURE.read_text(encoding="utf-8")
    rows = parse_storyline_html(
        html,
        zone_id="zone-western-plaguelands",
        zone_name="Western Plaguelands",
    )
    cluster_ids = {row["cluster_id"] for row in rows}
    assert len(cluster_ids) >= 2
    assert "cluster-main" not in cluster_ids


def test_split_by_faction_creates_subclusters_for_large_mixed_cluster() -> None:
    rows = [
        {
            "zone_id": "zone-example",
            "node_type": "quest",
            "cluster_id": "cluster-main",
            "cluster_title": "Main storylines",
            "cluster_order": 1,
            "order_in_cluster": index,
            "node_id": f"quest-{index}",
            "title": f"Quest {index}",
            "faction_binding": "alliance" if index % 2 else "horde",
            "level_range": "[35-40]",
            "source_link": f"/wiki/Quest_{index}",
        }
        for index in range(1, 18)
    ]
    split = split_by_faction(rows)
    cluster_ids = {row["cluster_id"] for row in split}
    assert "cluster-main-alliance" in cluster_ids
    assert "cluster-main-horde" in cluster_ids


def test_split_by_level_band_splits_when_still_large() -> None:
    rows = [
        {
            "zone_id": "zone-example",
            "node_type": "quest",
            "cluster_id": "cluster-main-shared",
            "cluster_title": "Main storylines",
            "cluster_order": 1,
            "order_in_cluster": index,
            "node_id": f"quest-{index}",
            "title": f"Quest {index}",
            "faction_binding": "shared",
            "level_range": "[35-40]" if index <= 8 else "[41-45]",
            "source_link": f"/wiki/Quest_{index}",
        }
        for index in range(1, 17)
    ]
    split = split_by_level_band(rows)
    cluster_ids = {row["cluster_id"] for row in split}
    assert any("35-40" in cluster_id or "35-to-40" in cluster_id for cluster_id in cluster_ids)
    assert any("41-45" in cluster_id or "41-to-45" in cluster_id for cluster_id in cluster_ids)


def test_split_by_faction_splits_mixed_heading_cluster_below_cap() -> None:
    rows = [
        {
            "zone_id": "zone-example",
            "node_type": "quest",
            "cluster_id": "part-1-the-first-battle-for-andorhal",
            "cluster_title": "Part 1 - The first battle for Andorhal",
            "cluster_order": 1,
            "order_in_cluster": index,
            "node_id": f"quest-{index}",
            "title": f"Quest {index}",
            "faction_binding": binding,
            "level_range": "[15-30]",
            "source_link": f"/wiki/Quest_{index}",
        }
        for index, binding in enumerate(["alliance", "alliance", "horde", "horde", "shared"], start=1)
    ]
    split = split_by_faction(rows)
    cluster_ids = {row["cluster_id"] for row in split}
    assert "part-1-the-first-battle-for-andorhal-alliance" in cluster_ids
    assert "part-1-the-first-battle-for-andorhal-horde" in cluster_ids


def test_apply_cluster_layers_orders_l4_before_l2_l3() -> None:
    rows = _sample_rows()
    layered = apply_cluster_layers(rows, html="<h2>Andorhal Front</h2>")
    titles = {row["cluster_title"] for row in layered}
    assert any("Andorhal" in title or "Main storylines" in title for title in titles)


def test_prereq_graph_clustering_beats_heading_collapse_on_wpl_fixture() -> None:
    """Slice B clustering should not collapse the WPL pilot into one mega-cluster."""
    from pipeline.discovery.questline_cluster import cluster_zone_questlines

    roster = json.loads(
        Path("tests/fixtures/clustering/western_plaguelands_roster_v3.json").read_text(encoding="utf-8")
    )
    records = [
        json.loads(line)
        for line in Path("tests/fixtures/clustering/western_plaguelands_quest_records.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    html = WPL_FIXTURE.read_text(encoding="utf-8")
    heading_rows = apply_cluster_layers(roster, html=html)
    graph_rows, _summaries, _unresolved = cluster_zone_questlines(
        zone_id="zone-western-plaguelands",
        roster_rows=roster,
        quest_records=records,
        storyline_html=html,
        zone_name="Western Plaguelands",
    )
    heading_clusters = {row["cluster_id"] for row in heading_rows if row.get("node_type") == "quest"}
    graph_clusters = {row["cluster_id"] for row in graph_rows if row.get("node_type") == "quest"}
    assert len(graph_clusters) >= len(heading_clusters)
    assert len(graph_clusters) >= 5
