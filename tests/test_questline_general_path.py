"""The general questline path must produce structurally valid cards with NO registry.

Slice 11: the pilot registry is gold/QA scaffolding (a validator/override for pilot
zones), never a dependency of the general path. This builds the WPL questlines with the
registry disabled and asserts the structural pipeline (clustering -> significance ->
cap trim -> generic ql-* ids) still yields valid, capped, ranked cards.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.contracts.models import ZONE_MAX_TOTAL_QUESTLINE_CARDS
from pipeline.discovery import questline_arc_map, questline_card_polish, questline_significance
from pipeline.discovery.questline_card_polish import build_zone_questline_card_metadata
from pipeline.discovery.questline_cluster import cluster_zone_questlines
from pipeline.discovery.questline_significance import score_zone_questline_clusters

FIXTURE_DIR = Path("tests/fixtures/clustering")
ZONE_ID = "zone-western-plaguelands"


def _load_wpl() -> tuple[list[dict], list[dict]]:
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
    return roster, records


def test_wpl_questlines_without_registry_yield_structurally_valid_cards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        questline_significance, "load_pilot_questline_registry", lambda zone_id: None
    )
    monkeypatch.setattr(
        questline_card_polish, "load_pilot_questline_registry", lambda zone_id: None
    )
    # map_cluster_to_card_id falls back to its own module-level loader when the
    # caller passes registry=None, so the arc-map loader must be disabled too.
    monkeypatch.setattr(
        questline_arc_map, "load_pilot_questline_registry", lambda zone_id: None
    )

    roster, records = _load_wpl()
    rows, summaries, _ = cluster_zone_questlines(
        zone_id=ZONE_ID, roster_rows=roster, quest_records=records
    )
    decisions, ranking = score_zone_questline_clusters(
        zone_id=ZONE_ID,
        cluster_summaries=summaries,
        v3_rows=rows,
        quest_records=records,
        run_id="test-run-no-registry",
    )

    included_ids = ranking["included_cluster_ids"]
    assert included_ids, "general path produced no questline cards"
    assert len(included_ids) <= ZONE_MAX_TOTAL_QUESTLINE_CARDS

    cluster_decisions = [
        row for row in decisions if str(row.get("subject_type", "")) == "questline_cluster"
    ]
    included_decisions = [
        row for row in cluster_decisions if str(row.get("subject_id", "")) in set(included_ids)
    ]
    assert len(included_decisions) == len(included_ids)
    for row in included_decisions:
        # No registry: inclusion comes from the structural score/borderline path only.
        assert row["final_decision"] == "include"
        reasons = set(row.get("reason_codes") or [])
        assert reasons & {"score_threshold_met", "borderline_adjudicated"}
        assert not str((row.get("features") or {}).get("registry_arc_id", ""))

    metadata_rows, metrics = build_zone_questline_card_metadata(
        zone_id=ZONE_ID,
        cluster_summaries=summaries,
        v3_rows=rows,
        quest_records=records,
        included_cluster_ids=included_ids,
    )
    assert metrics["card_polish_unmapped_count"] == 0
    assert metrics["card_polish_registry_mapped_count"] == 0
    assert len(metadata_rows) == len(included_ids)
    for row in metadata_rows:
        card_id = str(row["card_id"])
        assert card_id.startswith("ql-")
        assert not card_id.startswith("cluster-")
        assert str(row["display_title"]).strip()
        assert str(row["start_anchor"]).strip()
        assert str(row["faction"]) in {"alliance", "horde", "shared"}
        assert row["registry_arc_id"] == ""
        assert row["suppress_continued_card"] is False
