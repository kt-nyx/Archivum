from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.check_run_semantics import SemanticCheckError, _cluster_ids_from_v3, check_run


def test_cluster_ids_from_v3_filters_quest_nodes_only() -> None:
    rows = [
        {"zone_id": "zone-a", "node_type": "quest", "cluster_id": "part-1"},
        {"zone_id": "zone-a", "node_type": "cluster", "cluster_id": "part-1-meta"},
    ]
    assert _cluster_ids_from_v3(rows, "zone-a") == {"part-1"}


def _write_minimal_run(run_root: Path, *, draft: dict[str, object]) -> None:
    (run_root / "data" / "drafts" / "zone_page").mkdir(parents=True)
    (run_root / "data" / "discovery").mkdir(parents=True)
    (run_root / "data" / "ingest").mkdir(parents=True)
    (run_root / "data" / "evidence").mkdir(parents=True)
    zone_id = "zone-example"
    (run_root / "data" / "drafts" / "zone_page" / f"{zone_id}.json").write_text(
        json.dumps(draft, indent=2),
        encoding="utf-8",
    )
    (run_root / "data" / "discovery" / "zone_quest_graph_v3.json").write_text(
        json.dumps(
            [
                {
                    "zone_id": zone_id,
                    "node_type": "quest",
                    "cluster_id": "part-1",
                    "title": "Quest A",
                    "source_link": "/wiki/Quest_A",
                }
            ],
            indent=2,
        ),
        encoding="utf-8",
    )
    (run_root / "data" / "evidence" / "evidence_packs.jsonl").write_text(
        json.dumps(
            {
                "subject_id": zone_id,
                "field_name": "quest_cluster_lore",
                "build_meta": {"subject_zone_id": zone_id, "cluster_id": "part-1"},
                "evidence_items": [{"snippet": "Narrative lore about the front lines."}],
            }
        )
        + "\n",
        encoding="utf-8",
    )


def _valid_draft() -> dict[str, object]:
    return {
        "zone_id": "zone-example",
        "name": "Example Zone",
        "major_questlines": [
            {
                "id": "cluster-part-1",
                "title": "Part 1 - Example Arc",
                "faction": "alliance",
                "cta_hook": "Crusaders push back undead forces along the ruined road.",
                "start_anchor": "Quest A",
                "chain_refs": ["quest-a"],
                "wiki_refs": ["/wiki/Quest_A"],
            }
        ],
        "location_cards": [{"id": "loc-1", "name": "Example Landmark", "summary": "A notable place."}],
        "sources": [
            {"source_id": "src-zone", "url": "https://example.test/zone"},
            {"source_id": "src-quest", "url": "https://example.test/quest"},
        ],
        "history_sections": [{"heading": "History", "body": "Past events shaped the zone."}],
    }


def test_check_run_passes_minimal_valid_run(tmp_path: Path) -> None:
    run_root = tmp_path / "run-example"
    run_root.mkdir()
    _write_minimal_run(run_root, draft=_valid_draft())
    check_run(run_root, zone_id="zone-example")


def test_check_run_fails_when_cluster_card_cap_exceeded(tmp_path: Path) -> None:
    run_root = tmp_path / "run-cap"
    run_root.mkdir()
    draft = _valid_draft()
    draft["major_questlines"] = [
        {
            "id": f"cluster-part-{index}",
            "title": f"Arc {index}",
            "faction": "shared",
            "cta_hook": f"Narrative hook for arc {index} with enough words.",
            "start_anchor": f"Quest {index}",
            "chain_refs": [f"quest-{index}"],
            "wiki_refs": [f"/wiki/Quest_{index}"],
        }
        for index in range(9)
    ]
    _write_minimal_run(run_root, draft=draft)
    with pytest.raises(SemanticCheckError, match="cluster card cap"):
        check_run(run_root, zone_id="zone-example")


def test_check_run_fails_when_hub_resolved_missing_origin(tmp_path: Path) -> None:
    run_root = tmp_path / "run-hub"
    run_root.mkdir()
    _write_minimal_run(run_root, draft=_valid_draft())
    (run_root / "data" / "ingest" / "traversal_report.json").write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "status": "fetched",
                        "role": "quest",
                        "link": "/wiki/Quest_Child",
                        "traversal_origin": "hub_resolved",
                    }
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    with pytest.raises(SemanticCheckError, match="hub_resolved_from"):
        check_run(run_root, zone_id="zone-example")


def test_check_run_validates_cluster_alignment_without_snapshots(tmp_path: Path) -> None:
    run_root = tmp_path / "run-no-snapshots"
    run_root.mkdir()
    _write_minimal_run(run_root, draft=_valid_draft())
    draft = _valid_draft()
    draft["major_questlines"] = [
        {
            "id": "cluster-unknown",
            "title": "Unknown Arc",
            "faction": "shared",
            "cta_hook": "Narrative hook for an unknown cluster with enough words.",
            "start_anchor": "Quest X",
            "chain_refs": ["quest-x"],
            "wiki_refs": ["/wiki/Quest_X"],
        }
    ]
    (run_root / "data" / "drafts" / "zone_page" / "zone-example.json").write_text(
        json.dumps(draft, indent=2),
        encoding="utf-8",
    )
    with pytest.raises(SemanticCheckError, match="unknown cluster ids"):
        check_run(run_root, zone_id="zone-example")
