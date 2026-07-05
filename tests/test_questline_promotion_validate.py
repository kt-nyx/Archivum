from __future__ import annotations

import json
from pathlib import Path

from pipeline.validate.context import build_entity_validation_context, load_validation_run_resources
from pipeline.validate.engine import validate_payload
from tests.test_questline_promotion_gate import _write_wpl_run
from tests.test_validation_engine import _validation_ready_zone_page_payload


def test_release_gate_validate_fails_wrong_pilot_anchor(tmp_path: Path) -> None:
    questlines = json.loads(
        Path("tests/fixtures/pilot/zone_page_western_plaguelands_gold.json").read_text(
            encoding="utf-8"
        )
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


def test_validation_context_loads_faction_candidates_from_finalize_decisions(
    tmp_path: Path,
) -> None:
    run_root = _write_wpl_run(tmp_path, questlines=[])
    decisions_dir = run_root / "data" / "decisions"
    decisions_dir.mkdir(parents=True, exist_ok=True)
    (decisions_dir / "prose_finalize_decisions.json").write_text(
        json.dumps(
            [
                {
                    "entity_id": "zone-western-plaguelands",
                    "stage": "major_factions.candidates",
                    "candidates": [
                        {"faction_id": "faction-argent-crusade", "name": "Argent Crusade"},
                        {"faction_id": "faction-argent-crusade", "name": "Argent Crusade"},
                    ],
                },
                {
                    "entity_id": "zone-western-plaguelands",
                    "stage": "currently.finalize",
                    "candidates": [{"name": "Ignored Stage"}],
                },
            ],
            indent=2,
        ),
        encoding="utf-8",
    )

    resources = load_validation_run_resources(run_root)
    context = build_entity_validation_context(
        entity_id="zone-western-plaguelands",
        fact_check_profile="off",
        release_gate=False,
        resources=resources,
    )

    assert context["faction_candidate_names"] == ["Argent Crusade"]
