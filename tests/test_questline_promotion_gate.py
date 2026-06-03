from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.discovery.pilot_questline_registry import WPL_ZONE_ID
from pipeline.discovery.questline_promotion_gate import (
    QuestlineRunArtifacts,
    check_questline_promotion,
    load_questline_run_artifacts,
)

GOLD_PATH = Path("tests/fixtures/pilot/zone_page_western_plaguelands_gold.json")


def _gold_questlines() -> list[dict]:
    gold = json.loads(GOLD_PATH.read_text(encoding="utf-8"))
    return list(gold["major_questlines"])


def _write_wpl_run(
    tmp_path: Path,
    *,
    questlines: list[dict] | None = None,
    included_cluster_ids: list[str] | None = None,
    metadata_rows: list[dict] | None = None,
) -> Path:
    run_root = tmp_path / "run-wpl-promotion"
    zone_id = WPL_ZONE_ID
    (run_root / "data" / "drafts" / "zone_page").mkdir(parents=True)
    (run_root / "data" / "discovery").mkdir(parents=True)
    draft = {
        "zone_id": zone_id,
        "name": "Western Plaguelands",
        "major_questlines": questlines if questlines is not None else _gold_questlines(),
    }
    (run_root / "data" / "drafts" / "zone_page" / f"{zone_id}.json").write_text(
        json.dumps(draft, indent=2),
        encoding="utf-8",
    )
    if included_cluster_ids is not None:
        (run_root / "data" / "discovery" / "zone_quest_cluster_rankings.json").write_text(
            json.dumps([{"zone_id": zone_id, "included_cluster_ids": included_cluster_ids}], indent=2),
            encoding="utf-8",
        )
    if metadata_rows is not None:
        (run_root / "data" / "discovery" / "zone_questline_card_metadata.json").write_text(
            json.dumps(metadata_rows, indent=2),
            encoding="utf-8",
        )
    v3_rows = []
    for card in draft["major_questlines"]:
        for index, node_id in enumerate(card.get("chain_refs") or [], start=1):
            v3_rows.append(
                {
                    "zone_id": zone_id,
                    "node_type": "quest",
                    "node_id": node_id,
                    "cluster_id": f"cluster-{card['id']}",
                    "order_in_cluster": index,
                    "title": node_id,
                    "source_link": f"/wiki/{node_id}",
                }
            )
    (run_root / "data" / "discovery" / "zone_quest_graph_v3.json").write_text(
        json.dumps(v3_rows, indent=2),
        encoding="utf-8",
    )
    if included_cluster_ids:
        evidence_lines = []
        for cluster_id in included_cluster_ids:
            evidence_lines.append(
                json.dumps(
                    {
                        "subject_id": zone_id,
                        "field_name": "quest_cluster_lore",
                        "build_meta": {"subject_zone_id": zone_id, "cluster_id": cluster_id},
                        "evidence_items": [{"snippet": f"Lore for {cluster_id}."}],
                    }
                )
            )
        (run_root / "data" / "evidence").mkdir(parents=True, exist_ok=True)
        (run_root / "data" / "evidence" / "evidence_packs.jsonl").write_text(
            "\n".join(evidence_lines) + "\n",
            encoding="utf-8",
        )
    return run_root


def test_check_questline_promotion_pilot_strict_passes_gold_shape(tmp_path: Path) -> None:
    included = ["c1", "c2", "c3", "c4"]
    metadata = [
        {
            "zone_id": WPL_ZONE_ID,
            "cluster_id": cluster_id,
            "card_id": card["id"],
            "suppress_continued_card": True,
        }
        for cluster_id, card in zip(
            included,
            _gold_questlines(),
            strict=True,
        )
    ]
    run_root = _write_wpl_run(
        tmp_path,
        included_cluster_ids=included,
        metadata_rows=metadata,
    )
    artifacts = load_questline_run_artifacts(run_root, WPL_ZONE_ID)
    artifacts = QuestlineRunArtifacts(
        zone_id=artifacts.zone_id,
        cards=_gold_questlines(),
        included_cluster_ids=included,
        metadata_by_cluster=artifacts.metadata_by_cluster,
        card_id_to_cluster_id=artifacts.card_id_to_cluster_id,
        excluded_cluster_ids=artifacts.excluded_cluster_ids,
        v3_quest_rows=artifacts.v3_quest_rows,
        pilot_expectations=artifacts.pilot_expectations,
    )
    assert not check_questline_promotion(
        artifacts,
        pilot_strict=True,
        require_rankings=True,
        require_evidence_coverage=True,
        covered_cluster_ids=set(included),
    )


def test_check_questline_promotion_fails_excluded_registry_card(tmp_path: Path) -> None:
    questlines = _gold_questlines() + [
        {
            "id": "ql-northridge-redpine",
            "title": "Northridge",
            "faction": "shared",
            "cta_hook": "Investigate the lumber mill conflict.",
            "start_anchor": "Northridge Lumber Mill",
            "chain_refs": ["quest-northridge"],
            "wiki_refs": ["/wiki/Northridge"],
            "include_decision": "include",
        }
    ]
    run_root = _write_wpl_run(tmp_path, questlines=questlines)
    artifacts = load_questline_run_artifacts(run_root, WPL_ZONE_ID)
    artifacts = QuestlineRunArtifacts(
        zone_id=artifacts.zone_id,
        cards=questlines,
        included_cluster_ids=artifacts.included_cluster_ids,
        metadata_by_cluster=artifacts.metadata_by_cluster,
        card_id_to_cluster_id=artifacts.card_id_to_cluster_id,
        excluded_cluster_ids=artifacts.excluded_cluster_ids,
        v3_quest_rows=artifacts.v3_quest_rows,
        pilot_expectations=artifacts.pilot_expectations,
    )
    errors = check_questline_promotion(artifacts, pilot_strict=True)
    assert any("excluded" in error.lower() for error in errors)
