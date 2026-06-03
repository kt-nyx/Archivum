from __future__ import annotations

import json
from pathlib import Path

from pipeline.validate.context import build_entity_validation_context, load_validation_run_resources
from pipeline.validate.engine import validate_payload

from tests.test_questline_promotion_gate import _write_wpl_run
from tests.test_validation_engine import _validation_ready_zone_page_payload


def test_release_gate_validate_fails_wrong_pilot_anchor(tmp_path: Path) -> None:
    questlines = json.loads(
        Path("tests/fixtures/pilot/zone_page_western_plaguelands_gold.json").read_text(encoding="utf-8")
    )["major_questlines"]
    questlines[0] = {**questlines[0], "start_anchor": "Wrong Anchor Title"}
    run_root = _write_wpl_run(tmp_path, questlines=questlines)
    resources = load_validation_run_resources(run_root)
    draft = _validation_ready_zone_page_payload()
    draft["zone_id"] = "zone-western-plaguelands"
    draft["name"] = "Western Plaguelands"
    draft["major_questlines"] = questlines
    report = validate_payload(
        "zone_page",
        draft,
        validation_context=build_entity_validation_context(
            entity_id="zone-western-plaguelands",
            fact_check_profile="off",
            release_gate=True,
            resources=resources,
        ),
    )
    codes = {issue.code for issue in report.issues}
    assert "questline_promotion.pilot_start_anchor" in codes
