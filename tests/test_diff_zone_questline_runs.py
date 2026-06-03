from __future__ import annotations

from scripts.diff_zone_questline_runs import build_diff

from tests.test_questline_promotion_gate import _write_wpl_run


def test_diff_detects_anchor_change(tmp_path) -> None:
    import json
    from pathlib import Path

    questlines = json.loads(
        Path("tests/fixtures/pilot/zone_page_western_plaguelands_gold.json").read_text(encoding="utf-8")
    )["major_questlines"]
    baseline_root = _write_wpl_run(tmp_path / "baseline", questlines=questlines)
    changed = [dict(card) for card in questlines]
    changed[0] = {**changed[0], "start_anchor": "Changed Anchor"}
    candidate_root = _write_wpl_run(tmp_path / "candidate", questlines=changed)
    diff = build_diff(
        baseline_root=baseline_root,
        candidate_root=candidate_root,
        zone_id="zone-western-plaguelands",
        notes="test",
    )
    assert diff["card_changes"]
    assert diff["card_changes"][0]["card_id"] == "ql-andorhal-horde"
