"""WPL pilot inclusion is driven by registry-arc quest membership (no keyword tables)."""

from __future__ import annotations

import json
from pathlib import Path

from pipeline.discovery.pilot_questline_registry import load_registry
from pipeline.discovery.questline_cluster import cluster_zone_questlines
from pipeline.discovery.questline_significance import score_zone_questline_clusters

FIXTURE_DIR = Path("tests/fixtures/clustering")
ZONE_ID = "zone-western-plaguelands"


def test_inclusion_is_driven_by_registry_arc_membership() -> None:
    registry = load_registry(ZONE_ID)
    assert registry is not None
    assert int(registry["pipeline_gap_analysis"]["expected_included_card_count"]) == 3

    roster = json.loads(
        (FIXTURE_DIR / "western_plaguelands_roster_v3.json").read_text(encoding="utf-8")
    )
    records = [
        json.loads(line)
        for line in (FIXTURE_DIR / "western_plaguelands_quest_records.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
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
    included_ids = set(ranking["included_cluster_ids"])

    # Every included cluster binds to an included registry arc; every excluded one does not.
    # No keyword titles involved — membership overlap is the sole inclusion signal.
    for row in cluster_rows:
        features = row.get("features") or {}
        arc_id = str(features.get("registry_arc_id", "")).strip()
        subject_id = str(row.get("subject_id", ""))
        if subject_id in included_ids:
            assert row["final_decision"] == "include"
            assert arc_id, f"included cluster {subject_id} has no registry arc"
        else:
            assert row["final_decision"] == "exclude"

    included_arcs = {
        str(
            (
                next(r for r in cluster_rows if str(r["subject_id"]) == cid).get("features") or {}
            ).get("registry_arc_id", "")
        )
        for cid in included_ids
    }
    assert "ql-andorhal-alliance" in included_arcs
    assert "ql-andorhal-horde" in included_arcs
    # Mender's Stead is no longer an included arc; nothing binds to it.
    assert "ql-menders-stead-healing" not in included_arcs
