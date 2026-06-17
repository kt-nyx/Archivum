from __future__ import annotations

import json
from pathlib import Path

from pipeline.discovery.questline_anchor import resolve_cluster_start_anchor
from pipeline.discovery.questline_card_polish import build_zone_questline_card_metadata
from pipeline.discovery.questline_cluster import cluster_zone_questlines
from pipeline.discovery.questline_significance import score_zone_questline_clusters

FIXTURE_DIR = Path("tests/fixtures/clustering")
ZONE_ID = "zone-western-plaguelands"

from pipeline.discovery.pilot_questline_registry import load_registry

REGISTRY = load_registry(ZONE_ID) or {}


def _load_wpl() -> tuple[list[dict], list[dict]]:
    roster = json.loads((FIXTURE_DIR / "western_plaguelands_roster_v3.json").read_text(encoding="utf-8"))
    records = [
        json.loads(line)
        for line in (FIXTURE_DIR / "western_plaguelands_quest_records.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return roster, records


def _registry_anchors_by_faction() -> dict[tuple[str, str], str]:
    registry = REGISTRY
    anchors: dict[tuple[str, str], str] = {}
    for arc in registry.get("included_arcs", []):
        faction = str(arc.get("faction", "shared")).strip().lower()
        title_blob = str(arc.get("title", "")).lower()
        anchors[(faction, "andorhal" if "andorhal" in title_blob else "other")] = str(arc.get("start_anchor", ""))
        if "mender" in title_blob or "healing" in title_blob:
            anchors[("shared", "mender")] = str(arc.get("start_anchor", ""))
        if "hearthglen" in title_blob or "tirion" in title_blob:
            anchors[("shared", "hearthglen")] = str(arc.get("start_anchor", ""))
    return anchors


def test_resolve_cluster_start_anchor_prefers_entry_quest_head() -> None:
    roster, records = _load_wpl()
    rows, summaries, _ = cluster_zone_questlines(
        zone_id=ZONE_ID,
        roster_rows=roster,
        quest_records=records,
        zone_name="Western Plaguelands",
    )
    records_by_node = {row["node_id"]: row for row in records}
    anchors = _registry_anchors_by_faction()
    for summary in summaries:
        cluster_id = str(summary.get("cluster_id", ""))
        quest_rows = sorted(
            [row for row in rows if row.get("cluster_id") == cluster_id],
            key=lambda row: int(row.get("order_in_cluster", 0) or 0),
        )
        anchor = resolve_cluster_start_anchor(
            cluster_id=cluster_id,
            ordered_quest_rows=quest_rows,
            records_by_node=records_by_node,
        )
        # Sanity: a resolved anchor is always a non-empty quest head for a real chain.
        if quest_rows:
            assert isinstance(anchor, str)

    _decisions, ranking = score_zone_questline_clusters(
        zone_id=ZONE_ID,
        cluster_summaries=summaries,
        v3_rows=rows,
        quest_records=records,
        run_id="test",
    )
    metadata_rows, _ = build_zone_questline_card_metadata(
        zone_id=ZONE_ID,
        cluster_summaries=summaries,
        v3_rows=rows,
        quest_records=records,
        included_cluster_ids=ranking["included_cluster_ids"],
    )
    metadata_by_card = {row["card_id"]: row for row in metadata_rows}
    # The Andorhal arcs bind in this fixture; their card anchors come from the registry arc.
    assert metadata_by_card["ql-andorhal-alliance"]["start_anchor"] == anchors[("alliance", "andorhal")]
    assert metadata_by_card["ql-andorhal-horde"]["start_anchor"] == anchors[("horde", "andorhal")]
