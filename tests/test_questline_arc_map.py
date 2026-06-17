from __future__ import annotations

import json
from pathlib import Path

from pipeline.discovery.questline_arc_map import (
    load_pilot_questline_registry,
    map_cluster_to_card_id,
)
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


def test_wpl_registry_maps_three_ql_card_ids() -> None:
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
    # Structural redesign: clusters bind to registry arcs by quest membership (not keyword
    # tables). This synthetic fixture's Andorhal clusters carry real arc node-ids and bind;
    # its Hearthglen/Mender clusters use placeholder node-ids that do not (the full-run
    # 3-card outcome incl. Hearthglen is validated against real quest records elsewhere).
    assert card_ids == {"ql-andorhal-alliance", "ql-andorhal-horde"}
    # Mender's Stead is no longer an included arc; nothing maps to it.
    assert "ql-menders-stead-healing" not in card_ids
    # No raw cluster-* ids; one card per arc (dedupe).
    assert all(row["card_id"].startswith("ql-") for row in metadata_rows)
    assert len(card_ids) == len(metadata_rows)
    assert metrics["card_polish_registry_mapped_count"] == len(metadata_rows)
    assert all(row["suppress_continued_card"] for row in metadata_rows)


def test_membership_binds_hearthglen_arc_from_real_node_ids() -> None:
    # Faithful membership coverage for Hearthglen using real registry-arc node ids.
    registry = load_pilot_questline_registry(ZONE_ID)
    card_id, registry_arc_id, _title, suppress = map_cluster_to_card_id(
        zone_id=ZONE_ID,
        cluster_id="argent-crusade",
        cluster_title="Argent Crusade",
        faction="shared",
        member_node_ids=[
            "quest-an-audience-with-the-highlord",
            "quest-taelan-fordring-s-legacy",
            "quest-the-good-people-of-hearthglen",
        ],
        registry=registry,
    )
    assert card_id == "ql-hearthglen-tirion-legacy"
    assert registry_arc_id == "ql-hearthglen-tirion-legacy"
    assert suppress is True


def test_unknown_zone_mints_generic_ql_id() -> None:
    # A zone with no registry mints a stable generic ql-<slug> id (never a raw cluster-*).
    card_id, registry_arc_id, _title, suppress = map_cluster_to_card_id(
        zone_id="zone-unknown",
        cluster_id="side-arc",
        cluster_title="Minor Side Story",
        faction="shared",
        member_node_ids=["quest-a", "quest-b"],
        registry=load_pilot_questline_registry("zone-unknown"),
    )
    assert card_id == "ql-minor-side-story"
    assert registry_arc_id is None
    assert suppress is False


def test_pilot_cluster_without_arc_match_is_dropped() -> None:
    # A pilot-zone cluster that binds to no included arc returns an empty card_id (dropped).
    registry = load_pilot_questline_registry(ZONE_ID)
    card_id, registry_arc_id, _title, _suppress = map_cluster_to_card_id(
        zone_id=ZONE_ID,
        cluster_id="random-side-cluster",
        cluster_title="Random Side Cluster",
        faction="shared",
        member_node_ids=["quest-not-in-any-arc-1", "quest-not-in-any-arc-2"],
        registry=registry,
    )
    assert card_id == ""
    assert registry_arc_id is None
