from __future__ import annotations

import json
from pathlib import Path

from pipeline.discovery.questline_arc_map import load_pilot_questline_registry, map_cluster_to_card_id
from pipeline.discovery.questline_card_polish import build_zone_questline_card_metadata
from pipeline.discovery.questline_cluster import cluster_zone_questlines
from pipeline.discovery.questline_significance import score_zone_questline_clusters

FIXTURE_DIR = Path("tests/fixtures/clustering")
ZONE_ID = "zone-western-plaguelands"


def _load_wpl() -> tuple[list[dict], list[dict]]:
    roster = json.loads((FIXTURE_DIR / "western_plaguelands_roster_v3.json").read_text(encoding="utf-8"))
    records = [
        json.loads(line)
        for line in (FIXTURE_DIR / "western_plaguelands_quest_records.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return roster, records


def test_wpl_registry_maps_four_ql_card_ids() -> None:
    roster, records = _load_wpl()
    rows, summaries, _ = cluster_zone_questlines(
        zone_id=ZONE_ID, roster_rows=roster, quest_records=records, zone_name="Western Plaguelands"
    )
    _decisions, ranking = score_zone_questline_clusters(
        zone_id=ZONE_ID,
        cluster_summaries=summaries,
        v3_rows=rows,
        quest_records=records,
        run_id="test",
    )
    metadata_rows, metrics = build_zone_questline_card_metadata(
        zone_id=ZONE_ID,
        cluster_summaries=summaries,
        v3_rows=rows,
        quest_records=records,
        included_cluster_ids=ranking["included_cluster_ids"],
    )
    card_ids = {row["card_id"] for row in metadata_rows}
    assert card_ids == {
        "ql-andorhal-alliance",
        "ql-andorhal-horde",
        "ql-menders-stead-healing",
        "ql-hearthglen-tirion-legacy",
    }
    assert metrics["card_polish_registry_mapped_count"] == 4
    assert all(row["suppress_continued_card"] for row in metadata_rows)


def test_unknown_cluster_falls_back_to_cluster_prefix() -> None:
    card_id, registry_arc_id, _title, suppress = map_cluster_to_card_id(
        zone_id="zone-unknown",
        cluster_id="side-arc",
        cluster_title="Minor Side Story",
        faction="shared",
        registry=load_pilot_questline_registry("zone-unknown"),
    )
    assert card_id == "cluster-side-arc"
    assert registry_arc_id is None
    assert suppress is False
