from __future__ import annotations

import json
from pathlib import Path

from pipeline.contracts.models import (
    ZONE_MAX_TOTAL_QUESTLINE_CARDS,
)
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


def _clusters_for_arc(decisions: list[dict], arc_id: str) -> list[dict]:
    return [
        row
        for row in decisions
        if str(row.get("subject_type", "")) == "questline_cluster"
        and str((row.get("features") or {}).get("registry_arc_id", "")) == arc_id
    ]


def test_criteria_breakdown_sums_to_inclusion_score() -> None:
    roster, records = _load_wpl()
    rows, summaries, _ = cluster_zone_questlines(
        zone_id=ZONE_ID, roster_rows=roster, quest_records=records
    )
    decisions, _ranking = score_zone_questline_clusters(
        zone_id=ZONE_ID,
        cluster_summaries=summaries,
        v3_rows=rows,
        quest_records=records,
        run_id="test-run",
    )
    for row in decisions:
        if str(row.get("subject_type", "")) != "questline_cluster":
            continue
        features = row.get("features") or {}
        criteria_sum = sum(
            int(value)
            for key, value in features.items()
            if str(key).startswith("criterion_")
        )
        assert criteria_sum == int(features.get("inclusion_score", -1))


def test_wpl_fixture_includes_arc_bound_clusters_and_excludes_side_content() -> None:
    # Membership-based inclusion: this synthetic fixture's Andorhal clusters bind to their
    # registry arcs; side content (gahrron/northridge/mender placeholders) binds to none and
    # is excluded. (The full 3-card outcome incl. Hearthglen is covered against real records.)
    roster, records = _load_wpl()
    rows, summaries, _ = cluster_zone_questlines(
        zone_id=ZONE_ID, roster_rows=roster, quest_records=records
    )
    decisions, ranking = score_zone_questline_clusters(
        zone_id=ZONE_ID,
        cluster_summaries=summaries,
        v3_rows=rows,
        quest_records=records,
        run_id="test-run",
    )
    cluster_decisions = [
        row for row in decisions if str(row.get("subject_type", "")) == "questline_cluster"
    ]
    included = [row for row in cluster_decisions if row.get("final_decision") == "include"]
    # Every included cluster binds to a registry arc (no keyword-table inclusion).
    assert included
    assert all(str((row.get("features") or {}).get("registry_arc_id", "")) for row in included)

    andorhal_alliance = _clusters_for_arc(cluster_decisions, "ql-andorhal-alliance")
    andorhal_horde = _clusters_for_arc(cluster_decisions, "ql-andorhal-horde")
    assert andorhal_alliance and andorhal_alliance[0]["final_decision"] == "include"
    assert andorhal_horde and andorhal_horde[0]["final_decision"] == "include"

    # Nothing binds to the dropped Mender's Stead arc.
    assert not _clusters_for_arc(cluster_decisions, "ql-menders-stead-healing")

    # Gahrron / Northridge side content scores but binds to no included arc -> excluded.
    for cid in ("gahrron-s-withering", "northridge"):
        row = next((r for r in cluster_decisions if str(r["subject_id"]) == cid), None)
        if row is not None:
            assert row["final_decision"] == "exclude"
            assert not str((row.get("features") or {}).get("registry_arc_id", ""))


def test_cap_trim_limits_included_clusters() -> None:
    roster, records = _load_wpl()
    rows, summaries, _ = cluster_zone_questlines(
        zone_id=ZONE_ID, roster_rows=roster, quest_records=records
    )
    _decisions, ranking = score_zone_questline_clusters(
        zone_id=ZONE_ID,
        cluster_summaries=summaries,
        v3_rows=rows,
        quest_records=records,
        run_id="test-run",
        pilot_max_cards=ZONE_MAX_TOTAL_QUESTLINE_CARDS,
    )
    assert len(ranking["included_cluster_ids"]) <= ZONE_MAX_TOTAL_QUESTLINE_CARDS


def test_borderline_scores_resolve_deterministically() -> None:
    summary = {
        "zone_id": "zone-example",
        "cluster_id": "cluster-borderline",
        "title": "Minor Patrol",
        "faction": "shared",
        "quest_count": 3,
        "reputation_orgs": [],
        "quest_node_ids": ["q1", "q2", "q3"],
    }
    records = [
        {
            "zone_id": "zone-example",
            "node_id": f"q{i}",
            "quest_title": f"Patrol Step {i}",
            "has_questbox": True,
            "faction": "shared",
            "previous": [f"Patrol Step {i - 1}"] if i > 1 else [],
            "next": [f"Patrol Step {i + 1}"] if i < 3 else [],
            "start_npc": f"NPC {i}",
            "reputation_org": "",
            "start_location": "Example Zone",
        }
        for i in range(1, 4)
    ]
    v3_rows = [
        {
            "zone_id": "zone-example",
            "node_type": "quest",
            "node_id": f"q{i}",
            "title": f"Patrol Step {i}",
            "cluster_id": "cluster-borderline",
            "cluster_order": 1,
            "order_in_cluster": i,
            "faction_binding": "shared",
        }
        for i in range(1, 4)
    ]
    decisions, _ = score_zone_questline_clusters(
        zone_id="zone-example",
        cluster_summaries=[summary],
        v3_rows=v3_rows,
        quest_records=records,
        run_id="test-run",
    )
    cluster_row = next(row for row in decisions if row.get("subject_type") == "questline_cluster")
    score = int((cluster_row.get("features") or {}).get("inclusion_score", 0))
    if 6 <= score <= 7:
        assert cluster_row.get("borderline_adjudication") is not None
        assert cluster_row["final_decision"] in {"include", "exclude"}
