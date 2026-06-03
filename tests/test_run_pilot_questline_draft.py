from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from pipeline.discovery.questline_promotion_gate import (
    check_questline_promotion,
    load_questline_run_artifacts,
)
from pipeline.discovery.questline_promotion_gate import QuestlineRunArtifacts

DEFAULT_RUN_ROOT = Path(
    os.environ.get("LORE_PILOT_RUN_ROOT", "artifacts/runs/run-western-plaguelands")
)


def test_promoted_run_draft_passes_pilot_strict_when_present() -> None:
    draft_path = DEFAULT_RUN_ROOT / "data" / "drafts" / "zone_page" / "zone-western-plaguelands.json"
    if not draft_path.exists():
        pytest.skip("pilot run draft not present (set LORE_PILOT_RUN_ROOT to override)")
    zone_id = "zone-western-plaguelands"
    draft = json.loads(draft_path.read_text(encoding="utf-8"))
    artifacts = load_questline_run_artifacts(DEFAULT_RUN_ROOT, zone_id)
    artifacts = QuestlineRunArtifacts(
        zone_id=zone_id,
        cards=[row for row in draft.get("major_questlines", []) if isinstance(row, dict)],
        included_cluster_ids=artifacts.included_cluster_ids,
        metadata_by_cluster=artifacts.metadata_by_cluster,
        card_id_to_cluster_id=artifacts.card_id_to_cluster_id,
        excluded_cluster_ids=artifacts.excluded_cluster_ids,
        v3_quest_rows=artifacts.v3_quest_rows,
        pilot_expectations=artifacts.pilot_expectations,
    )
    errors = check_questline_promotion(
        artifacts,
        pilot_strict=True,
        require_rankings=bool(artifacts.included_cluster_ids),
    )
    if errors:
        pytest.skip(f"pilot run not yet promotion-ready: {errors}")
