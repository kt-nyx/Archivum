from __future__ import annotations

import json
from pathlib import Path

from pipeline.contracts.models import ZONE_MAX_TOTAL_QUESTLINE_CARDS, ZONE_MIN_QUESTLINE_INCLUSION_SCORE
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


def _cluster_with_keyword(decisions: list[dict], keyword: str, *, faction: str = "") -> list[dict]:
    matches = []
    for row in decisions:
        if str(row.get("subject_type", "")) != "questline_cluster":
            continue
        features = row.get("features") or {}
        title = str(features.get("cluster_title", "")).lower()
        if keyword.lower() not in title:
            continue
        if faction and str(features.get("faction", "")).lower() != faction:
            continue
        matches.append(row)
    return matches


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


def test_wpl_fixture_includes_four_major_arcs_and_excludes_side_content() -> None:
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
    included_ids = ranking["included_cluster_ids"]
    assert len(included_ids) == 4

    cluster_decisions = [
        row for row in decisions if str(row.get("subject_type", "")) == "questline_cluster"
    ]
    included = [row for row in cluster_decisions if row.get("final_decision") == "include"]
    assert len(included) == 4
    for row in included:
        score = int((row.get("features") or {}).get("inclusion_score", 0))
        assert score >= ZONE_MIN_QUESTLINE_INCLUSION_SCORE or row.get("borderline_adjudication")

    andorhal_alliance = _cluster_with_keyword(cluster_decisions, "andorhal", faction="alliance")
    andorhal_horde = _cluster_with_keyword(cluster_decisions, "andorhal", faction="horde")
    assert andorhal_alliance and andorhal_alliance[0]["final_decision"] == "include"
    assert andorhal_horde and andorhal_horde[0]["final_decision"] == "include"

    northridge = _cluster_with_keyword(cluster_decisions, "northridge")
    gahrron = _cluster_with_keyword(cluster_decisions, "gahrron")
    assert northridge and northridge[0]["final_decision"] == "exclude"
    assert gahrron and gahrron[0]["final_decision"] == "exclude"

    included_titles = " ".join(
        str((row.get("features") or {}).get("cluster_title", "")).lower() for row in included
    )
    assert "northridge" not in included_titles
    assert "gahrron" not in included_titles

    ranks = {item["cluster_id"]: item["rank"] for item in ranking["rankings"] if item.get("rank", 0) > 0}
    if andorhal_alliance and andorhal_horde:
        alliance_id = andorhal_alliance[0]["subject_id"]
        horde_id = andorhal_horde[0]["subject_id"]
        assert ranks.get(alliance_id, 99) <= 4
        assert ranks.get(horde_id, 99) <= 4


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
