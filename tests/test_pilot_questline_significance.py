"""Map WPL pilot registry included/excluded arcs to cluster title keyword expectations."""

from __future__ import annotations

import json
from pathlib import Path

from pipeline.discovery.questline_cluster import cluster_zone_questlines
from pipeline.discovery.questline_significance import score_zone_questline_clusters

REGISTRY_PATH = Path("tests/fixtures/pilot/western_plaguelands_questline_registry.json")
FIXTURE_DIR = Path("tests/fixtures/clustering")
ZONE_ID = "zone-western-plaguelands"

_INCLUDED_KEYWORDS = (
    ("ql-andorhal-alliance", ("andorhal",), "alliance"),
    ("ql-andorhal-horde", ("andorhal",), "horde"),
    ("ql-menders-stead-healing", ("mender", "cenarion"), "shared"),
    ("ql-hearthglen-tirion-legacy", ("hearthglen", "tirion"), "shared"),
)
_EXCLUDED_KEYWORDS = (
    ("ql-northridge-redpine", ("northridge", "lumber", "redpine")),
    ("ql-gahrrons-withering-cleanup", ("gahrron", "withering", "cauldron")),
)


def test_registry_arcs_match_significance_inclusion_by_title_keywords() -> None:
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    assert int(registry["pipeline_gap_analysis"]["expected_included_card_count"]) == 4

    roster = json.loads((FIXTURE_DIR / "western_plaguelands_roster_v3.json").read_text(encoding="utf-8"))
    records = [
        json.loads(line)
        for line in (FIXTURE_DIR / "western_plaguelands_quest_records.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    rows, summaries, _ = cluster_zone_questlines(
        zone_id=ZONE_ID, roster_rows=roster, quest_records=records
    )
    decisions, ranking = score_zone_questline_clusters(
        zone_id=ZONE_ID,
        cluster_summaries=summaries,
        v3_rows=rows,
        quest_records=records,
        run_id="test-registry",
    )
    cluster_rows = [
        row for row in decisions if str(row.get("subject_type", "")) == "questline_cluster"
    ]

    def find_cluster(keywords: tuple[str, ...], faction: str = "") -> dict | None:
        for row in cluster_rows:
            title = str((row.get("features") or {}).get("cluster_title", "")).lower()
            if not any(keyword in title for keyword in keywords):
                continue
            if faction and str((row.get("features") or {}).get("faction", "")).lower() != faction:
                continue
            return row
        return None

    for arc_id, keywords, faction in _INCLUDED_KEYWORDS:
        row = find_cluster(keywords, faction)
        assert row is not None, f"missing cluster for included arc {arc_id}"
        assert row["final_decision"] == "include", arc_id
        assert str(row["subject_id"]) in ranking["included_cluster_ids"], arc_id

    for arc_id, keywords in _EXCLUDED_KEYWORDS:
        row = find_cluster(keywords)
        assert row is not None, f"missing cluster for excluded arc {arc_id}"
        assert row["final_decision"] == "exclude", arc_id
        assert str(row["subject_id"]) not in ranking["included_cluster_ids"], arc_id
