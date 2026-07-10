"""Graph-derived questline behavior must be invariant across regression-zone inputs."""

from __future__ import annotations

import json
from pathlib import Path

from pipeline.contracts.models import ZONE_MAX_TOTAL_QUESTLINE_CARDS
from pipeline.discovery.questline_card_polish import build_zone_questline_card_metadata
from pipeline.discovery.questline_cluster import cluster_zone_questlines
from pipeline.discovery.questline_significance import score_zone_questline_clusters

FIXTURE_DIR = Path("tests/fixtures/clustering")


def _load_wpl() -> tuple[list[dict], list[dict]]:
    roster = json.loads((FIXTURE_DIR / "western_plaguelands_roster_v3.json").read_text())
    records = [
        json.loads(line)
        for line in (FIXTURE_DIR / "western_plaguelands_quest_records.jsonl").read_text().splitlines()
        if line.strip()
    ]
    return roster, records


def test_questline_cards_are_derived_from_clusters_not_zone_overrides() -> None:
    roster, records = _load_wpl()
    rows, summaries, _ = cluster_zone_questlines(
        zone_id="zone-western-plaguelands", roster_rows=roster, quest_records=records
    )
    decisions, ranking = score_zone_questline_clusters(
        zone_id="zone-western-plaguelands",
        cluster_summaries=summaries,
        v3_rows=rows,
        quest_records=records,
        run_id="test",
    )
    included = ranking["included_cluster_ids"]
    assert included and len(included) <= ZONE_MAX_TOTAL_QUESTLINE_CARDS
    assert all(
        set(row["reason_codes"]) & {"score_threshold_met", "borderline_adjudicated"}
        for row in decisions
        if row["subject_id"] in included
    )
    metadata, metrics = build_zone_questline_card_metadata(
        zone_id="zone-western-plaguelands",
        cluster_summaries=summaries,
        v3_rows=rows,
        quest_records=records,
        included_cluster_ids=included,
    )
    assert metrics["card_polish_cluster_count"] == len(included)
    assert {row["card_id"] for row in metadata} == {f"ql-{cluster_id}" for cluster_id in included}
    assert all(row["ordered_chain_refs"] for row in metadata)
