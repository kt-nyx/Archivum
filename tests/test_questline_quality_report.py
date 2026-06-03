from __future__ import annotations

import json
from pathlib import Path

from scripts.questline_quality_report import STATUS_FAIL, evaluate_run

from tests.test_pilot_questline_gold_standard import _validation_ready_payload_with_gold_questlines
from tests.test_questline_promotion_gate import _gold_questlines, _write_wpl_run


def test_questline_quality_report_passes_gold_run(tmp_path) -> None:
    included = ["c1", "c2", "c3", "c4"]
    metadata = [
        {
            "zone_id": "zone-western-plaguelands",
            "cluster_id": cluster_id,
            "card_id": card["id"],
            "suppress_continued_card": True,
        }
        for cluster_id, card in zip(included, _gold_questlines(), strict=True)
    ]
    run_root = _write_wpl_run(
        tmp_path,
        included_cluster_ids=included,
        metadata_rows=metadata,
    )
    draft = _validation_ready_payload_with_gold_questlines()
    draft["zone_id"] = "zone-western-plaguelands"
    draft["name"] = "Western Plaguelands"
    draft_path = run_root / "data" / "drafts" / "zone_page" / "zone-western-plaguelands.json"
    draft_path.write_text(json.dumps(draft, indent=2), encoding="utf-8")
    scores = evaluate_run(run_root, zone_id="zone-western-plaguelands", pilot_questline_gate=True)
    assert len(scores) == 1
    assert scores[0].status != STATUS_FAIL


def test_questline_quality_report_fails_bad_anchor(tmp_path) -> None:
    questlines = json.loads(
        Path("tests/fixtures/pilot/zone_page_western_plaguelands_gold.json").read_text(encoding="utf-8")
    )["major_questlines"]
    questlines[0] = {**questlines[0], "start_anchor": "Wrong"}
    run_root = _write_wpl_run(tmp_path, questlines=questlines)
    scores = evaluate_run(run_root, zone_id="zone-western-plaguelands")
    assert scores[0].status == STATUS_FAIL
